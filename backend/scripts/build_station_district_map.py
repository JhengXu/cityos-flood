#!/usr/bin/env python3
"""Build the auditable station-to-district mapping from project-local GIS."""
from __future__ import annotations

import csv
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import observations  # noqa: E402


def main():
    mapping = observations.build_station_district_map()
    target = observations.MAPPING
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "czbm",
                "district_id",
                "method",
                "reference_distance_km",
                "coordinate_check",
                "lat",
                "lon",
            ],
        )
        writer.writeheader()
        for code, row in sorted(mapping.items()):
            writer.writerow({"czbm": code, **row})
    print(f"wrote {len(mapping)} station mappings to {target}")


if __name__ == "__main__":
    main()
