"""API-Tests mit dem Demo-Datensatz aus data/."""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

pytestmark = pytest.mark.skipif(
    not (config.DATA_DIR / config.META_FILE).exists(), reason="keine Daten – make_demo_data ausführen"
)

# Startpunkte in verschiedenen Ländern
STARTS = {
    "München": (48.137, 11.575),
    "Berlin": (52.52, 13.405),
    "New York": (40.71, -74.0),
    "Sydney": (-33.87, 151.21),
    "Nairobi": (-1.29, 36.82),
    "Singapur": (1.35, 103.82),
    "Buenos Aires": (-34.6, -58.38),
    "Reykjavík": (64.15, -21.94),
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_status(client):
    s = client.get("/api/status").json()
    assert "valid_time" in s and "stale" in s and "disclaimer" in s


@pytest.mark.parametrize("name", STARTS)
@pytest.mark.parametrize("min_cm", [5, 20, 50])
def test_nearest_from_many_countries(client, name, min_cm):
    lat, lon = STARTS[name]
    r = client.get("/api/nearest", params={"lat": lat, "lon": lon, "min_cm": min_cm})
    assert r.status_code == 200
    body = r.json()
    assert body["found"]
    assert body["snow"]["depth_cm"] >= min_cm
    assert body["car"]["google_maps_url"].startswith("https://www.google.com/maps/dir/?api=1")


def test_higher_threshold_is_never_closer(client):
    lat, lon = STARTS["Berlin"]
    dists = [
        client.get("/api/nearest", params={"lat": lat, "lon": lon, "min_cm": m}).json()["distance_km"]
        for m in (5, 10, 20, 50)
    ]
    assert dists == sorted(dists)


def test_impossible_threshold(client):
    r = client.get("/api/nearest", params={"lat": 0, "lon": 0, "min_cm": 5000}).json()
    assert r["found"] is False


def test_invalid_coordinates(client):
    assert client.get("/api/nearest", params={"lat": 100, "lon": 0}).status_code == 422
