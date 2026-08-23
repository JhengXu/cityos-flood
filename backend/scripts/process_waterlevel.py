#!/usr/bin/env python3
"""Convert Shenzhen point-water-level exports to deduplicated Beijing hourly data."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

BJT = timezone(timedelta(hours=8))


def parse_local(value):
    # Source is Shenzhen municipal local time but has no offset in the export.
    dt = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=BJT)


def process(source, output, report):
    groups = defaultdict(list)
    input_rows = 0
    with Path(source).open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            input_rows += 1
            try:
                ts = parse_local(row["time"])
                level = float(row["level_m"])
            except (KeyError, ValueError):
                continue
            groups[(row["station_code"].strip(), ts)].append((level, row))

    deduped = []
    duplicate_rows = 0
    conflict_groups = 0
    for (station, ts), values in groups.items():
        duplicate_rows += max(0, len(values) - 1)
        levels = [v[0] for v in values]
        conflict = max(levels) - min(levels) > 1e-6
        conflict_groups += int(conflict)
        level = sum(levels) / len(levels)
        row = values[-1][1]
        valid = 0 <= level <= 3.0
        deduped.append({
            "station_code": station, "station_name": row.get("station_name", ""),
            "timestamp": ts, "level_m": level if valid else None,
            "lat": row.get("lat", ""), "lon": row.get("lon", ""),
            "quality_flag": "invalid_range" if not valid else "duplicate_conflict" if conflict else "good",
        })

    hourly = defaultdict(list)
    for row in deduped:
        key = (row["station_code"], row["timestamp"].replace(minute=0, second=0, microsecond=0))
        hourly[key].append(row)
    output_rows = []
    for (station, hour), rows in sorted(hourly.items(), key=lambda x: (x[0][1], x[0][0])):
        valid = [r["level_m"] for r in rows if r["level_m"] is not None]
        flags = {r["quality_flag"] for r in rows}
        meta = rows[-1]
        output_rows.append({
            "timestamp_bjt": hour.isoformat(), "timezone": "Asia/Shanghai",
            "station_code": station, "station_name": meta["station_name"],
            "level_m_mean": round(sum(valid)/len(valid), 4) if valid else "",
            "level_m_max": round(max(valid), 4) if valid else "",
            "sample_count": len(valid), "raw_count": len(rows),
            "quality_flag": "invalid" if not valid else "review" if "duplicate_conflict" in flags else "good",
            "lat": meta["lat"], "lon": meta["lon"],
            "source": "深圳市水务局开放平台·积涝点水位",
        })
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    fields = list(output_rows[0]) if output_rows else []
    with Path(output).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader(); writer.writerows(output_rows)
    summary = {
        "input_rows": input_rows, "unique_station_timestamps": len(deduped),
        "duplicate_rows_removed": duplicate_rows, "duplicate_conflict_groups": conflict_groups,
        "hourly_rows": len(output_rows), "stations": len({r["station_code"] for r in output_rows}),
        "timezone": "Asia/Shanghai (+08:00)",
        "timezone_assumption": "source export is Shenzhen municipal local time; original field had no offset",
        "quality_rules": {"valid_range_m": [0, 3], "duplicate_conflict": "same station/time with differing values"},
    }
    Path(report).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    print(json.dumps(process(args.source, args.output, args.report), ensure_ascii=False, indent=2))
