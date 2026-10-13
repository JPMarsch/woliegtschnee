"""Erzeugt einen synthetischen DEMO-Datensatz, damit die App ohne CDS-Zugang
lauffähig ist. Die Werte sind frei erfunden und werden in der Oberfläche
deutlich als Demo gekennzeichnet.

    python -m scripts.make_demo_data
"""

from datetime import datetime, timedelta, timezone

import numpy as np

from app import config
from app.grid import NODATA, save_dataset

STEP = 0.1

# (Breite, Länge, Radius in Grad, maximale Schneehöhe in cm)
SNOW_REGIONS = [
    (46.5, 10.0, 2.2, 180),   # Alpen
    (42.7, 0.8, 0.9, 80),     # Pyrenäen
    (47.5, 25.0, 1.6, 60),    # Karpaten
    (63.0, 13.0, 4.5, 120),   # Skandinavisches Gebirge
    (66.0, 26.0, 3.5, 70),    # Finnisch-Lappland
    (62.0, 60.0, 6.0, 80),    # Ural / Nordrussland
    (64.0, 100.0, 14.0, 90),  # Sibirien
    (43.0, 43.5, 1.5, 120),   # Kaukasus
    (39.5, 42.0, 1.5, 60),    # Ostanatolien
    (31.0, -7.5, 0.6, 30),    # Hoher Atlas
    (31.0, 80.0, 5.0, 200),   # Himalaya / Tibet
    (42.0, 80.0, 3.0, 90),    # Tian Shan
    (36.3, 137.6, 1.0, 250),  # Japanische Alpen
    (43.5, 142.8, 1.0, 180),  # Hokkaido
    (62.0, -110.0, 13.0, 70), # Kanada
    (64.0, -150.0, 6.0, 90),  # Alaska
    (50.5, -117.0, 4.0, 160), # Kanadische Rocky Mountains / Selkirks
    (40.0, -106.5, 3.0, 110), # Colorado
    (46.0, -121.5, 2.0, 150), # Kaskadenkette
    (39.0, -120.2, 1.2, 140), # Sierra Nevada
    (47.0, -71.0, 3.0, 70),   # Québec
    (72.0, -40.0, 9.0, 300),  # Grönland
    (-33.0, -70.0, 1.2, 120), # Zentrale Anden
    (-41.0, -71.5, 1.8, 100), # Patagonische Anden
    (-43.5, 170.5, 1.0, 150), # Neuseeländische Alpen
    (-36.4, 148.3, 0.5, 60),  # Snowy Mountains
    (-3.07, 37.35, 0.1, 40),  # Kilimandscharo
]


def main():
    lat = np.arange(90.0, -90.0 - STEP / 2, -STEP)
    lon = np.arange(-180.0, 180.0, STEP)
    lon2, lat2 = np.meshgrid(lon, lat)

    rng = np.random.default_rng(42)
    # grobes, geglättetes Rauschen für natürlicher wirkende Ränder
    noise = rng.random((len(lat) // 20 + 1, len(lon) // 20 + 1))
    noise = np.kron(noise, np.ones((20, 20)))[: len(lat), : len(lon)]

    depth = np.zeros_like(lat2)
    for clat, clon, radius, max_cm in SNOW_REGIONS:
        dlon = (lon2 - clon + 180) % 360 - 180
        r = np.hypot(lat2 - clat, dlon * np.cos(np.radians(clat))) / radius
        depth = np.maximum(depth, max_cm * np.clip(1.0 - r**2, 0, None) * (0.6 + 0.6 * noise))
    # Antarktis
    depth = np.where(lat2 < -70, np.maximum(depth, 250 + 100 * noise), depth)

    depth_cm = np.rint(depth).astype(np.uint16)
    # Außerhalb der Schneeregionen meist „Land ohne Schnee“, Rest „keine Daten“
    depth_cm[(depth_cm == 0) & (noise < 0.35)] = NODATA

    valid_time = (datetime.now(timezone.utc) - timedelta(days=5)).replace(hour=0, minute=0, second=0, microsecond=0)
    meta = save_dataset(
        config.DATA_DIR,
        depth_cm,
        lat,
        lon,
        source="DEMO (synthetische Werte)",
        valid_time=valid_time,
        demo=True,
        note="Erfundene Testdaten – für echte Werte scripts/ingest_era5.py ausführen.",
    )
    print(f"Demo-Daten geschrieben: {meta}")


if __name__ == "__main__":
    main()
