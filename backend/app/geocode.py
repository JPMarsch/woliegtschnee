"""Adresssuche über Nominatim (OpenStreetMap) mit Cache und 1 Anfrage/Sekunde,
wie es die Nominatim-Nutzungsrichtlinie verlangt."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict

import httpx

from . import config

_CACHE_SIZE = 2000
_cache: OrderedDict[str, list] = OrderedDict()
_lock = asyncio.Lock()
_last_request = 0.0


async def geocode(query: str, lang: str = "de") -> list[dict]:
    key = f"{lang}|{query.strip().lower()}"
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    global _last_request
    async with _lock:
        wait = 1.0 - (time.monotonic() - _last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": config.NOMINATIM_USER_AGENT}) as client:
            resp = await client.get(
                f"{config.NOMINATIM_URL}/search",
                params={"q": query, "format": "jsonv2", "limit": 5, "accept-language": lang},
            )
        _last_request = time.monotonic()
    resp.raise_for_status()

    results = [
        {"name": r.get("display_name", ""), "lat": float(r["lat"]), "lon": float(r["lon"])}
        for r in resp.json()
    ]
    _cache[key] = results
    if len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return results
