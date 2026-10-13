"""Täglicher Import: jüngste ERA5-Land-Schneehöhe laden und aufbereiten.

    python -m scripts.ingest_era5                 # jüngster verfügbarer Tag
    python -m scripts.ingest_era5 --file x.nc --date 2026-01-15   # vorhandene Datei
"""

import argparse
import logging
from datetime import date
from pathlib import Path

from app import config
from app.era5 import ingest_latest, process_file


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=config.DATA_DIR)
    parser.add_argument("--file", type=Path, help="vorhandene NetCDF-Datei verarbeiten statt herunterladen")
    parser.add_argument("--date", type=date.fromisoformat, help="Datenstand der --file (YYYY-MM-DD)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.file:
        if not args.date:
            parser.error("--file braucht --date")
        meta = process_file(args.file, args.date, args.out)
    else:
        meta = ingest_latest(args.out)
    print(f"OK – Datenstand {meta['valid_time']}, Raster {meta['shape']}")


if __name__ == "__main__":
    main()
