"""Suche nach dem nächstgelegenen Schneegebiet im Raster."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import config
from .geo import haversine_km
from .grid import NODATA, load_dataset

log = logging.getLogger(__name__)


@dataclass
class SnowHit:
    lat: float
    lon: float
    depth_cm: int
    distance_km: float
    cell_bounds: list  # [[south, west], [north, east]]


class SnowIndex:
    """Alle Zellen mit Schnee, absteigend nach Schneehöhe sortiert.

    Für eine Mindesthöhe ist die Kandidatenmenge damit immer ein Präfix der
    Arrays; die Suche ist eine vektorisierte Haversine über dieses Präfix.
    """

    def __init__(self, depth_cm: np.ndarray, lat: np.ndarray, lon: np.ndarray, meta: dict):
        self.meta = meta
        self.shape = depth_cm.shape
        self.lat_step = float(abs(lat[1] - lat[0])) if len(lat) > 1 else 0.0
        self.lon_step = float(abs(lon[1] - lon[0])) if len(lon) > 1 else 0.0

        rows, cols = np.nonzero((depth_cm != NODATA) & (depth_cm >= 1))
        depth = depth_cm[rows, cols]
        order = np.argsort(-depth.astype(np.int32), kind="stable")
        self.depth = depth[order]
        self.lat = lat[rows[order]].astype(np.float32)
        self.lon = lon[cols[order]].astype(np.float32)
        # Vorberechnet in float32, um Speicher zu sparen (Genauigkeit reicht
        # für die Vorauswahl; der Treffer wird danach exakt nachgerechnet).
        self._lat_rad = np.radians(self.lat)
        self._lon_rad = np.radians(self.lon)
        self._cos_lat = np.cos(self._lat_rad)
        # depth absteigend → negiert aufsteigend, für searchsorted
        self._neg_depth = -self.depth.astype(np.int32)

        valid = depth_cm != NODATA
        self.valid_cells = int(valid.sum())
        self.snow_cells = int(len(self.depth))
        self.max_depth_cm = int(self.depth[0]) if len(self.depth) else 0

    def count_at_least(self, min_cm: int) -> int:
        return int(np.searchsorted(self._neg_depth, -int(min_cm), side="right"))

    def nearest(self, lat: float, lon: float, min_cm: int) -> SnowHit | None:
        n = self.count_at_least(max(1, int(min_cm)))
        if n == 0:
            return None
        la, lo = np.float32(np.radians(lat)), np.float32(np.radians(lon))
        a = (
            np.sin((self._lat_rad[:n] - la) / 2) ** 2
            + np.cos(la) * self._cos_lat[:n] * np.sin((self._lon_rad[:n] - lo) / 2) ** 2
        )
        i = int(np.argmin(a))
        hit_lat, hit_lon = float(self.lat[i]), float(self.lon[i])
        half_lat, half_lon = self.lat_step / 2, self.lon_step / 2
        return SnowHit(
            lat=round(hit_lat, 4),
            lon=round(hit_lon, 4),
            depth_cm=int(self.depth[i]),
            distance_km=float(haversine_km(lat, lon, hit_lat, hit_lon)),
            cell_bounds=[
                [round(hit_lat - half_lat, 4), round(hit_lon - half_lon, 4)],
                [round(hit_lat + half_lat, 4), round(hit_lon + half_lon, 4)],
            ],
        )

    def status(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        valid_time = datetime.fromisoformat(self.meta["valid_time"])
        age_days = (now - valid_time).total_seconds() / 86400
        return {
            **self.meta,
            "age_days": round(age_days, 1),
            "stale": age_days > config.STALE_AFTER_DAYS,
            "stale_after_days": config.STALE_AFTER_DAYS,
            "snow_cells": self.snow_cells,
            "valid_cells": self.valid_cells,
            "max_depth_cm": self.max_depth_cm,
        }


class SnowStore:
    """Hält den aktuellen Index und lädt neu, sobald sich die Metadatei ändert."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self._index: SnowIndex | None = None
        self._mtime: float | None = None
        self._lock = threading.Lock()

    def get(self) -> SnowIndex | None:
        meta_path = self.data_dir / config.META_FILE
        try:
            mtime = meta_path.stat().st_mtime
        except FileNotFoundError:
            return self._index
        if mtime != self._mtime:
            with self._lock:
                if mtime != self._mtime:
                    try:
                        self._index = SnowIndex(*load_dataset(self.data_dir))
                        log.info("Schneedaten geladen: %s", self._index.meta.get("valid_time"))
                    except Exception:
                        # Alten Index behalten statt bei jeder Anfrage erneut zu scheitern.
                        log.exception("Schneedaten konnten nicht geladen werden")
                    self._mtime = mtime
        return self._index
