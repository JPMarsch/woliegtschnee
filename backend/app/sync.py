"""Hintergrundaufgaben, damit der Server ohne manuelles Zutun aktuell bleibt.

- DATA_URL gesetzt: regelmäßig fertig verarbeitete Dateien von dort holen
  (empfohlen; die GitHub Action veröffentlicht sie täglich als Release).
- INGEST_ON_SERVER=1: ERA5-Land einmal täglich direkt im Server importieren.
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

log = logging.getLogger(__name__)


def _local_meta() -> dict:
    try:
        return json.loads((config.DATA_DIR / config.META_FILE).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def sync_from_url() -> bool:
    """Lädt neue Daten von DATA_URL. Gibt True zurück, wenn aktualisiert wurde."""
    with httpx.Client(timeout=120, follow_redirects=True) as client:
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


def _needs_ingest() -> bool:
    meta = _local_meta()
    if not meta or meta.get("demo"):
        return True
    created = datetime.fromisoformat(meta["created_at"])
    return (datetime.now(timezone.utc) - created).total_seconds() > 20 * 3600


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
        from .era5 import ingest_latest

        def ingest_if_due():
            if _needs_ingest():
                ingest_latest(config.DATA_DIR)

        threading.Thread(target=_loop, args=(ingest_if_due, 3600, "ERA5-Import"), daemon=True).start()
