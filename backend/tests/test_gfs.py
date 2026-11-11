"""GFS-Import: Laufauswahl und Aufbereitung eines cfgrib-artigen Datasets."""

from datetime import datetime, timezone

import numpy as np
import pytest

from app import gfs
from app.grid import NODATA, load_dataset, meters_to_cm, save_dataset

xr = pytest.importorskip("xarray")


def test_candidate_cycles_skip_unfinished_run():
    now = datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc)
    cycles = gfs.candidate_cycles(now, max_lag_hours=24)
    # 06 UTC ist um 09 UTC noch nicht fertig (< 3,5 h) → zuerst 00 UTC
    assert cycles[0] == datetime(2026, 11, 11, 0, tzinfo=timezone.utc)
    assert cycles[1] == datetime(2026, 11, 10, 18, tzinfo=timezone.utc)
    assert all(c.hour % 6 == 0 for c in cycles)
    assert cycles[-1] >= now.replace(day=10)


def test_candidate_cycles_around_midnight():
    now = datetime(2026, 11, 11, 2, 0, tzinfo=timezone.utc)
    assert gfs.candidate_cycles(now)[0] == datetime(2026, 11, 10, 18, tzinfo=timezone.utc)


def test_grid_from_gfs_like_dataset(tmp_path):
    lat = np.arange(90, -90.01, -0.25)
    lon = np.arange(0, 360, 0.25)  # GFS: 0..360
    sde = np.zeros((len(lat), len(lon)), dtype=np.float32)
    lsm = np.ones_like(sde)
    li = lambda v: int(np.argmin(np.abs(lat - v)))
    lo = lambda v: int(np.argmin(np.abs(lon - v)))
    sde[li(62), lo(129.75)] = 0.24  # Jakutsk, 24 cm
    sde[li(85), lo(0)] = 0.4  # Schnee auf Meereis → ausblenden
    lsm[li(85), lo(0)] = 0.0
    sde[li(0), lo(330)] = np.nan  # Ozean
    lsm[li(0), lo(330)] = 0.0
    ds = xr.Dataset(
        {"sde": (("latitude", "longitude"), sde), "lsm": (("latitude", "longitude"), lsm)},
        coords={"latitude": lat, "longitude": lon},
    )

    depth_m, glat, glon = gfs.grid_from_dataset(ds)
    cycle = datetime(2026, 11, 10, 0, tzinfo=timezone.utc)
    meta = save_dataset(
        tmp_path, meters_to_cm(depth_m), glat, glon, source=gfs.SOURCE, valid_time=cycle,
        extra={"stale_after_days": gfs.STALE_AFTER_DAYS},
    )
    depth, glat, glon, saved = load_dataset(tmp_path)

    assert saved["stale_after_days"] == 2 and meta["resolution_deg"] == 0.25
    at = lambda la, lo_: depth[int(np.argmin(np.abs(glat - la))), int(np.argmin(np.abs(glon - lo_)))]
    assert at(62, 129.75) == 24
    assert at(85, 0) == NODATA
    assert at(0, -30) == NODATA
    assert at(48, 11.5) == 0
