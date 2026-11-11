"""Index der verfügbaren Tage (days.json).

Der aktuelle Tag nutzt die klassischen Dateien (snow_grid.npz, snow_overlay.png,
snow_meta.json; "file": ""). Jeder andere Tag ist eine einzelne Datei
„day-YYYY-MM-DD.npz“ mit Raster und Metadaten:

    {"created_at": "...", "days": [
        {"date": "2026-11-04", "kind": "past",     "file": "day-2026-11-04.npz", ...},
        {"date": "2026-11-11", "kind": "today",    "file": "", ...},
        {"date": "2026-11-12", "kind": "forecast", "file": "day-2026-11-12.npz", ...}]}

Vergangene Tage bleiben dauerhaft im Index (die Historie wächst mit jedem
Import), Prognosen werden bei jedem Lauf ersetzt.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from . import config

DAY_FILE_RE = re.compile(r"^day-\d{4}-\d{2}-\d{2}\.npz$")


def day_file(day: date) -> str:
    return f"day-{day.isoformat()}.npz"


def entry(meta: dict, kind: str, file: str) -> dict:
    return {
        "date": datetime.fromisoformat(meta["valid_time"]).date().isoformat(),
        "kind": kind,
        "valid_time": meta["valid_time"],
        "run": meta.get("run", meta["valid_time"]),
        "created_at": meta["created_at"],
        "source": meta.get("source", ""),
        "file": file,
    }


def merge(previous: dict | None, new_entries: list[dict]) -> list[dict]:
    """Neue Einträge über die alten legen. Von früher bleiben nur vergangene
    Tage erhalten – alte Prognosen und der alte „heute“-Eintrag sind überholt."""
    by_date = {e["date"]: e for e in (previous or {}).get("days", []) if e.get("kind") == "past"}
    today = next((e["date"] for e in new_entries if e["kind"] == "today"), None)
    for e in new_entries:
        by_date[e["date"]] = e
    if today:
        # Ein vergangener Tag darf nicht neben dem gleichnamigen „heute“ stehen bleiben.
        by_date = {d: e for d, e in by_date.items() if d != today or e["kind"] == "today"}
    return sorted(by_date.values(), key=lambda e: e["date"])


def write_index(out_dir: Path, entries: list[dict]) -> dict:
    index = {"created_at": datetime.now(timezone.utc).isoformat(), "days": entries}
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / (config.DAYS_FILE + ".tmp")
    tmp.write_text(json.dumps(index, indent=2))
    os.replace(tmp, out_dir / config.DAYS_FILE)
    return index


def read_index(data_dir: Path) -> dict | None:
    try:
        return json.loads((data_dir / config.DAYS_FILE).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def fetch_remote_index(base_url: str) -> dict | None:
    """days.json von DATA_URL (z. B. dem GitHub-Release), falls vorhanden."""
    import httpx

    if not base_url:
        return None
    resp = httpx.get(f"{base_url}/{config.DAYS_FILE}", timeout=60, follow_redirects=True)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def list_days(data_dir: Path) -> list[dict]:
    """Verfügbare Tage; ohne Index (ältere Daten, Demo) nur der aktuelle."""
    index = read_index(data_dir)
    if index and index.get("days"):
        return index["days"]
    try:
        meta = json.loads((data_dir / config.META_FILE).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return [entry(meta, "today", "")]


def remove_unlisted(data_dir: Path, days: list[dict]) -> None:
    keep = {e["file"] for e in days}
    for path in data_dir.glob("day-*.npz"):
        if DAY_FILE_RE.match(path.name) and path.name not in keep:
            path.unlink(missing_ok=True)
