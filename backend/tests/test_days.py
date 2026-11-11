"""Tagesindex: Zusammenführen über mehrere Importe und Laden einzelner Tage."""

from datetime import date, datetime, timezone

import numpy as np

from app import days
from app.grid import save_day
from app.snowdata import DayStore


def _e(d, kind, created="c1"):
    return {"date": d, "kind": kind, "valid_time": f"{d}T12:00:00+00:00", "created_at": created,
            "file": "" if kind == "today" else days.day_file(date.fromisoformat(d))}


def test_merge_keeps_history_and_replaces_forecasts():
    previous = {"days": [_e("2026-01-01", "past"), _e("2026-01-09", "past"),
                         _e("2026-01-10", "today"), _e("2026-01-11", "forecast"), _e("2026-01-12", "forecast")]}
    new = [_e("2026-01-11", "today", "c2"), _e("2026-01-10", "past", "c2"),
           _e("2026-01-12", "forecast", "c2"), _e("2026-01-13", "forecast", "c2")]
    merged = days.merge(previous, new)
    assert [(e["date"], e["kind"]) for e in merged] == [
        ("2026-01-01", "past"), ("2026-01-09", "past"), ("2026-01-10", "past"),
        ("2026-01-11", "today"), ("2026-01-12", "forecast"), ("2026-01-13", "forecast"),
    ]
    assert all(e["created_at"] == "c2" for e in merged if e["kind"] != "past" or e["date"] == "2026-01-10")


def _write_day(path, depth_at_alps):
    lat = np.arange(90, -90.01, -1.0)
    lon = np.arange(-180, 180, 1.0)
    depth = np.zeros((len(lat), len(lon)), dtype=np.uint16)
    depth[np.argmin(abs(lat - 47)), np.argmin(abs(lon - 11))] = depth_at_alps
    return save_day(path, depth, lat, lon, source="Test", valid_time=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
                    extra={"kind": "past"})


def test_daystore_loads_lazily_and_refreshes(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    local = tmp_path / "local"
    local.mkdir()
    meta = _write_day(remote / "day-2026-01-01.npz", 40)
    entry = {**days.entry(meta, "past", "day-2026-01-01.npz")}
    days.write_index(local, [entry])

    store = DayStore(local, data_url="https://example.invalid")
    downloads = []

    def fake_download(name, path):
        downloads.append(name)
        path.write_bytes((remote / name).read_bytes())

    monkeypatch.setattr(store, "_download", fake_download)
    found = store.find("2026-01-01")
    hit = store.index(found).nearest(48, 11, 10)
    assert hit.depth_cm == 40 and downloads == ["day-2026-01-01.npz"]
    store.index(found)  # aus dem Speicher
    assert len(downloads) == 1
    assert store.overlay_png(found).startswith(b"\x89PNG")

    # Neu erzeugter Tag im Release → wird erneut geladen
    meta2 = _write_day(remote / "day-2026-01-01.npz", 80)
    days.write_index(local, [days.entry(meta2, "past", "day-2026-01-01.npz")])
    assert store.index(store.find("2026-01-01")).nearest(48, 11, 10).depth_cm == 80
    assert len(downloads) == 2
    assert store.find("2025-12-31") is None


def test_remove_unlisted(tmp_path):
    for d in ("2026-01-01", "2026-01-02"):
        (tmp_path / f"day-{d}.npz").write_bytes(b"x")
    days.remove_unlisted(tmp_path, [{"file": "day-2026-01-02.npz"}])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["day-2026-01-02.npz"]
