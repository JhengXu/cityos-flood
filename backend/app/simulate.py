# -*- coding: utf-8 -*-
"""What-if engine backed by the same conservative model as `/api/predict`."""
from __future__ import annotations

import hashlib
import json

import numpy as np

from . import dispatch, forecasting, ocean, shenzhen, state_model, weather
from .risk import RISK_LEVELS, level_from_depth


_SIMULATION_CACHE = {}

def _apply_scenario(rainfall_seq, scenario, spatial_weight=1.0):
    mult = float(scenario.get("rainfall_multiplier", 1.0))
    add_peak = float(scenario.get("add_peak_mm", 0.0))
    if mult < 0.0 or add_peak < 0.0:
        raise ValueError("rainfall_multiplier and add_peak_mm must be non-negative")
    offset = int(scenario.get("peak_offset_h", int(len(rainfall_seq) * 0.5)))
    total = len(rainfall_seq)
    bump = np.zeros(total)
    if add_peak > 0 and total:
        hours = np.arange(total, dtype=float)
        sigma_h = max(1.5, float(scenario.get("rain_peak_sigma_h", 3.0)))
        bump = add_peak * float(spatial_weight) * np.exp(-0.5 * ((hours - offset) / sigma_h) ** 2)
    return np.clip(np.asarray(rainfall_seq, dtype=float) * mult + bump, 0.0, None)


def _probability_series(ensemble, district_index, threshold=150.0):
    return ensemble["exceedance_probability"][float(threshold)][:, district_index]


def _depth_series(ensemble, district_index, quantile):
    return ensemble[f"depth_p{quantile}_mm"][:, district_index] / 1000.0


def _peak(times, p10, p50, p90, probability):
    index = forecasting.select_peak_index(p50, probability)
    level = level_from_depth(p50[index] * 1000.0)
    return {
        "index": index,
        "time": times[index],
        "prob": round(float(probability[index]), 4),
        "probability_definition": "P(representative water depth >= 0.15 m)",
        "level": level,
        "level_label": RISK_LEVELS[level],
        "depth_p10_m": round(float(p10[index]), 4),
        "depth_p50_m": round(float(p50[index]), 4),
        "depth_p90_m": round(float(p90[index]), 4),
    }


