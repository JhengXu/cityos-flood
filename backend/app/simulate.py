# -*- coding: utf-8 -*-
"""
SIMULATE 引擎：What-if 情景沙盘（如「台风 + 天文大潮」全城影响推演）
---------------------------------------------------------------
以真实降雨网格预报为基线，叠加情景参数（降雨放大 / 额外暴雨峰值 / 泵站降效 / 潮位抬升），
用 LSTM 时序推演模型重算各区分时风险，对比基线 vs 情景，并输出泵站调度与预警。
"""
import numpy as np

from . import weather, model, dispatch, ocean
from .shenzhen import DISTRICTS, CITY


def _apply_scenario(rainfall_seq, scenario, spatial_weight=1.0):
    mult = float(scenario.get("rainfall_multiplier", 1.0))
    add_peak = float(scenario.get("add_peak_mm", 0.0))
    offset = int(scenario.get("peak_offset_h", int(len(rainfall_seq) * 0.5)))
    T = len(rainfall_seq)
    bump = np.zeros(T)
    if add_peak > 0:
        tt = np.linspace(0, 1, T)
        center = offset / T if T else 0.5
        bump = add_peak * spatial_weight * np.exp(-((tt - center) ** 2) / 0.01)
    return np.clip(np.array(rainfall_seq) * mult + bump, 0, None)


def simulate(scenario, forecast_days=3):
    fc = weather.downscaled_forecast(forecast_days)
    times = fc["times"]
    T = len(times)
    city_rain = fc.get("city") or []
    base_ocean = ocean.build_boundary(times, {"surge_peak_m": 0.0}, city_rain)
    scen_cfg = dict(scenario)
    # 若指定雨潮错位，让额外降雨峰值相对海面峰值移动。
    if "rain_tide_peak_offset_h" in scen_cfg:
        preview = ocean.build_boundary(times, scen_cfg)
        scen_cfg["peak_offset_h"] = int(np.clip(
            preview["peak"]["index"] + float(scen_cfg["rain_tide_peak_offset_h"]), 0, max(0, T - 1)
        ))
    scen_city_rain = _apply_scenario(city_rain, scen_cfg)
    scenario_ocean = ocean.build_boundary(times, scen_cfg, scen_city_rain)
    drainage_factor = float(scenario.get("drainage_factor", 1.0))

    districts_out = []
    alert_inputs = []
    for d in DISTRICTS:
        V, _ = model.district_vulnerability(d)
        C = d["drainage_design"]

        base_rain = fc["districts"][d["id"]]
        base_cum = model.compute_cum_seq(base_rain)
        base_drain_factor = ocean.district_drainage_factor(
            base_ocean["total_level_m"], d["id"], d["coastal"])
        base_C = C * base_drain_factor
        Xb = model.build_seq_features(base_rain, base_cum, V, base_C, base_ocean["tide_feature"])
        base_prob = model.SEQ_MODEL.net.predict_seq(Xb)

        # 台风降雨随海岸暴露度空间加权（沿海/低地更重），更贴近真实且增强区分度
        spatial_weight = 0.5 + 0.9 * d["coastal"]
        scen_rain = _apply_scenario(base_rain, scen_cfg, spatial_weight=spatial_weight)
        scen_cum = model.compute_cum_seq(list(scen_rain))
        ocean_factor = ocean.district_drainage_factor(
            scenario_ocean["total_level_m"], d["id"], d["coastal"])
        C_eff = C * drainage_factor * ocean_factor
        Xs = model.build_seq_features(
            list(scen_rain), scen_cum, V, C_eff, scenario_ocean["tide_feature"]
        )
        scen_prob = model.SEQ_MODEL.net.predict_seq(Xs)

        def _peak(prob):
            idx = int(np.argmax(prob))
            return idx, float(prob[idx])

        b_idx, b_p = _peak(base_prob)
        s_idx, s_p = _peak(scen_prob)
        b_lv = model.FloodRiskModel._level(b_p)
        s_lv = model.FloodRiskModel._level(s_p)

        districts_out.append({
            "id": d["id"],
            "name": d["name"],
            "center": d["center"],
            "base_prob": [round(float(x), 4) for x in base_prob],
            "scenario_prob": [round(float(x), 4) for x in scen_prob],
            "base_peak": {"index": b_idx, "time": times[b_idx], "level": b_lv,
                          "level_label": model.RISK_LEVELS[b_lv], "prob": round(b_p, 4)},
            "scenario_peak": {"index": s_idx, "time": times[s_idx], "level": s_lv,
                              "level_label": model.RISK_LEVELS[s_lv], "prob": round(s_p, 4)},
            "delta_prob": round(s_p - b_p, 4),
            "vulnerability": V,
            "coastal_exposure": d["coastal"],
            "min_drainage_factor": round(float(np.min(ocean_factor) * drainage_factor), 3),
            "ocean_boundary": ocean.DISTRICT_BOUNDARIES.get(d["id"], {"boundary": "内陆/河网", "stations": [], "gravity_share": 0.15, "pump_share": 0.85}),
        })
        # 用于预警：取情景与基线中的更高峰值
        pk_level = max(b_lv, s_lv)
        pk_prob = max(b_p, s_p)
        pk_idx = s_idx if s_p >= b_p else b_idx
        alert_inputs.append({
            "id": d["id"], "name": d["name"],
            "peak_level": pk_level, "peak_prob": pk_prob, "peak_index": pk_idx,
            "tide_high": (scenario_ocean["peak"]["total_level_m"] or 0) >= 0.8,
        })

    alerts = dispatch.generate_alerts(alert_inputs, times)
    return {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone(__import__("datetime").timedelta(hours=8))
        ).isoformat(),
        "city": CITY,
        "scenario": scen_cfg,
        "times": times,
        "baseline_tide": base_ocean["tide_feature"],
        "ocean": scenario_ocean,
        "districts": districts_out,
        "alerts": alerts,
        "alert_count": len(alerts),
        "worst_district": max(districts_out, key=lambda x: x["scenario_peak"]["prob"])["name"],
    }


