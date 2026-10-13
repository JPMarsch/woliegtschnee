"""HTTP-API für den Schnee-Finder. Liefert im Produktivbetrieb auch das
gebaute Frontend aus, sodass ein einzelner Dienst genügt."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .geocode import geocode
from .snowdata import SnowStore
from .sync import start_background_jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

store = SnowStore(config.DATA_DIR)

DISCLAIMER = (
    "Die Schneehöhen stammen aus dem Reanalyse-Modell ERA5-Land und sind modellierte "
    "Mittelwerte für Rasterzellen von ca. 9 × 9 km – keine exakten Messungen an einem "
    "bestimmten Ort. Vor Ort kann die Schneelage deutlich abweichen."
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_background_jobs()
    store.get()
    yield


app = FastAPI(title="Wo liegt Schnee?", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET"], allow_headers=["*"])


def _require_index():
    index = store.get()
    if index is None:
        raise HTTPException(503, "Noch keine Schneedaten vorhanden. Bitte Import ausführen.")
    return index


@app.get("/api/status")
def status():
    index = _require_index()
    return {**index.status(), "disclaimer": DISCLAIMER}


@app.get("/api/nearest")
def nearest(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    min_cm: int = Query(10, ge=1, le=5000),
):
    index = _require_index()
    hit = index.nearest(lat, lon, min_cm)
    data_status = index.status()
    if hit is None:
        return {
            "found": False,
            "min_cm": min_cm,
            "max_depth_cm": index.max_depth_cm,
            "data": data_status,
            "disclaimer": DISCLAIMER,
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
        "disclaimer": DISCLAIMER,
    }


@app.get("/api/geocode")
async def api_geocode(q: str = Query(..., min_length=2, max_length=200), lang: str = "de"):
    try:
        return {"results": await geocode(q, lang)}
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Adresssuche nicht erreichbar: {exc}") from exc


@app.get("/api/overlay.png")
def overlay():
    path = config.DATA_DIR / config.OVERLAY_FILE
    if not path.exists():
        raise HTTPException(404, "Kein Overlay vorhanden")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


if config.FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIST, html=True), name="frontend")
