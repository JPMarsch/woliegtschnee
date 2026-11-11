"""Import der GFS-Schneehöhe: heute, Prognose und fehlende vergangene Tage.

    python -m scripts.ingest_gfs                          # Standardlauf
    python -m scripts.ingest_gfs --backfill 2025-11-01    # ältere Tage nachladen (AWS-Archiv)
    python -m scripts.ingest_gfs --file x.grib2 --cycle 2026-11-10T00   # vorhandene Datei als „heute“

Der bisherige Tagesindex (days.json) kommt aus --out oder, wenn DATA_URL gesetzt
ist, aus dem Release – so werden schon vorhandene Tage nicht erneut geladen.
"""

import argparse
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from app import config
from app.days import fetch_remote_index, read_index
from app.gfs import ingest_latest, process_file


def _cycle(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=config.DATA_DIR)
    parser.add_argument("--file", type=Path, help="vorhandene GRIB2-Datei als „heute“ verarbeiten")
    parser.add_argument("--cycle", type=_cycle, help="Modelllauf der --file (YYYY-MM-DDTHH, UTC)")
    parser.add_argument("--past-days", type=int, default=10, help="fehlende Tage in diesem Zeitraum laden")
    parser.add_argument("--forecast-days", type=int, default=7)
    parser.add_argument("--backfill", type=date.fromisoformat, help="zusätzlich alle Tage ab diesem Datum laden")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.file:
        if not args.cycle:
            parser.error("--file braucht --cycle")
        meta = process_file(args.file, args.cycle, args.out)
        print(f"OK – Datenstand {meta['valid_time']}, Raster {meta['shape']}")
        return

    previous = fetch_remote_index(config.DATA_URL) if config.DATA_URL else read_index(args.out)
    index = ingest_latest(
        args.out,
        previous=previous,
        past_days=args.past_days,
        forecast_days=args.forecast_days,
        backfill_from=args.backfill,
    )
    kinds = {k: sum(e["kind"] == k for e in index["days"]) for k in ("past", "today", "forecast")}
    print(f"OK – {kinds['past']} vergangene Tage, heute, {kinds['forecast']} Prognosetage")


if __name__ == "__main__":
    main()
