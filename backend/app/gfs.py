"""Import der Schneehöhe aus dem NOAA-Wettermodell GFS.

GFS läuft viermal täglich (00/06/12/18 UTC) und ist ca. 4 Stunden nach dem
Lauf verfügbar – kostenlos und ohne Konto. Variable SNOD (Schneehöhe in
Metern) auf dem 0,25°-Raster, plus Land-See-Maske gegen Schnee auf Meereis.

Pro Import entstehen:
  - heute:      Analyse (f000) des jüngsten Laufs
  - Prognose:   die nächsten Tage um 12 UTC aus demselben Lauf
  - Vergangen:  fehlende Tage als Analyse des 12-UTC-Laufs dieses Tages.
                Bereits vorhandene Tage bleiben, die Historie wächst also;
                mit `backfill_from` lassen sich ältere Tage nachladen.

Quellen (in dieser Reihenfolge):
  1. NOMADS-Filter: schneidet die Felder serverseitig aus (~1 MB), nur ~10 Tage.
  2. AWS Open Data: Byte-Bereiche anhand der .idx-Datei, Archiv seit 2021.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

from . import config
from . import days as days_index
from .grid import meters_to_cm, save_dataset, save_day

log = logging.getLogger(__name__)

NOMADS_FILTER = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
AWS_BASE = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
FIELDS = ("SNOD", "LAND")  # Schneehöhe [m], Landanteil [0/1]
CYCLE_HOURS = 6
MIN_LAG_HOURS = 3.5  # früher ist der Lauf praktisch nie vollständig
STALE_AFTER_DAYS = 2
NOMADS_KEEP_DAYS = 9  # NOMADS hält nur die letzten ~10 Tage vor
ATMOS_SINCE = datetime(2021, 3, 22, tzinfo=timezone.utc)  # davor ohne „/atmos“
PAST_HOURS = (12, 0, 18, 6)  # bevorzugter Lauf für vergangene Tage

SOURCE = "NOAA GFS (SNOD, Analyse)"
SOURCE_FORECAST = "NOAA GFS (SNOD, Prognose +{h} h)"
NOTE = "Modellierte Rasterwerte (ca. 25 km), keine Punktmessungen."
DISCLAIMER = (
    "Die Schneehöhen stammen aus dem Wettermodell NOAA GFS (Analyse des jüngsten Laufs) "
    "und sind modellierte Mittelwerte für Rasterzellen von ca. 25 × 25 km – keine exakten "
    "Messungen an einem bestimmten Ort. Besonders in den Bergen kann die Schneelage vor Ort "
    "deutlich abweichen."
)
DISCLAIMER_FORECAST = (
    "Prognose aus dem Wettermodell NOAA GFS – je weiter in der Zukunft, desto unsicherer. "
    "Modellierte Mittelwerte für Rasterzellen von ca. 25 × 25 km, keine Messungen."
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


def _paths(cycle: datetime, fhour: int = 0) -> tuple[str, str]:
    hh = f"{cycle.hour:02d}"
    directory = f"gfs.{cycle:%Y%m%d}/{hh}" + ("/atmos" if cycle >= ATMOS_SINCE else "")
    return directory, f"gfs.t{hh}z.pgrb2.0p25.f{fhour:03d}"


def _download_nomads(client: httpx.Client, cycle: datetime, fhour: int) -> bytes:
    if datetime.now(timezone.utc) - cycle > timedelta(days=NOMADS_KEEP_DAYS):
        raise RuntimeError("zu alt für NOMADS")
    directory, filename = _paths(cycle, fhour)
    params = {"dir": f"/{directory}", "file": filename, "lev_surface": "on"}
    params.update({f"var_{name}": "on" for name in FIELDS})
    resp = client.get(NOMADS_FILTER, params=params)
    resp.raise_for_status()
    return resp.content


def _download_aws(client: httpx.Client, cycle: datetime, fhour: int) -> bytes:
    directory, filename = _paths(cycle, fhour)
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


def download(cycle: datetime, target: Path, fhour: int = 0) -> None:
    errors = []
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        for fetch in (_download_nomads, _download_aws):
            try:
                data = fetch(client, cycle, fhour)
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


def _meta_kwargs(cycle: datetime, fhour: int, kind: str) -> dict:
    forecast = fhour > 0
    return {
        "source": SOURCE_FORECAST.format(h=fhour) if forecast else SOURCE,
        "valid_time": cycle + timedelta(hours=fhour),
        "note": NOTE,
        "extra": {
            "kind": kind,
            "run": cycle.isoformat(),
            "forecast_hours": fhour,
            "stale_after_days": STALE_AFTER_DAYS,
            "disclaimer": DISCLAIMER_FORECAST if forecast else DISCLAIMER,
        },
    }


def process_file(
    grib_path: Path,
    cycle: datetime,
    out_dir: Path = config.DATA_DIR,
    *,
    fhour: int = 0,
    kind: str = "today",
    file: str = "",
) -> dict:
    """GRIB2 → aktueller Datensatz (file="") oder Tagesdatei (file="day-….npz")."""
    depth_m, lat, lon = read_grib(grib_path)
    depth_cm = meters_to_cm(depth_m)
    kwargs = _meta_kwargs(cycle, fhour, kind)
    if file:
        return save_day(out_dir / file, depth_cm, lat, lon, **kwargs)
    return save_dataset(out_dir, depth_cm, lat, lon, **kwargs)


def _utc(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=timezone.utc)


def _try(tmp: Path, cycle: datetime, fhour: int, out_dir: Path, kind: str, file: str) -> dict:
    target = tmp / f"gfs_{cycle:%Y%m%d%H}_f{fhour:03d}.grib2"
    download(cycle, target, fhour)
    try:
        return process_file(target, cycle, out_dir, fhour=fhour, kind=kind, file=file)
    finally:
        target.unlink(missing_ok=True)


def ingest_latest(
    out_dir: Path = config.DATA_DIR,
    *,
    previous: dict | None = None,
    past_days: int = 10,
    forecast_days: int = 7,
    backfill_from: date | None = None,
) -> dict:
    """Heute + Prognose + fehlende vergangene Tage laden und days.json schreiben.
    `previous` ist der bisherige Index (lokal oder aus dem Release)."""
    entries: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)

        # 1) Heute: Analyse des jüngsten verfügbaren Laufs (Pflicht)
        last_error: Exception | None = None
        for cycle in candidate_cycles(datetime.now(timezone.utc)):
            try:
                log.info("Heute: GFS-Lauf %s UTC …", f"{cycle:%Y-%m-%d %H}")
                meta = _try(tmp, cycle, 0, out_dir, "today", "")
                break
            except Exception as exc:  # Lauf (noch) nicht verfügbar o. Ä.
                log.warning("  Lauf %s nicht verfügbar: %s", f"{cycle:%Y-%m-%d %H}", exc)
                last_error = exc
        else:
            raise RuntimeError(f"Kein GFS-Lauf verfügbar (letzter Fehler: {last_error})")
        entries.append(days_index.entry(meta, "today", ""))
        base = cycle.date()

        # 2) Prognose: die nächsten Tage um 12 UTC aus demselben Lauf
        for offset in range(1, forecast_days + 1):
            day = base + timedelta(days=offset)
            fhour = int((_utc(day, 12) - cycle).total_seconds() // 3600)
            file = days_index.day_file(day)
            try:
                log.info("Prognose %s (+%d h) …", day, fhour)
                entries.append(days_index.entry(_try(tmp, cycle, fhour, out_dir, "forecast", file), "forecast", file))
            except Exception as exc:
                log.warning("  Prognose %s fehlgeschlagen: %s", day, exc)

        # 3) Vergangene Tage, die noch fehlen
        have = {e["date"] for e in (previous or {}).get("days", []) if e.get("kind") == "past"}
        first = min(base - timedelta(days=past_days), backfill_from or base)
        day = first
        while day < base:
            if day.isoformat() not in have:
                file = days_index.day_file(day)
                for hour in PAST_HOURS:
                    try:
                        log.info("Vergangen %s (Lauf %02d UTC) …", day, hour)
                        meta = _try(tmp, _utc(day, hour), 0, out_dir, "past", file)
                        entries.append(days_index.entry(meta, "past", file))
                        break
                    except Exception as exc:
                        log.warning("  %s %02d UTC nicht verfügbar: %s", day, hour, exc)
            day += timedelta(days=1)

    index = days_index.write_index(out_dir, days_index.merge(previous, entries))
    log.info("Fertig: heute = %s, %d Tage im Index", meta_today(entries)["valid_time"], len(index["days"]))
    return index


def meta_today(entries: list[dict]) -> dict:
    return next(e for e in entries if e["kind"] == "today")
