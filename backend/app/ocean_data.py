# -*- coding: utf-8 -*-
"""潮位观测数据合同、质量控制、小时聚合与调和分解。"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

BJT = timezone(timedelta(hours=8))
REQUIRED = {
    "timestamp", "station_id", "longitude", "latitude",
    "observed_level_m", "datum", "quality_flag", "source",
}
PERIODS_H = {"M2": 12.4206, "S2": 12.0, "K1": 23.9345, "O1": 25.8193}
BAD_FLAGS = {"bad", "invalid", "missing", "异常", "缺测"}


class TideDataError(ValueError):
    pass


def parse_timestamp(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise TideDataError("timestamp 必须显式包含时区；禁止猜测原始数据时区")
    return dt.astimezone(BJT)


def read_observations(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise TideDataError(f"缺少字段: {', '.join(sorted(missing))}")
        rows = []
        for raw in reader:
            flag = (raw["quality_flag"] or "unknown").strip().lower()
            value = raw["observed_level_m"].strip()
            level = float(value) if value else math.nan
            if not np.isfinite(level):
                flag = "missing"
            if np.isfinite(level) and not -5.0 <= level <= 8.0:
                flag = "invalid"
            rows.append({
                **raw,
                "timestamp": parse_timestamp(raw["timestamp"]),
                "longitude": float(raw["longitude"]),
                "latitude": float(raw["latitude"]),
                "observed_level_m": level,
                "quality_flag": flag,
            })
    return rows


def assert_comparable_datums(rows):
    datums = {r["datum"].strip() for r in rows if r.get("datum")}
    if len(datums) != 1:
        raise TideDataError(f"基准面未统一，禁止跨站比较或合并: {sorted(datums)}")
    if not datums:
        raise TideDataError("datum 不能为空")
    return next(iter(datums))


def aggregate_hourly(rows, min_valid=1):
    """分钟/秒数据按北京时间整点聚合；坏值不参与均值，空小时显式补 missing。"""
    grouped = defaultdict(list)
    metadata = {}
    for row in rows:
        key = (row["station_id"], row["timestamp"].replace(minute=0, second=0, microsecond=0))
        grouped[key].append(row)
        metadata[row["station_id"]] = row
    if not grouped:
        return []
    output = []
    for station in sorted(metadata):
        times = sorted(t for sid, t in grouped if sid == station)
        cursor, end = times[0], times[-1]
        meta = metadata[station]
        while cursor <= end:
            bucket = grouped.get((station, cursor), [])
            valid = [r["observed_level_m"] for r in bucket
                     if r["quality_flag"] not in BAD_FLAGS and np.isfinite(r["observed_level_m"])]
            ok = len(valid) >= min_valid
            output.append({
                "timestamp": cursor.isoformat(), "station_id": station,
                "longitude": meta["longitude"], "latitude": meta["latitude"],
                "observed_level_m": round(float(np.mean(valid)), 4) if ok else None,
                "datum": meta["datum"], "quality_flag": "good" if ok else "missing",
                "source": meta["source"], "sample_count": len(valid),
            })
            cursor += timedelta(hours=1)
    return output


def harmonic_reconstruct(rows):
    """用最小二乘拟合 M2/S2/K1/O1；数据不足时明确拒绝分解。"""
    valid = [r for r in rows if r.get("observed_level_m") is not None
             and r.get("quality_flag") not in BAD_FLAGS]
    if len(valid) < 48:
        raise TideDataError("调和分解至少需要48个有效小时；正式校准建议连续30天以上")
    assert_comparable_datums(valid)
    t0 = parse_timestamp(valid[0]["timestamp"]) if isinstance(valid[0]["timestamp"], str) else valid[0]["timestamp"]
    hours = np.array([((parse_timestamp(r["timestamp"]) if isinstance(r["timestamp"], str) else r["timestamp"]) - t0).total_seconds()/3600 for r in valid])
    y = np.array([r["observed_level_m"] for r in valid], dtype=float)
    columns = [np.ones(len(hours))]
    for period in PERIODS_H.values():
        w = 2*np.pi/period
        columns.extend([np.cos(w*hours), np.sin(w*hours)])
    coef, *_ = np.linalg.lstsq(np.column_stack(columns), y, rcond=None)
    predicted = np.column_stack(columns) @ coef
    out = []
    for row, tide in zip(valid, predicted):
        out.append({
            "timestamp": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else row["timestamp"],
            "station_id": row["station_id"], "observed_m": round(float(row["observed_level_m"]), 4),
            "predicted_tide_m": round(float(tide), 4),
            "surge_residual_m": round(float(row["observed_level_m"] - tide), 4),
            "datum": row["datum"], "quality_flag": row["quality_flag"],
        })
    return out
