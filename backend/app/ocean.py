# -*- coding: utf-8 -*-
"""沿海城市复合内涝的海洋边界条件（P1 物理代理）。

当前阶段使用可解释的调和潮 + 参数化风暴增水，不冒充潮位站实测。
真实站点数据接入后，只需替换 ``build_boundary`` 的输入序列，输出契约保持不变。
"""
from __future__ import annotations

from datetime import datetime

import numpy as np


PROVENANCE = {
    "astronomical_tide": "predicted(harmonic-proxy; M2/S2/K1/O1)",
    "storm_surge": "simulated(parametric-gaussian)",
    "drainage_coupling": "estimated(head-difference-proxy; uncalibrated)",
}

DISTRICT_BOUNDARIES = {
    "futian": {"boundary": "深圳湾", "stations": ["chiwan"], "gravity_share": 0.45, "pump_share": 0.55},
    "nanshan": {"boundary": "深圳湾/珠江口", "stations": ["chiwan", "shenzhen_temp"], "gravity_share": 0.55, "pump_share": 0.45},
    "baoan": {"boundary": "珠江口", "stations": ["shenzhen_temp"], "gravity_share": 0.65, "pump_share": 0.35},
    "yantian": {"boundary": "大鹏湾", "stations": ["yantian"], "gravity_share": 0.70, "pump_share": 0.30},
    "dapeng": {"boundary": "大鹏湾/大亚湾", "stations": ["yantian", "huizhou"], "gravity_share": 0.75, "pump_share": 0.25},
}


def _hours_from_times(times):
    if not times:
        return np.array([], dtype=float)
    out = []
    t0 = datetime.fromisoformat(times[0])
    for value in times:
        out.append((datetime.fromisoformat(value) - t0).total_seconds() / 3600.0)
    return np.asarray(out, dtype=float)


def harmonic_tide(hours, mean_level_m=0.0, amplitude_m=0.75, phase_h=0.0):
    """四分潮简化重建，输出相对统一基准面的天文潮位（m）。"""
    h = np.asarray(hours, dtype=float) + float(phase_h)
    amp = max(0.0, float(amplitude_m))
    constituents = (
        (0.62, 12.4206, 0.0),   # M2
        (0.18, 12.0000, 0.55),  # S2
        (0.12, 23.9345, -0.35), # K1
        (0.08, 25.8193, 0.90),  # O1
    )
    tide = np.full_like(h, float(mean_level_m), dtype=float)
    for weight, period, phase in constituents:
        tide += amp * weight * np.cos(2 * np.pi * h / period + phase)
    return tide


def storm_surge(hours, peak_m=0.0, peak_offset_h=20.0, duration_h=12.0):
    """平滑参数化增水；duration_h 近似控制主要增水过程宽度。"""
    h = np.asarray(hours, dtype=float)
    sigma = max(1.0, float(duration_h) / 2.355)
    return max(0.0, float(peak_m)) * np.exp(-0.5 * ((h - float(peak_offset_h)) / sigma) ** 2)


def normalize_level(level_m):
    """将海面高度映射为 LSTM 现有的 0..1 潮位特征。"""
    return np.clip((np.asarray(level_m, dtype=float) + 1.0) / 2.5, 0.0, 1.0)


def drainage_factor(total_level_m, coastal_exposure, threshold_m=0.35,
                    max_reduction=0.55, transition_m=0.9, gravity_share=1.0):
    """外海水位升高导致重力排水受限；内陆区通过 coastal_exposure 衰减。"""
    level = np.asarray(total_level_m, dtype=float)
    pressure = np.clip((level - float(threshold_m)) / max(0.1, float(transition_m)), 0.0, 1.0)
    reduction = (np.clip(float(coastal_exposure), 0.0, 1.0)
                 * np.clip(float(gravity_share), 0.0, 1.0)
                 * float(max_reduction) * pressure)
    return np.clip(1.0 - reduction, 0.35, 1.0)


def district_drainage_factor(total_level_m, district_id, coastal_exposure):
    meta = DISTRICT_BOUNDARIES.get(district_id, {})
    return drainage_factor(total_level_m, coastal_exposure,
                           gravity_share=meta.get("gravity_share", 0.15))


