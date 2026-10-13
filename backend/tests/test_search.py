from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.geo import haversine_km
from app.grid import NODATA, load_dataset, meters_to_cm, normalize_lonlat, save_dataset
from app.snowdata import SnowIndex

STEP = 1.0
LAT = np.arange(90.0, -90.0 - STEP / 2, -STEP)
LON = np.arange(-180.0, 180.0, STEP)


def make_index(cells: dict, valid_time=None, nodata_elsewhere=False):
    depth = np.full((len(LAT), len(LON)), NODATA if nodata_elsewhere else 0, dtype=np.uint16)
    for (la, lo), cm in cells.items():
        depth[int(round(90 - la)), int(round(lo + 180))] = cm
    vt = valid_time or datetime.now(timezone.utc) - timedelta(days=5)
    return SnowIndex(depth, LAT.astype(np.float32), LON.astype(np.float32), {"valid_time": vt.isoformat()})


def test_haversine_known_distance():
    # München → Innsbruck ≈ 98 km
    assert haversine_km(48.137, 11.575, 47.269, 11.404) == pytest.approx(97.6, abs=1.5)


def test_nearest_respects_min_depth():
    idx = make_index({(48, 11): 5, (47, 11): 12, (40, 11): 60})
    assert idx.nearest(48, 11, 5).depth_cm == 5
    assert idx.nearest(48, 11, 6).depth_cm == 12
    assert (idx.nearest(48, 11, 10).lat, idx.nearest(48, 11, 10).lon) == (47, 11)
    assert idx.nearest(48, 11, 13).depth_cm == 60
    assert idx.nearest(48, 11, 60).depth_cm == 60
    assert idx.nearest(48, 11, 61) is None


@pytest.mark.parametrize("min_cm", [1, 5, 10, 20, 50])
def test_result_never_below_threshold(min_cm):
    rng = np.random.default_rng(1)
    cells = {(int(la), int(lo)): int(cm) for la, lo, cm in zip(
        rng.integers(-80, 80, 400), rng.integers(-179, 179, 400), rng.integers(1, 100, 400))}
    idx = make_index(cells)
    for la, lo in [(52.5, 13.4), (-33.9, 151.2), (40.7, -74.0), (-1.3, 36.8), (35.7, 139.7)]:
        hit = idx.nearest(la, lo, min_cm)
        assert hit.depth_cm >= min_cm
        # Brute Force: es gibt keine nähere passende Zelle
        best = min(haversine_km(la, lo, c[0], c[1]) for c, cm in cells.items() if cm >= min_cm)
        assert hit.distance_km == pytest.approx(best, abs=0.5)


def test_nearest_across_dateline():
    idx = make_index({(60, 179): 30, (60, 0): 30})
    hit = idx.nearest(60, -179, 10)
    assert hit.lon == 179
    assert hit.distance_km < 120


def test_nodata_cells_are_ignored():
    idx = make_index({(10, 10): 20}, nodata_elsewhere=True)
    assert idx.snow_cells == 1
    assert idx.nearest(0, 0, 1).lat == 10


def test_stale_flag():
    fresh = make_index({(0, 0): 5}, valid_time=datetime.now(timezone.utc) - timedelta(days=5))
    old = make_index({(0, 0): 5}, valid_time=datetime.now(timezone.utc) - timedelta(days=30))
    assert fresh.status()["stale"] is False
    assert old.status()["stale"] is True


def test_meters_to_cm_and_lon_normalization():
    cm = meters_to_cm(np.array([[0.0, 0.123, np.nan, -0.01, 1000.0]]))
    assert cm.tolist() == [[0, 12, int(NODATA), 0, 65534]]
    depth = np.array([[1, 2, 3, 4]], dtype=np.uint16)
    d, _, lon = normalize_lonlat(depth, np.array([0.0]), np.array([0.0, 90.0, 180.0, 270.0]))
    assert lon.tolist() == [-180.0, -90.0, 0.0, 90.0]
    assert d.tolist() == [[3, 4, 1, 2]]


def test_save_and_load_roundtrip(tmp_path):
    depth = np.zeros((len(LAT), len(LON)), dtype=np.uint16)
    depth[40, 190] = 42
    save_dataset(tmp_path, depth, LAT, LON, source="test", valid_time=datetime(2026, 1, 1, tzinfo=timezone.utc))
    d, lat, lon, meta = load_dataset(tmp_path)
    assert d[40, 190] == 42 and meta["source"] == "test" and meta["resolution_deg"] == 1.0
    assert (tmp_path / "snow_overlay.png").exists()
