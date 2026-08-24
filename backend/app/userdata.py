# -*- coding: utf-8 -*-
"""User-facing data ingestion and manual state-model experiments.

Uploads are quality-controlled and landed as auditable data artefacts.  They do
not cause an HTTP request to start model training.  Manual forecasts use the
same conservative ensemble state model as the online forecast/simulation stack;
no synthetic-label PyTorch checkpoint is loaded here.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Tuple

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
USER_DIR = ROOT / "backend" / "data" / "user"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_ROWS = 500_000
DEPTH_THRESHOLD_M = 0.15
RISK_LEVELS = ("无", "低", "中", "高", "极高")


# ---------------- 实时最新数据 ----------------
def current_conditions():
    from . import weather

    snapshot = weather.forecast_snapshot(forecast_days=1)
    times = snapshot["times"]
    rainfall = snapshot["districts"]
    city = snapshot["city"]
    return {
        "kind": "forecast",
        "issued_at": snapshot.get("issued_at"),
        "valid_at": times[0] if times else None,
        "generated_at": snapshot.get("issued_at") or (times[0] if times else None),
        "forecast_run_id": snapshot.get("forecast_run_id"),
        "data_source": "fallback-sample" if snapshot["fallback"] else "open-meteo-multi-point",
        "city_rainfall_forecast_mm_h": city[0] if city else 0,
        "city_rainfall": city[0] if city else 0,
        "hour": times[0] if times else None,
        "districts": {key: (values[0] if values else 0) for key, values in rainfall.items()},
    }


# ---------------- 手动输入预测 ----------------
def _rainfall_series(values: Iterable[Any]) -> np.ndarray:
    if isinstance(values, (str, bytes)):
        raise ValueError("rainfall 必须是逐小时数值数组")
    try:
        rain = np.asarray([float(value) for value in values], dtype=float)
    except (TypeError, ValueError):
        raise ValueError("rainfall 必须是逐小时数值数组") from None
    if rain.ndim != 1 or len(rain) == 0:
        raise ValueError("rainfall 至少包含 1 个小时")
    if len(rain) > 240:
        raise ValueError("手动推演最多支持 240 小时")
    if np.any(~np.isfinite(rain)) or np.any(rain < 0.0) or np.any(rain > 500.0):
        raise ValueError("rainfall 必须是 0..500 mm/h 的有限数值")
    return rain


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> Tuple[float, float]:
    """Binomial interval for an ensemble threshold frequency (not calibration)."""
    if total <= 0:
        return 0.0, 1.0
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    half = z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * total)) / total) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def _depth_level(depth_mm: float) -> int:
    if depth_mm >= 500.0:
        return 4
    if depth_mm >= 300.0:
        return 3
    if depth_mm >= 150.0:
        return 2
    if depth_mm >= 50.0:
        return 1
    return 0


def manual_forecast(district_id, rainfall, tide_raise=0.0):
    """Run a selected-district rainfall scenario through the physical ensemble.

    Rainfall is applied only to ``district_id``; other districts receive zero
    rainfall but still participate in downhill routing. ``prob`` is retained as
    a compatibility field and means the empirical ensemble frequency of depth
    >= 0.15 m. It is not presented as a calibrated real-world probability.
    """
    from . import ocean, shenzhen
    from .state_model import DEFAULT_MODEL

    district_id = str(district_id)
    district = shenzhen.get_district(district_id)
    if district is None:
        return {"status": "error", "error": f"未知行政区: {district_id}"}
    try:
        rain = _rainfall_series(rainfall)
        tide_raise = float(tide_raise)
    except (TypeError, ValueError) as exc:
        return {"status": "error", "error": str(exc)}
    if not np.isfinite(tide_raise) or not 0.0 <= tide_raise <= 5.0:
        return {"status": "error", "error": "tide_raise 必须是 0..5 m 的有限数值"}

    steps = len(rain)
    rainfall_by_district = {
        did: (rain.copy() if did == district_id else np.zeros(steps, dtype=float))
        for did in DEFAULT_MODEL.district_ids
    }
    # The phase is relative because a manual scenario has no forecast issue time.
    tide_m = ocean.harmonic_tide(np.arange(steps, dtype=float)) + tide_raise
    seed_material = json.dumps(
        {"district": district_id, "rainfall": rain.tolist(), "tide_raise": tide_raise},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:4], "big")
    result = DEFAULT_MODEL.simulate_ensemble(
        rainfall_by_district,
        tide_m=tide_m,
        n_members=80,
        seed=seed,
        thresholds_mm=(50.0, 150.0, 300.0, 500.0),
    )
    index = DEFAULT_MODEL.index[district_id]
    members = np.asarray(result["members_depth_mm"], dtype=float)[:, :, index]
    p10 = np.asarray(result["depth_p10_mm"], dtype=float)[:, index]
    p50 = np.asarray(result["depth_p50_mm"], dtype=float)[:, index]
    p90 = np.asarray(result["depth_p90_mm"], dtype=float)[:, index]
    exceed = np.asarray(result["exceedance_probability"][150.0], dtype=float)[:, index]

    intervals: List[Tuple[float, float]] = []
    for step in range(steps):
        successes = int(np.count_nonzero(members[:, step] >= 150.0))
        intervals.append(_wilson_interval(successes, members.shape[0]))

    peak_index = int(np.argmax(p50))
    peak_depth = float(p50[peak_index])
    peak_probability = float(exceed[peak_index])
    level = _depth_level(peak_depth)
    parameters = DEFAULT_MODEL.parameters
    static_exposure = float(
        0.45 * parameters["low_lying_ratio"][index]
        + 0.40 * parameters["impervious_ratio"][index]
        + 0.15 * parameters["coastal_exposure"][index]
    )
    hours = [f"+{step + 1}h" for step in range(steps)]
    return {
        "status": "ok",
        "district": district_id,
        "district_name": district["name"],
        "input_scope": "rainfall applies to selected district only; other districts are dry routing nodes",
        "static_exposure_index": round(static_exposure, 4),
        "vulnerability": round(static_exposure, 4),  # compatibility alias
        "drainage": round(float(parameters["drainage_capacity_mm_h"][index]), 3),
        "peak_depth_p50_m": round(peak_depth / 1000.0, 4),
        "peak_depth_p10_m": round(float(p10[peak_index]) / 1000.0, 4),
        "peak_depth_p90_m": round(float(p90[peak_index]) / 1000.0, 4),
        "peak_prob": round(peak_probability, 4),
        "peak_prob_semantics": "empirical ensemble frequency: water_depth_m >= 0.15; not calibrated",
        "max_threshold_probability": round(float(np.max(exceed)), 4),
        "peak_level": RISK_LEVELS[level],
        "peak_level_idx": level,
        "peak_time": hours[peak_index],
        "model": {
            "family": "conservative graph state-space parameter ensemble",
            "members": int(result["n_members"]),
            "seed": seed,
            "observation_assimilation": "not used for manual scenario",
        },
        "uncertainty": {
            "method": "parameter ensemble (runoff/drainage/two-stage storage/routing/external export)",
            "depth_std_m_at_peak": round(float(np.std(members[:, peak_index])) / 1000.0, 4),
            "ensemble_frequency_interval": [
                round(intervals[peak_index][0], 4),
                round(intervals[peak_index][1], 4),
            ],
            "warning": "集合仅传播参数不确定性，尚未包含气象集合与事件校准误差。",
        },
        "trajectory": [
            {
                "h": hours[step],
                "prob": round(float(exceed[step]), 4),
                "lo": round(intervals[step][0], 4),
                "hi": round(intervals[step][1], 4),
                "depth_p10_m": round(float(p10[step]) / 1000.0, 4),
                "depth_p50_m": round(float(p50[step]) / 1000.0, 4),
                "depth_p90_m": round(float(p90[step]) / 1000.0, 4),
                "threshold_prob": {
                    "gt_0_15m": round(float(exceed[step]), 4),
                },
            }
            for step in range(steps)
        ],
        "audit": result["audit"],
        "provenance": {
            "rainfall": "user-provided scenario",
            "tide": "simulated(harmonic proxy + user sea-level raise)",
            "state_model": "simulated(uncalibrated district-scale grey-box)",
        },
    }


# ---------------- 用户上传数据：严格 QC + 落盘，不自动训练 ----------------
def _parse_aware_timestamp(value: str, field: str, row_number: int) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"第 {row_number} 行 {field} 为空")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"第 {row_number} 行 {field} 不是 ISO8601 时间") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"第 {row_number} 行 {field} 必须包含时区偏移")
    return parsed


def _finite_number(value: str, field: str, row_number: int, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"第 {row_number} 行 {field} 不是数值") from None
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"第 {row_number} 行 {field} 必须在 {low}..{high} 范围内")
    return number


def _safe_upload_name(filename: str, digest: str) -> str:
    original = Path(os.path.basename(filename or "user_data.csv"))
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", original.stem).strip("._") or "user_data"
    return f"{stem[:80]}-{digest[:12]}.csv"


def _upload_readiness(
    rows: List[Dict[str, str]],
    has_depth: bool,
    has_flooded: bool,
    has_available_at: bool,
    mismatch_count: int,
) -> Dict[str, Any]:
    events = {str(row["event_id"]).strip() for row in rows}
    if has_depth:
        positive_events = {
            str(row["event_id"]).strip()
            for row in rows
            if float(row["water_depth_m"]) >= DEPTH_THRESHOLD_M
        }
        label_mode = "independent_depth_observation"
    else:
        positive_events = {
            str(row["event_id"]).strip()
            for row in rows
            if str(row.get("flooded", "")).strip() == "1"
        }
        label_mode = "binary_only_compatibility"

    development_ready = bool(has_depth and has_available_at and len(events) >= 3 and positive_events)
    blockers = []
    if not has_depth:
        blockers.append("缺少 water_depth_m；flooded 兼容列不能训练/校准连续积水深度")
    if not has_available_at:
        blockers.append("缺少 available_at，无法审计数据在预报签发时是否已可用")
    if len(events) < 3:
        blockers.append("独立 event_id 少于 3，无法进行事件级 train/validation/test 留出")
    if not positive_events:
        blockers.append("没有达到 0.15m（或 flooded=1）的正事件")
    if mismatch_count:
        blockers.append(f"water_depth_m 与 flooded(0.15m规则) 有 {mismatch_count} 行不一致，需确认标签口径")
    return {
        "schema_qc_passed": True,
        "label_mode": label_mode,
        "rows": len(rows),
        "independent_events": len(events),
        "positive_events": len(positive_events),
        "depth_supervision_available": has_depth,
        "availability_time_auditable": has_available_at,
        "eligible_for_model_development": development_ready and mismatch_count == 0,
        "forecast_skill_claim_ready": False,
        "blockers": blockers,
        "note": (
            "通过上传 QC 仅表示数据可以落盘；模型能力仍须经过来源审核、事件去重、"
            "rolling-origin 回放和独立测试，上传不会自动训练。"
        ),
    }


def upload_data(filename, content_bytes):
    """Validate and land an event CSV without starting any training process."""
    from . import observations, shenzhen

    if not isinstance(content_bytes, (bytes, bytearray)) or not content_bytes:
        return {"status": "error", "hint": "上传文件为空"}
    if len(content_bytes) > MAX_UPLOAD_BYTES:
        return {"status": "error", "hint": f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 限制"}
    try:
        text = bytes(content_bytes).decode("utf-8-sig")
    except UnicodeDecodeError:
        return {"status": "error", "hint": "CSV 必须使用 UTF-8 编码"}
    if "\x00" in text:
        return {"status": "error", "hint": "CSV 含 NUL 字符，拒绝落盘"}

    try:
        reader = csv.DictReader(io.StringIO(text))
        raw_headers = [str(value or "") for value in (reader.fieldnames or [])]
        headers = [value.strip() for value in raw_headers]
        if not headers or any(not value for value in headers):
            raise ValueError("CSV 缺少有效表头")
        if headers != raw_headers:
            raise ValueError("CSV 列名首尾不能含空白字符")
        if len(headers) != len(set(headers)):
            raise ValueError("CSV 含重复列名")
        required = {"timestamp", "event_id", "district_id", "rainfall_mm"}
        missing = sorted(required - set(headers))
        if missing:
            raise ValueError(f"缺少必需列 {missing}")
        has_depth = "water_depth_m" in headers
        has_flooded = "flooded" in headers
        if not has_depth and not has_flooded:
            raise ValueError("需包含 water_depth_m；仅有历史二分类时可用 flooded(0/1) 兼容列")

        rows = list(reader)
        if not rows:
            raise ValueError("CSV 没有数据行")
        if len(rows) > MAX_UPLOAD_ROWS:
            raise ValueError(f"CSV 超过 {MAX_UPLOAD_ROWS} 行限制")

        district_ids = {district["id"] for district in shenzhen.DISTRICTS}
        seen = set()
        mismatch_count = 0
        has_available_at = "available_at" in headers
        for row_index, row in enumerate(rows, start=2):
            if None in row:
                raise ValueError(f"第 {row_index} 行字段数多于表头")
            timestamp = _parse_aware_timestamp(row.get("timestamp", ""), "timestamp", row_index)
            event_id = str(row.get("event_id", "")).strip()
            district_id = str(row.get("district_id", "")).strip()
            if not event_id:
                raise ValueError(f"第 {row_index} 行 event_id 为空")
            if district_id not in district_ids:
                raise ValueError(f"第 {row_index} 行 district_id 未知: {district_id}")
            _finite_number(row.get("rainfall_mm", ""), "rainfall_mm", row_index, 0.0, 500.0)

            available_at = None
            if has_available_at:
                available_at = _parse_aware_timestamp(
                    row.get("available_at", ""), "available_at", row_index
                )
                if available_at.astimezone(timezone.utc) < timestamp.astimezone(timezone.utc):
                    raise ValueError(f"第 {row_index} 行 available_at 早于 timestamp")

            depth = None
            flooded = None
            if has_depth:
                depth = _finite_number(
                    row.get("water_depth_m", ""), "water_depth_m", row_index, 0.0, 10.0
                )
            if has_flooded:
                raw_flooded = str(row.get("flooded", "")).strip()
                if raw_flooded not in {"0", "1"}:
                    raise ValueError(f"第 {row_index} 行 flooded 必须为 0 或 1")
                flooded = int(raw_flooded)
            if depth is not None and flooded is not None:
                mismatch_count += int(flooded != int(depth >= DEPTH_THRESHOLD_M))

            unique_key = (event_id, district_id, timestamp.astimezone(timezone.utc).isoformat())
            if unique_key in seen:
                raise ValueError(f"第 {row_index} 行事件/行政区/观测时间重复")
            seen.add(unique_key)
    except (csv.Error, ValueError) as exc:
        return {
            "status": "error",
            "hint": (
                f"Schema/QC 未通过: {exc}。推荐列：timestamp,event_id,district_id,"
                "rainfall_mm,water_depth_m,available_at"
            ),
        }

    readiness = _upload_readiness(rows, has_depth, has_flooded, has_available_at, mismatch_count)
    digest = hashlib.sha256(bytes(content_bytes)).hexdigest()
    safe_name = _safe_upload_name(str(filename or "user_data.csv"), digest)
    destination_dir = Path(USER_DIR)
    destination_dir.mkdir(parents=True, exist_ok=True)
    path = destination_dir / safe_name
    qc_path = destination_dir / f"{Path(safe_name).stem}.qc.json"

    # Only write after the whole file has passed structural and row-level QC.
    if not path.exists():
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    qc_report = {
        "schema_version": "event-depth-v2",
        "content_sha256": digest,
        "source_filename": os.path.basename(str(filename or "user_data.csv")),
        "saved_filename": safe_name,
        "qc_at": datetime.now(timezone.utc).isoformat(),
        "columns": headers,
        "threshold_consistency_rule_m": DEPTH_THRESHOLD_M,
        "depth_flooded_mismatch_rows": mismatch_count,
        "readiness": readiness,
    }
    with qc_path.open("w", encoding="utf-8") as handle:
        json.dump(qc_report, handle, ensure_ascii=False, indent=2)

    return {
        "status": "ok",
        "action": "saved_not_trained",
        "training_triggered": False,
        "saved": safe_name,
        "qc_saved": qc_path.name,
        "sha256": digest,
        "rows": len(rows),
        "readiness": readiness,
        "project_readiness": observations.data_readiness(),
        "hint": "文件已通过 Schema/QC 并落盘；未触发训练。",
    }