# 预设情景（前端可直接选用）
SCENARIOS = {
    "baseline": {"label": "现状预报（基线）", "rainfall_multiplier": 1.0, "add_peak_mm": 0,
                 "peak_offset_h": 18, "drainage_factor": 1.0, "surge_peak_m": 0.0},
    "typhoon_tide": {"label": "台风 + 天文大潮", "rainfall_multiplier": 1.3, "add_peak_mm": 22,
                     "drainage_factor": 0.85, "tide_amplitude_m": 0.95,
                     "surge_peak_m": 0.65, "surge_peak_offset_h": 20,
                     "surge_duration_h": 14, "rain_tide_peak_offset_h": 0},
    "rain_6h_before_tide": {"label": "雨峰提前高潮6小时", "rainfall_multiplier": 1.3, "add_peak_mm": 22,
                            "tide_amplitude_m": 0.95, "surge_peak_m": 0.65, "rain_tide_peak_offset_h": -6},
    "rain_with_tide": {"label": "雨峰与高潮重合", "rainfall_multiplier": 1.3, "add_peak_mm": 22,
                       "tide_amplitude_m": 0.95, "surge_peak_m": 0.65, "rain_tide_peak_offset_h": 0},
    "rain_6h_after_tide": {"label": "雨峰滞后高潮6小时", "rainfall_multiplier": 1.3, "add_peak_mm": 22,
                           "tide_amplitude_m": 0.95, "surge_peak_m": 0.65, "rain_tide_peak_offset_h": 6},
    "pump_failure": {"label": "泵站降效 65%", "rainfall_multiplier": 1.15, "add_peak_mm": 12,
                     "peak_offset_h": 18, "drainage_factor": 0.65, "surge_peak_m": 0.1},
    "extreme": {"label": "极端特大暴雨", "rainfall_multiplier": 2.2, "add_peak_mm": 70,
                "peak_offset_h": 16, "drainage_factor": 0.85, "surge_peak_m": 0.2},
}
