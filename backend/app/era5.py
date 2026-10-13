"""Import der Schneehöhe aus Copernicus ERA5-Land über die CDS-API.

Voraussetzung: kostenloses Konto auf https://cds.climate.copernicus.eu,
akzeptierte Lizenz für „ERA5-Land hourly data“ und ein API-Key – entweder in
~/.cdsapirc oder in den Umgebungsvariablen CDSAPI_URL / CDSAPI_KEY.

ERA5-Land erscheint mit rund 5 Tagen Verzögerung. Wir probieren daher die
jüngsten Tage absteigend durch, bis einer verfügbar ist.
"""

from __future__ import annotations

import logging
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import config
from .grid import meters_to_cm, save_dataset

log = logging.getLogger(__name__)

DATASET = "reanalysis-era5-land"
VARIABLE = "snow_depth"  # Schneehöhe in Metern (Kurzname „sde“)
HOUR = "00:00"


def _download(day: date, target: Path) -> None:
    import cdsapi  # nur für den Import nötig

    client = cdsapi.Client(quiet=True)
    client.retrieve(
        DATASET,
        {
            "variable": [VARIABLE],
            "year": f"{day.year}",
            "month": f"{day.month:02d}",
            "day": [f"{day.day:02d}"],
            "time": [HOUR],
            "data_format": "netcdf",
            "download_format": "unarchived",
        },
        str(target),
    )


def _read_netcdf(path: Path):
    import xarray as xr

    with xr.open_dataset(path) as ds:
        name = "sde" if "sde" in ds.data_vars else next(iter(ds.data_vars))
        da = ds[name].squeeze(drop=True)
        lat_name = "latitude" if "latitude" in da.dims else "lat"
        lon_name = "longitude" if "longitude" in da.dims else "lon"
        da = da.transpose(lat_name, lon_name)
        return (
            np.asarray(da.values, dtype=np.float64),
            np.asarray(da[lat_name].values, dtype=np.float64),
            np.asarray(da[lon_name].values, dtype=np.float64),
        )


def process_file(nc_path: Path, day: date, out_dir: Path = config.DATA_DIR) -> dict:
    depth_m, lat, lon = _read_netcdf(nc_path)
    valid_time = datetime(day.year, day.month, day.day, int(HOUR[:2]), tzinfo=timezone.utc)
    return save_dataset(
        out_dir,
        meters_to_cm(depth_m),
        lat,
        lon,
        source="Copernicus ERA5-Land (snow_depth)",
        valid_time=valid_time,
        note="Modellierte Rasterwerte (ca. 9 km), keine Punktmessungen.",
    )


def ingest_latest(out_dir: Path = config.DATA_DIR, max_lag_days: int = 14, min_lag_days: int = 4) -> dict:
    """Lädt den jüngsten verfügbaren Tag und schreibt das verarbeitete Raster."""
    today = datetime.now(timezone.utc).date()
    last_error: Exception | None = None
    with tempfile.TemporaryDirectory() as tmp:
        for lag in range(min_lag_days, max_lag_days + 1):
            day = today - timedelta(days=lag)
            target = Path(tmp) / f"era5land_sde_{day.isoformat()}.nc"
            try:
                log.info("Lade ERA5-Land snow_depth für %s …", day)
                _download(day, target)
            except Exception as exc:  # Tag (noch) nicht verfügbar o. Ä.
                log.warning("  %s nicht verfügbar: %s", day, exc)
                last_error = exc
                continue
            meta = process_file(target, day, out_dir)
            log.info("Fertig: Datenstand %s", meta["valid_time"])
            return meta
    raise RuntimeError(f"Kein ERA5-Land-Tag verfügbar (letzter Fehler: {last_error})")