def build_boundary(times, scenario=None, rainfall=None):
    scenario = scenario or {}
    hours = _hours_from_times(times)
    astronomical = harmonic_tide(
        hours,
        mean_level_m=scenario.get("mean_sea_level_m", 0.0),
        amplitude_m=scenario.get("tide_amplitude_m", 0.75),
        phase_h=scenario.get("tide_phase_h", 0.0),
    )
    legacy_raise = scenario.get("tide_raise", 0.0)
    surge = storm_surge(
        hours,
        peak_m=scenario.get("surge_peak_m", legacy_raise),
        peak_offset_h=scenario.get("surge_peak_offset_h", 20.0),
        duration_h=scenario.get("surge_duration_h", 12.0),
    )
    total = astronomical + surge
    rate = np.gradient(total, hours) if len(hours) > 1 else np.zeros_like(total)
    peak_idx = int(np.argmax(total)) if len(total) else 0
    # 复合事件以增水过程附近的高潮为目标，避免72小时窗起点恰为高潮时
    # “提前6小时”被裁剪成0小时而破坏控制实验。
    if len(total) and float(scenario.get("surge_peak_m", legacy_raise)) > 0:
        center = int(np.clip(round(float(scenario.get("surge_peak_offset_h", 20.0))), 0, len(total)-1))
        lo, hi = max(0, center-7), min(len(total), center+8)
        peak_idx = lo + int(np.argmax(total[lo:hi]))
    next_high_idx = peak_idx
    if len(total) > 2:
        local = [i for i in range(1, len(total)-1) if total[i] >= total[i-1] and total[i] >= total[i+1]]
        next_high_idx = next((i for i in local if i >= 0), peak_idx)
    rain_peak_idx = int(np.argmax(rainfall)) if rainfall is not None and len(rainfall) else None
    measured_offset = (rain_peak_idx - peak_idx) if rain_peak_idx is not None else None
    offset = (int(round(float(scenario["rain_tide_peak_offset_h"])))
              if "rain_tide_peak_offset_h" in scenario else measured_offset)

    # 复合指数只用于情景间比较，不是观测概率。
    rain_norm = 0.0 if rainfall is None or not len(rainfall) else min(float(np.max(rainfall)) / 100.0, 1.0)
    sea_norm = 0.0 if not len(total) else float(np.clip((np.max(total) + 0.5) / 2.0, 0, 1))
    overlap = 0.0 if offset is None else float(np.exp(-abs(offset) / 6.0))
    compound_index = float(np.clip(0.4 * rain_norm + 0.35 * sea_norm + 0.25 * overlap, 0, 1))

    def rounded(values):
        return [round(float(v), 4) for v in values]

    return {
        "times": list(times),
        "astronomical_tide_m": rounded(astronomical),
        "storm_surge_m": rounded(surge),
        "total_level_m": rounded(total),
        "tide_feature": rounded(normalize_level(total)),
        "level_rate_m_h": rounded(rate),
        "tide_phase": ["rising" if v > 0.01 else "falling" if v < -0.01 else "slack" for v in rate],
        "time_to_next_high_tide_h": [max(0, next_high_idx - i) for i in range(len(total))],
        "onshore_wind_component_m_s": scenario.get("onshore_wind_component_m_s"),
        "pressure_anomaly_hpa": scenario.get("pressure_anomaly_hpa"),
        "outfall_head_difference_m": rounded(np.maximum(0.0, scenario.get("outfall_invert_m", 1.1) - total)),
        "peak": {
            "index": peak_idx,
            "time": times[peak_idx] if times else None,
            "total_level_m": round(float(total[peak_idx]), 3) if len(total) else None,
            "surge_m": round(float(surge[peak_idx]), 3) if len(surge) else None,
        },
        "rain_peak_index": rain_peak_idx,
        "rain_tide_peak_offset_h": offset,
        "diagnosed_rain_tide_peak_offset_h": measured_offset,
        "compound_index": round(compound_index, 3),
        "station": {"id": None, "datum": None, "updated_at": None, "quality": "unavailable"},
        "uncertainty": {"level": "high", "reason": "尚无统一基准面的深圳潮位站实测序列"},
        "district_boundaries": DISTRICT_BOUNDARIES,
        "provenance": PROVENANCE,
        "warning": "调和潮与风暴增水为物理代理，尚未使用统一基准面的深圳潮位站实测校准。",
    }
