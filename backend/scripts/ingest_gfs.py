"""Import der aktuellen GFS-Schneehöhe (jüngster verfügbarer Modelllauf).

    python -m scripts.ingest_gfs                                   # jüngster Lauf
    python -m scripts.ingest_gfs --file x.grib2 --cycle 2026-11-10T00   # vorhandene Datei
"""

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from app import config
from app.gfs import ingest_latest, process_file


def _cycle(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=config.DATA_DIR)
    parser.add_argument("--file", type=Path, help="vorhandene GRIB2-Datei verarbeiten statt herunterladen")
    parser.add_argument("--cycle", type=_cycle, help="Modelllauf der --file (YYYY-MM-DDTHH, UTC)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.file:
        if not args.cycle:
            parser.error("--file braucht --cycle")
        meta = process_file(args.file, args.cycle, args.out)
    else:
        meta = ingest_latest(args.out)
    print(f"OK – Datenstand {meta['valid_time']}, Raster {meta['shape']}")


if __name__ == "__main__":
    main()
