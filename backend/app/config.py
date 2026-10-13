"""Zentrale Konfiguration, überschreibbar per Umgebungsvariablen."""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SNOW_DATA_DIR", BACKEND_DIR / "data"))
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", BACKEND_DIR.parent / "frontend" / "dist"))

GRID_FILE = "snow_grid.npz"
META_FILE = "snow_meta.json"
OVERLAY_FILE = "snow_overlay.png"

# Ab wie vielen Tagen Alter der Datenstand als veraltet gilt.
# ERA5-Land hat regulär ~5 Tage Verzögerung, daher großzügig.
STALE_AFTER_DAYS = int(os.environ.get("STALE_AFTER_DAYS", "10"))

# Optional: Basis-URL, von der fertig verarbeitete Daten geladen werden
# (z. B. ein GitHub-Release, das die tägliche GitHub Action befüllt).
DATA_URL = os.environ.get("DATA_URL", "").rstrip("/")
DATA_SYNC_HOURS = float(os.environ.get("DATA_SYNC_HOURS", "6"))

# Optional: täglicher ERA5-Import direkt im Server-Prozess (braucht CDS-Zugang).
INGEST_ON_SERVER = os.environ.get("INGEST_ON_SERVER", "0") == "1"

# Nominatim verlangt einen aussagekräftigen User-Agent mit Kontakt.
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org")
NOMINATIM_USER_AGENT = os.environ.get(
    "NOMINATIM_USER_AGENT", "woliegtschnee/0.1 (https://github.com/JPMarsch/woliegtschnee)"
)

CORS_ORIGINS = [o for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",") if o]
