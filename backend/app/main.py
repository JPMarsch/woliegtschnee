"""HTTP-API für den Schnee-Finder. Liefert im Produktivbetrieb auch das
gebaute Frontend aus, sodass ein einzelner Dienst genügt."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config
from .geocode import geocode
from .snowdata import DayStore
from .sync import start_background_jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

store = DayStore(config.DATA_DIR, config.DATA_URL)
DAY = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="Tag (YYYY-MM-DD), Standard: aktuell")

DISCLAIMER = (
    "Die Schneehöhen stammen aus dem Reanalyse-Modell ERA5-Land und sind modellierte "
    "Mittelwerte für Rasterzellen von ca. 9 × 9 km – keine exakten Messungen an einem "
    "bestimmten Ort. Vor Ort kann die Schneelage deutlich abweichen."
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_background_jobs()
    store.today.get()
    if config.DATA_URL:
        # Prognose + jüngste Tage regelmäßig vorab laden (neuer Index → neue Dateien)
        threading.Thread(target=_prefetch_loop, daemon=True, name="Vorabladen").start()
    yield


def _prefetch_loop():
    while True:
        try:
            store.prefetch()
        except Exception:
            logging.getLogger(__name__).exception("Vorabladen fehlgeschlagen")
        time.sleep(600)


app = FastAPI(title="Wo liegt Schnee?", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET"], allow_headers=["*"])


def _disclaimer(index) -> str:
    # Neuere Datensätze bringen ihren Hinweis selbst mit (z. B. GFS).
    return index.meta.get("disclaimer") or DISCLAIMER


def _entry(day: str | None) -> dict:
    entry = store.find(day)
    if entry is None:
        raise HTTPException(404, f"Für den {day} gibt es keine Schneedaten.")
    return entry


def _require_index(day: str | None = None):
    entry = _entry(day)
    try:
        index = store.index(entry)
    except Exception as exc:
        logging.getLogger(__name__).exception("Tag %s konnte nicht geladen werden", day)
        raise HTTPException(503, f"Schneedaten für den {day} sind gerade nicht abrufbar.") from exc
    if index is None:
        raise HTTPException(503, "Noch keine Schneedaten vorhanden. Bitte Import ausführen.")
    return index


@app.get("/api/days")
def days():
    """Alle verfügbaren Tage: vergangen, heute, Prognose."""
    fields = ("date", "kind", "valid_time", "run", "source", "created_at")
    return {"days": [{k: e.get(k) for k in fields} for e in store.days()]}


@app.get("/api/status")
def status(day: str | None = DAY):
    index = _require_index(day)
    return {**index.status(), "disclaimer": _disclaimer(index)}


@app.get("/api/nearest")
def nearest(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    min_cm: int = Query(10, ge=1, le=5000),
    day: str | None = DAY,
):
    index = _require_index(day)
    hit = index.nearest(lat, lon, min_cm)
    data_status = index.status()
    if hit is None:
        return {
            "found": False,
            "min_cm": min_cm,
            "max_depth_cm": index.max_depth_cm,
            "data": data_status,
            "disclaimer": _disclaimer(index),
        }

    directions = "https://www.google.com/maps/dir/?" + urlencode({
        "api": 1,
        "origin": f"{lat},{lon}",
        "destination": f"{hit.lat},{hit.lon}",
        "travelmode": "driving",
    })
    return {
        "found": True,
        "min_cm": min_cm,
        "start": {"lat": lat, "lon": lon},
        "snow": {
            "lat": hit.lat,
            "lon": hit.lon,
            "depth_cm": hit.depth_cm,
            "cell_bounds": hit.cell_bounds,
            "resolution_deg": round(index.lat_step, 4),
        },
        "distance_km": round(hit.distance_km, 1),
        # Liegt der Startpunkt selbst in der gefundenen Zelle, ist man schon im Schnee.
        "at_start": hit.distance_km <= index.lat_step * 111.32 * 0.75,
        "car": {"google_maps_url": directions},
        "data": data_status,
        "disclaimer": _disclaimer(index),
    }


@app.get("/api/geocode")
async def api_geocode(q: str = Query(..., min_length=2, max_length=200), lang: str = "de"):
    try:
        return {"results": await geocode(q, lang)}
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Adresssuche nicht erreichbar: {exc}") from exc


@app.get("/api/overlay.png")
def overlay(day: str | None = DAY):
    entry = _entry(day)
    if entry["file"]:
        try:
            png = store.overlay_png(entry)
        except Exception as exc:
            raise HTTPException(503, "Overlay für diesen Tag nicht abrufbar") from exc
        return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
    path = config.DATA_DIR / config.OVERLAY_FILE
    if not path.exists():
        raise HTTPException(404, "Kein Overlay vorhanden")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
