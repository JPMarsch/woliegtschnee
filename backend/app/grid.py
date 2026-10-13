"""Speicherformat für das Schneeraster.

Das Raster liegt als komprimierte NumPy-Datei vor:
  depth_cm  uint16[nlat, nlon]  Schneehöhe in cm, NODATA = keine Daten (z. B. Meer)
  lat       float32[nlat]       Breitengrad der Zellmitten
  lon       float32[nlon]       Längengrad der Zellmitten (-180..180, aufsteigend)

Dazu eine JSON-Datei mit Metadaten (Quelle, Datenstand, Auflösung) und ein
PNG-Overlay in Web-Mercator für die Karte.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from . import config

NODATA = np.uint16(65535)
MAX_CM = 65534
MERCATOR_MAX_LAT = 85.0511287798

# Farbstufen (Untergrenze in cm, RGBA) für das Karten-Overlay.
OVERLAY_CLASSES = [
    (1, (186, 230, 253, 110)),
    (5, (125, 211, 252, 140)),
    (10, (56, 189, 248, 160)),
    (20, (14, 165, 233, 175)),
    (50, (3, 105, 161, 190)),
    (100, (30, 58, 138, 205)),
]


def meters_to_cm(depth_m: np.ndarray) -> np.ndarray:
    """Schneehöhe in Metern (NaN = keine Daten) → uint16 in cm mit NODATA."""
    depth_m = np.asarray(depth_m, dtype=np.float64)
    out = np.full(depth_m.shape, NODATA, dtype=np.uint16)
    valid = np.isfinite(depth_m)
    cm = np.clip(np.rint(np.maximum(depth_m[valid], 0.0) * 100.0), 0, MAX_CM)
    out[valid] = cm.astype(np.uint16)
    return out


def normalize_lonlat(depth_cm: np.ndarray, lat: np.ndarray, lon: np.ndarray):
    """Längengrade auf -180..<180 bringen und Achsen sortieren."""
    lon = np.where(lon >= 180.0, lon - 360.0, lon)
    order = np.argsort(lon, kind="stable")
    return depth_cm[:, order], np.asarray(lat, np.float32), np.asarray(lon[order], np.float32)


def save_dataset(
    out_dir: Path,
    depth_cm: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    *,
    source: str,
    valid_time: datetime,
    demo: bool = False,
    note: str = "",
) -> dict:
    """Raster, Overlay und Metadaten atomar schreiben. Die Metadatei kommt
    zuletzt, damit der Server erst neu lädt, wenn alles vollständig ist."""
    out_dir.mkdir(parents=True, exist_ok=True)
    depth_cm, lat, lon = normalize_lonlat(depth_cm, lat, lon)

    tmp_grid = out_dir / (config.GRID_FILE + ".tmp.npz")
    np.savez_compressed(tmp_grid, depth_cm=depth_cm, lat=lat, lon=lon)
    os.replace(tmp_grid, out_dir / config.GRID_FILE)

    tmp_png = out_dir / (config.OVERLAY_FILE + ".tmp")
    render_overlay(depth_cm, lat, lon).save(tmp_png, format="PNG", optimize=True)
    os.replace(tmp_png, out_dir / config.OVERLAY_FILE)

    resolution = float(abs(lon[1] - lon[0])) if len(lon) > 1 else 0.0
    meta = {
        "source": source,
        "demo": demo,
        "valid_time": valid_time.astimezone(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "resolution_deg": round(resolution, 4),
        "shape": list(depth_cm.shape),
        "note": note,
    }
    tmp_meta = out_dir / (config.META_FILE + ".tmp")
    tmp_meta.write_text(json.dumps(meta, indent=2))
    os.replace(tmp_meta, out_dir / config.META_FILE)
    return meta


def load_dataset(data_dir: Path):
    with np.load(data_dir / config.GRID_FILE) as f:
        depth_cm, lat, lon = f["depth_cm"], f["lat"], f["lon"]
    meta = json.loads((data_dir / config.META_FILE).read_text())
    return depth_cm, lat, lon, meta


def _nearest_index(axis: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Index der nächsten Achsenposition (Achse auf- oder absteigend)."""
    if axis[0] > axis[-1]:
        idx = len(axis) - 1 - _nearest_index(axis[::-1], values)
        return idx
    idx = np.clip(np.searchsorted(axis, values), 1, len(axis) - 1)
    left = axis[idx - 1]
    right = axis[idx]
    return np.where(np.abs(values - left) <= np.abs(values - right), idx - 1, idx)


def render_overlay(depth_cm: np.ndarray, lat: np.ndarray, lon: np.ndarray, size: int = 2048) -> Image.Image:
    """Schneehöhe als halbtransparentes PNG in Web-Mercator (für Leaflet)."""
    y = (np.arange(size) + 0.5) / size
    merc = math.pi * (1.0 - 2.0 * y)
    row_lat = np.degrees(np.arctan(np.sinh(merc)))
    col_lon = -180.0 + (np.arange(size) + 0.5) * 360.0 / size

    ri = _nearest_index(lat.astype(np.float64), row_lat)
    ci = _nearest_index(lon.astype(np.float64), col_lon)
    sampled = depth_cm[np.ix_(ri, ci)]

    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    for threshold, color in OVERLAY_CLASSES:
        mask = (sampled >= threshold) & (sampled != NODATA)
        rgba[mask] = color
    return Image.fromarray(rgba, mode="RGBA")