def _simulation_id(
    forecast_run_id, scenario, seed, n_members, baseline_model_run_id, scenario_model_run_id
):
    payload = {
        "forecast_run_id": forecast_run_id,
        "scenario": scenario,
        "model_version": forecasting.MODEL_VERSION,
        "seed": int(seed),
        "ensemble_members": int(n_members),
        "baseline_model_run_id": baseline_model_run_id,
        "scenario_model_run_id": scenario_model_run_id,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def simulate(
    scenario,
    forecast_days=3,
    snapshot=None,
    n_members=forecasting.ENSEMBLE_SIZE,
    forecast_run_id=None,
):
    snapshot = snapshot or weather.resolve_snapshot(forecast_days, forecast_run_id)
    if forecast_run_id and snapshot.get("forecast_run_id") != str(forecast_run_id):
        raise ValueError("snapshot does not match requested forecast_run_id")
    times = list(snapshot.get("times") or [])
    if not times:
        raise ValueError("forecast snapshot contains no future time steps")
    total = len(times)
    city_rain = list(snapshot.get("city") or [0.0] * total)
    scen_cfg = dict(scenario or {})

    # Let peak offset control only the extra event; this makes the compound
    # rain/tide experiment identifiable while keeping the baseline unchanged.
    if "rain_tide_peak_offset_h" in scen_cfg:
        preview = ocean.build_boundary(times, scen_cfg)
        scen_cfg["peak_offset_h"] = int(np.clip(
            preview["peak"]["index"] + float(scen_cfg["rain_tide_peak_offset_h"]),
            0,
            max(0, total - 1),
        ))
    scenario_city_rain = _apply_scenario(city_rain, scen_cfg)
    scenario_ocean = ocean.build_boundary(times, scen_cfg, scenario_city_rain)
    drainage_factor = float(scen_cfg.get("drainage_factor", 1.0))
    if drainage_factor < 0.0:
        raise ValueError("drainage_factor must be non-negative")
    pump_efficiency = float(scen_cfg.get("pump_efficiency", 1.0))
    if not 0.0 <= pump_efficiency <= 1.0:
        raise ValueError("pump_efficiency must be between 0 and 1")

    baseline_rain = {did: list(values) for did, values in snapshot["districts"].items()}
    scenario_rain = {}
    for district in shenzhen.DISTRICTS:
        # Exposure is applied only to the extra hypothetical storm, not to the
        # baseline forecast field.
        weight = 0.65 + 0.55 * float(district["coastal"]) + 0.25 * float(district["low_lying_ratio"])
        scenario_rain[district["id"]] = _apply_scenario(
            baseline_rain[district["id"]], scen_cfg, spatial_weight=weight
        )

    baseline, base_ocean, live_observations = forecasting.ensemble_for_snapshot(
        snapshot, n_members=n_members
    )
    common_salt = forecasting.CANONICAL_ENSEMBLE_SALT
    scenario_result = forecasting.run_ensemble(
        scenario_rain,
        scenario_ocean["total_level_m"],
        forecast_run_id=snapshot.get("forecast_run_id", "unknown"),
        seed_salt=common_salt,
        n_members=n_members,
        drainage_control=drainage_factor,
        pump_efficiency=pump_efficiency,
        initial_depth_mm=baseline["members_initial_depth_mm"],
        sampled_parameters=baseline["sampled_parameters"],
    )
    seed = baseline["seed"]

    districts_out = []
    alert_inputs = []
    for index, district in enumerate(shenzhen.DISTRICTS):
        base_prob = _probability_series(baseline, index)
        scen_prob = _probability_series(scenario_result, index)
        b10, b50, b90 = (_depth_series(baseline, index, q) for q in (10, 50, 90))
        s10, s50, s90 = (_depth_series(scenario_result, index, q) for q in (10, 50, 90))
        base_peak = _peak(times, b10, b50, b90, base_prob)
        scenario_peak = _peak(times, s10, s50, s90, scen_prob)
        did = district["id"]
        coastal_exposure = float(
            state_model.DEFAULT_MODEL.parameters["coastal_exposure"][index]
        )
        total_level = np.asarray(scenario_ocean["total_level_m"], dtype=float)
        x = np.clip((total_level - 0.5) / 0.25, -40.0, 40.0)
        tide_availability = np.clip(
            1.0 - 0.78 * coastal_exposure / (1.0 + np.exp(-x)), 0.15, 1.0
        )
        actual_capacity_factor = drainage_factor * (
            0.65 * tide_availability + 0.35 * pump_efficiency
        )
        districts_out.append({
            "id": did,
            "name": district["name"],
            "center": district["center"],
            "base_prob": [round(float(x), 4) for x in base_prob],
            "scenario_prob": [round(float(x), 4) for x in scen_prob],
            "probability_definition": "P(representative water depth >= 0.15 m)",
            "base_depth_p10_m": [round(float(x), 4) for x in b10],
            "base_depth_p50_m": [round(float(x), 4) for x in b50],
            "base_depth_p90_m": [round(float(x), 4) for x in b90],
            "scenario_depth_p10_m": [round(float(x), 4) for x in s10],
            "scenario_depth_p50_m": [round(float(x), 4) for x in s50],
            "scenario_depth_p90_m": [round(float(x), 4) for x in s90],
            "base_peak": base_peak,
            "scenario_peak": scenario_peak,
            "delta_prob": round(scenario_peak["prob"] - base_peak["prob"], 4),
            "delta_peak_depth_m": round(
                scenario_peak["depth_p50_m"] - base_peak["depth_p50_m"], 4
            ),
            "coastal_exposure": district["coastal"],
            "min_drainage_factor": round(float(np.min(actual_capacity_factor)), 3),
            "drainage_factor_definition": "actual state-model design-capacity multiplier",
            "ocean_boundary": ocean.DISTRICT_BOUNDARIES.get(
                did,
                {"boundary": "内陆/河网", "stations": [], "gravity_share": 0.15, "pump_share": 0.85},
            ),
        })
        alert_inputs.append({
            "id": did,
            "name": district["name"],
            "peak_level": scenario_peak["level"],
            "peak_prob": scenario_peak["prob"],
            "peak_index": scenario_peak["index"],
            "peak_depth_m": scenario_peak["depth_p50_m"],
            "tide_high": (scenario_ocean["peak"]["total_level_m"] or 0) >= 0.8,
        })

    alerts = dispatch.generate_alerts(alert_inputs, times)
    simulation_id = _simulation_id(
        snapshot.get("forecast_run_id"),
        scen_cfg,
        seed,
        n_members,
        baseline["model_run_id"],
        scenario_result["model_run_id"],
    )
    worst = max(districts_out, key=lambda item: item["scenario_peak"]["depth_p50_m"])
    flags = ["uncalibrated_parameters", "district_scale_not_street_depth"]
    if snapshot.get("fallback"):
        flags.append("synthetic_rainfall_fallback")
    response = {
        "generated_at": snapshot.get("snapshot_created_at") or snapshot.get("issued_at"),
        "forecast_run_id": snapshot.get("forecast_run_id"),
        "forcing_selection_as_of": snapshot.get("forcing_selection_as_of"),
        "simulation_run_id": simulation_id,
        "model_version": forecasting.MODEL_VERSION,
        "baseline_model_run_id": baseline["model_run_id"],
        "scenario_model_run_id": scenario_result["model_run_id"],
        "parameter_ensemble_id": baseline["parameter_ensemble_id"],
        "seed": seed,
        "ensemble_members": int(n_members),
        "city": shenzhen.CITY,
        "scenario": scen_cfg,
        "times": times,
        "step_minutes": 60,
        "baseline_tide": base_ocean["tide_feature"],
        "ocean": scenario_ocean,
        "districts": districts_out,
        "alerts": alerts,
        "alert_count": len(alerts),
        "worst_district": worst["name"],
        "worst_peak_depth_m": worst["scenario_peak"]["depth_p50_m"],
        "initial_observations": live_observations,
        "initial_analysis": baseline["initial_analysis"],
        "quality_flags": flags,
        "mass_balance": {
            "baseline": baseline["audit"],
            "scenario": scenario_result["audit"],
        },
        "comparison_design": "paired common-parameter ensemble on one forecast snapshot",
    }
    _SIMULATION_CACHE[simulation_id] = response
    while len(_SIMULATION_CACHE) > 32:
        _SIMULATION_CACHE.pop(next(iter(_SIMULATION_CACHE)))
    return response


def get_cached(simulation_run_id):
    """Return the exact displayed run for dispatch replay when still resident."""
    return _SIMULATION_CACHE.get(str(simulation_run_id))


SCENARIOS = {
    "baseline": {"label": "现状预报（基线）", "rainfall_multiplier": 1.0, "add_peak_mm": 0,
                 "peak_offset_h": 18, "drainage_factor": 1.0, "surge_peak_m": 0.0},
    "typhoon_tide": {"label": "台风 + 天文大潮 + 排水降效15%", "rainfall_multiplier": 1.3, "add_peak_mm": 22,
                     "drainage_factor": 0.85, "tide_amplitude_m": 0.95,
                     "surge_peak_m": 0.65, "surge_peak_offset_h": 20,
                     "surge_duration_h": 14, "rain_tide_peak_offset_h": 0},
    "rain_6h_before_tide": {"label": "雨峰提前高潮6小时", "rainfall_multiplier": 1.3, "add_peak_mm": 22,
                            "tide_amplitude_m": 0.95, "surge_peak_m": 0.65, "rain_tide_peak_offset_h": -6},
    "rain_with_tide": {"label": "雨峰与高潮重合", "rainfall_multiplier": 1.3, "add_peak_mm": 22,
                       "tide_amplitude_m": 0.95, "surge_peak_m": 0.65, "rain_tide_peak_offset_h": 0},
    "rain_6h_after_tide": {"label": "雨峰滞后高潮6小时", "rainfall_multiplier": 1.3, "add_peak_mm": 22,
                           "tide_amplitude_m": 0.95, "surge_peak_m": 0.65, "rain_tide_peak_offset_h": 6},
    "pump_failure": {"label": "泵站失效 65%（剩余效能 35%）", "rainfall_multiplier": 1.0,
                     "add_peak_mm": 0, "peak_offset_h": 18,
                     "drainage_factor": 1.0, "pump_efficiency": 0.35,
                     "surge_peak_m": 0.0},
    "extreme": {"label": "极端特大暴雨（仅改变降雨）", "rainfall_multiplier": 2.2,
                "add_peak_mm": 70, "peak_offset_h": 16,
                "drainage_factor": 1.0, "pump_efficiency": 1.0,
                "surge_peak_m": 0.0},
}


__all__ = ["SCENARIOS", "_apply_scenario", "simulate", "get_cached"]
