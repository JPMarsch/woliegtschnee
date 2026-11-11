"""Import der aktuellen Schneehöhe aus dem NOAA-Wettermodell GFS.

GFS läuft viermal täglich (00/06/12/18 UTC) und ist ca. 4 Stunden nach dem
Lauf verfügbar – kostenlos und ohne Konto. Wir nehmen die Analyse (f000) des
jüngsten Laufs, Variable SNOD (Schneehöhe in Metern) auf dem 0,25°-Raster,
plus die Land-See-Maske, um Schnee auf Meereis auszublenden.

Quellen (in dieser Reihenfolge):
  1. NOMADS-Filter: schneidet die benötigten Felder serverseitig aus (~1 MB).
  2. AWS Open Data: Byte-Bereiche anhand der .idx-Datei (Fallback).
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

from . import config
from .grid import meters_to_cm, save_dataset

log = logging.getLogger(__name__)

NOMADS_FILTER = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
AWS_BASE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
FIELDS = ("SNOD", "LAND")  # Schneehöhe [m], Landanteil [0/1]
CYCLE_HOURS = 6
MIN_LAG_HOURS = 3.5  # früher ist der Lauf praktisch nie vollständig
STALE_AFTER_DAYS = 2

SOURCE = "NOAA GFS (SNOD, Analyse)"
NOTE = "Modellierte Rasterwerte (ca. 25 km), keine Punktmessungen."
DISCLAIMER = (
    "Die Schneehöhen stammen aus dem Wettermodell NOAA GFS (Analyse des jüngsten Laufs) "
    "und sind modellierte Mittelwerte für Rasterzellen von ca. 25 × 25 km – keine exakten "
    "Messungen an einem bestimmten Ort. Besonders in den Bergen kann die Schneelage vor Ort "
    "deutlich abweichen."
)


def candidate_cycles(now: datetime, max_lag_hours: int = 48) -> list[datetime]:
    """Modellläufe vom jüngsten möglichen rückwärts."""
    newest = now - timedelta(hours=MIN_LAG_HOURS)
    newest = newest.replace(hour=newest.hour - newest.hour % CYCLE_HOURS, minute=0, second=0, microsecond=0)
    oldest = now - timedelta(hours=max_lag_hours)
    cycles = []
    cycle = newest
    while cycle >= oldest:
        cycles.append(cycle)
        cycle -= timedelta(hours=CYCLE_HOURS)
    return cycles


def _paths(cycle: datetime) -> tuple[str, str]:
    hh = f"{cycle.hour:02d}"
    return f"gfs.{cycle:%Y%m%d}/{hh}/atmos", f"gfs.t{hh}z.pgrb2.0p25.f000"


def _download_nomads(client: httpx.Client, cycle: datetime) -> bytes:
    directory, filename = _paths(cycle)
    params = {"dir": f"/{directory}", "file": filename, "lev_surface": "on"}
    params.update({f"var_{name}": "on" for name in FIELDS})
    resp = client.get(NOMADS_FILTER, params=params)
    resp.raise_for_status()
    return resp.content


def _download_aws(client: httpx.Client, cycle: datetime) -> bytes:
    directory, filename = _paths(cycle)
    url = f"{AWS_BASE}/{directory}/{filename}"
    idx = client.get(f"{url}.idx").raise_for_status().text.splitlines()
    # Zeilenformat: "578:411433104:d=2026111000:SNOD:surface:anl:"
    offsets = [int(line.split(":")[1]) for line in idx]
    parts = []
    for i, line in enumerate(idx):
        _, _, _, var, level, *_ = line.split(":")
        if var in FIELDS and level == "surface":
            end = f"{offsets[i + 1] - 1}" if i + 1 < len(offsets) else ""
            resp = client.get(url, headers={"Range": f"bytes={offsets[i]}-{end}"})
            resp.raise_for_status()
            parts.append(resp.content)
    if len(parts) != len(FIELDS):
        raise RuntimeError(f"Felder {FIELDS} nicht vollständig in {filename}")
    return b"".join(parts)


def download(cycle: datetime, target: Path) -> None:
    errors = []
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for fetch in (_download_nomads, _download_aws):
            try:
                data = fetch(client, cycle)
                if not data.startswith(b"GRIB"):
                    raise RuntimeError("Antwort ist keine GRIB-Datei")
                target.write_bytes(data)
                return
            except Exception as exc:
                errors.append(f"{fetch.__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def read_grib(path: Path):
    import xarray as xr

    with xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""}) as ds:
        return grid_from_dataset(ds)


def grid_from_dataset(ds):
    """xarray-Dataset (cfgrib-Namen sde/lsm) → Schneehöhe [m], lat, lon.
    Wasser und Meereis werden zu NaN, damit dort nichts gefunden wird."""
    depth = np.asarray(ds["sde"].squeeze(drop=True).values, dtype=np.float64)
    if "lsm" in ds:
        land = np.asarray(ds["lsm"].squeeze(drop=True).values, dtype=np.float64)
        depth = np.where(land >= 0.5, depth, np.nan)
    return (
        depth,
        np.asarray(ds["latitude"].values, dtype=np.float64),
        np.asarray(ds["longitude"].values, dtype=np.float64),
    )


def process_file(grib_path: Path, cycle: datetime, out_dir: Path = config.DATA_DIR) -> dict:
    depth_m, lat, lon = read_grib(grib_path)
    return save_dataset(
        out_dir,
        meters_to_cm(depth_m),
        lat,
        lon,
        source=SOURCE,
        valid_time=cycle,
        note=NOTE,
        extra={"stale_after_days": STALE_AFTER_DAYS, "disclaimer": DISCLAIMER},
    )


def ingest_latest(out_dir: Path = config.DATA_DIR) -> dict:
    """Lädt den jüngsten verfügbaren GFS-Lauf und schreibt das verarbeitete Raster."""
    last_error: Exception | None = None
    with tempfile.TemporaryDirectory() as tmp:
        for cycle in candidate_cycles(datetime.now(timezone.utc)):
            target = Path(tmp) / f"gfs_snod_{cycle:%Y%m%d%H}.grib2"
            try:
                log.info("Lade GFS-Schneehöhe, Lauf %s UTC …", f"{cycle:%Y-%m-%d %H}")
                download(cycle, target)
            except Exception as exc:  # Lauf (noch) nicht verfügbar o. Ä.
                log.warning("  Lauf %s nicht verfügbar: %s", f"{cycle:%Y-%m-%d %H}", exc)
                last_error = exc
                continue
            meta = process_file(target, cycle, out_dir)
            log.info("Fertig: Datenstand %s", meta["valid_time"])
            return meta
    raise RuntimeError(f"Kein GFS-Lauf verfügbar (letzter Fehler: {last_error})")
