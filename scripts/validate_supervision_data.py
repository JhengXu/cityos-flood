#!/usr/bin/env python3
"""Validate event-level supervision data before it enters training."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path


REQUIRED = {
    "waterlogging.csv": {
        "label_id", "timestamp", "longitude", "latitude", "depth_cm",
        "flooded", "source_id", "quality_flag", "label_type",
    },
    "rainfall_hourly.csv": {
        "station_id", "timestamp", "longitude", "latitude",
        "rainfall_mm", "source_id", "quality_flag",
    },
}
OPTIONAL = {
    "waterlevel.csv": {
        "station_code", "timestamp", "longitude", "latitude", "level_m",
        "datum", "source_id", "quality_flag",
    },
    "disaster.csv": {
        "record_id", "timestamp", "longitude", "latitude", "kind",
        "severity", "source_id", "quality_flag",
    },
}
SHENZHEN_BOUNDS = {"lat": (22.35, 22.90), "lon": (113.70, 114.70)}


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return dt


def number(row: dict[str, str], key: str, minimum: float | None = None) -> float:
    value = float(row[key])
    if minimum is not None and value < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    return value


def validate_csv(path: Path, required: set[str]) -> tuple[int, list[str]]:
    errors: list[str] = []
    seen: set[tuple[str, ...]] = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        missing = sorted(required - fields)
        if missing:
            return 0, [f"missing columns: {', '.join(missing)}"]
        count = 0
        for line, row in enumerate(reader, start=2):
            count += 1
            try:
                parse_time(row["timestamp"])
                lat = number(row, "latitude")
                lon = number(row, "longitude")
                if not SHENZHEN_BOUNDS["lat"][0] <= lat <= SHENZHEN_BOUNDS["lat"][1]:
                    raise ValueError("latitude outside Shenzhen bounds")
                if not SHENZHEN_BOUNDS["lon"][0] <= lon <= SHENZHEN_BOUNDS["lon"][1]:
                    raise ValueError("longitude outside Shenzhen bounds")
                if not row.get("source_id") or not row.get("quality_flag"):
                    raise ValueError("source_id and quality_flag are required")
                if path.name == "waterlogging.csv":
                    number(row, "depth_cm", 0)
                    if row["flooded"] not in {"0", "1"}:
                        raise ValueError("flooded must be 0 or 1")
                    if row["label_type"] not in {"observed", "derived", "proxy"}:
                        raise ValueError("label_type must be observed, derived, or proxy")
                    key = (row["label_id"], row["timestamp"])
                elif path.name == "rainfall_hourly.csv":
                    number(row, "rainfall_mm", 0)
                    key = (row["station_id"], row["timestamp"])
                elif path.name == "waterlevel.csv":
                    number(row, "level_m")
                    if not row.get("datum"):
                        raise ValueError("datum is required for water level")
                    key = (row["station_code"], row["timestamp"])
                else:
                    severity = number(row, "severity", 0)
                    if severity > 4:
                        raise ValueError("severity must be in 0..4")
                    key = (row["record_id"], row["timestamp"])
                if key in seen:
                    raise ValueError(f"duplicate key {key}")
                seen.add(key)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"line {line}: {exc}")
    if count == 0:
        errors.append("file has no data rows")
    return count, errors


def validate_event(event_dir: Path) -> dict:
    result = {"event": event_dir.name, "ok": True, "files": {}, "errors": []}
    meta_path = event_dir / "meta.json"
    if not meta_path.exists():
        result["errors"].append("missing meta.json")
    else:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for key in ("event_id", "start_time", "end_time", "dataset_version", "label_type", "sources"):
                if not meta.get(key):
                    result["errors"].append(f"meta.json missing {key}")
            parse_time(meta["start_time"])
            parse_time(meta["end_time"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            result["errors"].append(f"invalid meta.json: {exc}")

    for filename, columns in {**REQUIRED, **OPTIONAL}.items():
        path = event_dir / filename
        if not path.exists():
            if filename in REQUIRED:
                result["errors"].append(f"missing {filename}")
            continue
        rows, errors = validate_csv(path, columns)
        result["files"][filename] = {"rows": rows, "errors": errors}
        result["errors"].extend(f"{filename}: {error}" for error in errors)
    result["ok"] = not result["errors"]
    return result


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/processed/events")
    if not root.is_dir():
        print(json.dumps({"ok": False, "error": f"event directory not found: {root}"}, ensure_ascii=False))
        return 2
    events = [validate_event(path) for path in sorted(root.iterdir()) if path.is_dir()]
    report = {"ok": bool(events) and all(event["ok"] for event in events), "event_count": len(events), "events": events}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
