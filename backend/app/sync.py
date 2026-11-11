"""Hintergrundaufgaben, damit der Server ohne manuelles Zutun aktuell bleibt.

- DATA_URL gesetzt: regelmäßig fertig verarbeitete Dateien von dort holen
  (empfohlen; die GitHub Action veröffentlicht sie täglich als Release).
- INGEST_ON_SERVER=1: direkt im Server importieren (INGEST_SOURCE=gfs alle 6 h,
  INGEST_SOURCE=era5 einmal täglich).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import httpx

from . import config
from .days import read_index, remove_unlisted

log = logging.getLogger(__name__)


def _local_meta() -> dict:
    try:
        return json.loads((config.DATA_DIR / config.META_FILE).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def sync_from_url() -> bool:
    """Lädt neue Daten von DATA_URL. Gibt True zurück, wenn aktualisiert wurde.
    Geholt werden der aktuelle Tag und days.json; andere Tage lädt der Server
    erst, wenn jemand sie auswählt."""
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        updated = _sync_current(client)
        return _sync_days_index(client) or updated


def _sync_days_index(client: httpx.Client) -> bool:
    resp = client.get(f"{config.DATA_URL}/{config.DAYS_FILE}")
    if resp.status_code == 404:
        return False
    remote = resp.raise_for_status().json()
    if remote == read_index(config.DATA_DIR):
        return False
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.DATA_DIR / f"{config.DAYS_FILE}.download"
    tmp.write_text(json.dumps(remote, indent=2))
    os.replace(tmp, config.DATA_DIR / config.DAYS_FILE)
    remove_unlisted(config.DATA_DIR, remote.get("days", []))
    log.info("Tagesindex aktualisiert: %d Tage", len(remote.get("days", [])))
    return True


def _sync_current(client: httpx.Client) -> bool:
    remote = client.get(f"{config.DATA_URL}/{config.META_FILE}").raise_for_status().json()
    if remote.get("created_at") == _local_meta().get("created_at"):
        return False
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in (config.GRID_FILE, config.OVERLAY_FILE):
        tmp = config.DATA_DIR / f"{name}.download"
        with client.stream("GET", f"{config.DATA_URL}/{name}") as resp, open(tmp, "wb") as f:
            resp.raise_for_status()
            for chunk in resp.iter_bytes():
                f.write(chunk)
        os.replace(tmp, config.DATA_DIR / name)
    tmp_meta = config.DATA_DIR / f"{config.META_FILE}.download"
    tmp_meta.write_text(json.dumps(remote, indent=2))
    os.replace(tmp_meta, config.DATA_DIR / config.META_FILE)
    log.info("Neue Schneedaten von DATA_URL: %s", remote.get("valid_time"))
    return True


def _needs_ingest(max_age_hours: float) -> bool:
    meta = _local_meta()
    if not meta or meta.get("demo"):
        return True
    created = datetime.fromisoformat(meta["created_at"])
    return (datetime.now(timezone.utc) - created).total_seconds() > max_age_hours * 3600


def _loop(task, interval_s: float, name: str, run_first: bool = True):
    while True:
        if run_first:
            try:
                task()
            except Exception:
                log.exception("%s fehlgeschlagen", name)
        run_first = True
        time.sleep(interval_s)


def start_background_jobs():
    if config.DATA_URL:
        # Beim Start (z. B. nach dem Aufwachen auf Render Free) einmal direkt
        # synchronisieren, damit die erste Anfrage nicht die Demo-Daten sieht.
        try:
            sync_from_url()
        except Exception:
            log.exception("Erster Daten-Sync fehlgeschlagen")
        threading.Thread(
            target=_loop,
            args=(sync_from_url, config.DATA_SYNC_HOURS * 3600, "Daten-Sync", False),
            daemon=True,
        ).start()
    if config.INGEST_ON_SERVER:
        if config.INGEST_SOURCE == "era5":
            from .era5 import ingest_latest

            max_age_hours, name = 20, "ERA5-Import"
        else:
            from .gfs import ingest_latest

            max_age_hours, name = 5.5, "GFS-Import"

        def ingest_if_due():
            if _needs_ingest(max_age_hours):
                ingest_latest(config.DATA_DIR, previous=read_index(config.DATA_DIR))

        threading.Thread(target=_loop, args=(ingest_if_due, 1800, name), daemon=True).start()
