"""Suche nach dem nächstgelegenen Schneegebiet im Raster."""

from __future__ import annotations

import io
import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import config
from .geo import haversine_km
from .days import list_days
from .grid import NODATA, load_dataset, load_day, render_overlay

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
        # Jede Quelle kann ihre eigene Grenze mitbringen (GFS: 2 Tage, ERA5-Land: 10).
        stale_after = self.meta.get("stale_after_days", config.STALE_AFTER_DAYS)
        kind = self.meta.get("kind", "today")
        return {
            **self.meta,
            "kind": kind,
            "age_days": round(age_days, 1),
            # Nur der aktuelle Stand kann veralten; vergangene Tage sind gewollt alt.
            "stale": kind == "today" and age_days > stale_after,
            "stale_after_days": stale_after,
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


class DayStore:
    """Alle verfügbaren Tage. „Heute“ kommt aus den klassischen Dateien
    (SnowStore), jeder andere Tag wird erst bei Bedarf geladen – lokal oder,
    falls dort nicht (aktuell) vorhanden, von DATA_URL – und im Speicher
    zwischengehalten (die letzten `max_loaded` Tage)."""

    def __init__(self, data_dir: Path, data_url: str = "", max_loaded: int = 6):
        self.data_dir = data_dir
        self.data_url = data_url
        self.max_loaded = max_loaded
        self.today = SnowStore(data_dir)
        self._indexes: OrderedDict[str, tuple[str, SnowIndex]] = OrderedDict()
        self._overlays: OrderedDict[str, tuple[str, bytes]] = OrderedDict()
        self._lock = threading.Lock()

    def days(self) -> list[dict]:
        return list_days(self.data_dir)

    def find(self, day: str | None) -> dict | None:
        """Eintrag für ein Datum (YYYY-MM-DD); ohne Datum der aktuelle Tag."""
        days = self.days()
        if day is None:
            return next((e for e in days if e["kind"] == "today"), {"file": "", "kind": "today"})
        return next((e for e in days if e["date"] == day), None)

    def index(self, entry: dict) -> SnowIndex | None:
        if not entry["file"]:
            return self.today.get()
        with self._lock:
            cached = self._indexes.get(entry["file"])
            if cached and cached[0] == entry["created_at"]:
                self._indexes.move_to_end(entry["file"])
                return cached[1]
            index = SnowIndex(*self._load(entry))
            self._remember(self._indexes, entry, index)
            return index

    def overlay_png(self, entry: dict) -> bytes:
        with self._lock:
            cached = self._overlays.get(entry["file"])
            if cached and cached[0] == entry["created_at"]:
                self._overlays.move_to_end(entry["file"])
                return cached[1]
            depth_cm, lat, lon, _ = self._load(entry)
            buf = io.BytesIO()
            render_overlay(depth_cm, lat, lon).save(buf, format="PNG", optimize=True)
            self._remember(self._overlays, entry, buf.getvalue())
            return buf.getvalue()

    def _remember(self, cache: OrderedDict, entry: dict, value) -> None:
        cache[entry["file"]] = (entry["created_at"], value)
        cache.move_to_end(entry["file"])
        while len(cache) > self.max_loaded:
            cache.popitem(last=False)

    def _load(self, entry: dict):
        path = self.data_dir / entry["file"]
        if path.exists():
            data = load_day(path)
            if data[3].get("created_at") == entry["created_at"] or not self.data_url:
                return data
        if not self.data_url:
            raise FileNotFoundError(entry["file"])
        self._download(entry["file"], path)
        return load_day(path)

    def _download(self, name: str, path: Path) -> None:
        import httpx

        log.info("Lade Tag %s von DATA_URL …", name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".download")
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            with client.stream("GET", f"{self.data_url}/{name}") as resp, open(tmp, "wb") as f:
                resp.raise_for_status()
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        os.replace(tmp, path)
