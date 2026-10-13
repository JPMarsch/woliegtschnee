"""Verarbeitung einer NetCDF-Datei im Format, das die CDS-API für ERA5-Land liefert."""

from datetime import date

import numpy as np
import pytest

from app.era5 import process_file
from app.grid import NODATA, load_dataset

xr = pytest.importorskip("xarray")


def test_process_era5_like_netcdf(tmp_path):
    lat = np.round(np.arange(90, -90.01, -0.5), 2)
    lon = np.round(np.arange(0, 360, 0.5), 2)  # ERA5-Land: 0..360
    sde = np.full((1, len(lat), len(lon)), np.nan, dtype=np.float32)  # Meer = NaN
    li = lambda v: int(np.argmin(np.abs(lat - v)))
    lo = lambda v: int(np.argmin(np.abs(lon - v)))
    sde[0, li(47), lo(11)] = 0.354  # Alpen, 35 cm
    sde[0, li(40), lo(254)] = 0.0  # Colorado, Land ohne Schnee (-106° → 254°)
    sde[0, li(40), lo(255)] = 1.2  # 120 cm
    ds = xr.Dataset(
        {"sde": (("valid_time", "latitude", "longitude"), sde, {"units": "m"})},
        coords={"valid_time": [np.datetime64("2026-01-15T00:00")], "latitude": lat, "longitude": lon},
    )
    nc = tmp_path / "in.nc"
    ds.to_netcdf(nc)

    meta = process_file(nc, date(2026, 1, 15), tmp_path / "out")
    depth, glat, glon, saved_meta = load_dataset(tmp_path / "out")

    assert meta["valid_time"].startswith("2026-01-15") and saved_meta["demo"] is False
    assert glon.min() >= -180 and glon.max() < 180 and np.all(np.diff(glon) > 0)
    at = lambda la, lo_: depth[int(np.argmin(np.abs(glat - la))), int(np.argmin(np.abs(glon - lo_)))]
    assert at(47, 11) == 35
    assert at(40, -106) == 0
    assert at(40, -105) == 120
    assert at(0, -30) == NODATA
