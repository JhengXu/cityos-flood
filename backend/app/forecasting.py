# -*- coding: utf-8 -*-
"""Unified forecast service for the conservative district state model.

This module is the API boundary between physical NumPy arrays and JSON product
DTOs.  Both PREDICT and SIMULATE use the same state transition, thresholds and
seed derivation so that a displayed run can be reproduced by dispatch.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
from typing import Any, Mapping, Optional

import numpy as np

from . import observations, ocean, shenzhen, state_model
from .risk import (
    ACTIONABLE_DEPTH_MM,
    DEPTH_LEVEL_THRESHOLDS_MM,
    RISK_LEVELS,
    district_vulnerability,
    level_from_depth,
)


MODEL_NAME = "守恒图状态空间内涝模型 v3"
MODEL_VERSION = "3.2.0-antecedent-spinup-ensemble"
ENSEMBLE_SIZE = 64
CANONICAL_ENSEMBLE_SALT = "canonical-parameter-ensemble"
PROBABILITY_THRESHOLDS_MM = (50.0, 150.0, 300.0, 500.0)
INITIAL_REPRESENTATIVENESS_ERROR_M = 0.10
DEFAULT_INITIAL_LOCALIZATION_RADIUS_KM = 25.0
ANTECEDENT_SPINUP_HOURS = 24
_ENSEMBLE_LOCK = threading.RLock()
MAX_CANONICAL_ENSEMBLE_CACHE = 4
_CANONICAL_ENSEMBLE_CACHE = OrderedDict()
_NEXT_SNAPSHOT_CACHE_TOKEN = 0


def _round(value, digits=4):
    return round(float(value), digits)


def select_peak_index(depth_series, probability_series=None):
    """Depth-first, probability-second, earliest-index peak selection."""
    depth = np.asarray(depth_series, dtype=float)
    if depth.ndim != 1 or depth.size == 0 or np.any(~np.isfinite(depth)):
        raise ValueError("depth_series must be a non-empty finite vector")
    candidates = np.flatnonzero(depth == np.max(depth))
    if probability_series is not None and len(candidates) > 1:
        probability = np.asarray(probability_series, dtype=float)
        if probability.shape != depth.shape or np.any(~np.isfinite(probability)):
            raise ValueError("probability_series must match depth_series")
        values = probability[candidates]
        candidates = candidates[values == np.max(values)]
    return int(candidates[0])


def stable_seed(*parts: Any) -> int:
    raw = "|".join(str(part) for part in parts)
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8], 16)


def _jsonable(value):
    if isinstance(value, Mapping):
        return {str(key): _jsonable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _manifest_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()[:16]


def model_run_id(forecast_run_id: str, seed: int, config: Optional[Mapping[str, Any]] = None) -> str:
    payload = {
        "forecast_run_id": forecast_run_id,
        "model_version": MODEL_VERSION,
        "seed": int(seed),
        "config": dict(config or {}),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def fresh_initial_depth_mm(now=None):
    """Return fresh observation proxies for compatibility and diagnostics."""
    latest = observations.latest_district_observations(now=now)
    values = {did: item["depth_m"] * 1000.0 for did, item in latest.items()}
    return values, latest


def _antecedent_spinup(snapshot, sampled_parameters, n_members):
    """Roll the last 24 fully available hourly forcings into the initial state."""
    n_members = int(n_members)
    empty = np.zeros(
        (n_members, state_model.DEFAULT_MODEL.n_districts), dtype=float
    )
    unavailable = {
        "applied": False,
        "hours": 0,
        "source": snapshot.get("antecedent_provenance") or "unavailable",
        "reason": "complete audited antecedent hourly forcing is unavailable",
    }
    if not snapshot.get("antecedent_complete"):
        return empty, unavailable
    times = list(snapshot.get("antecedent_times") or [])
    rainfall = snapshot.get("antecedent_districts") or {}
    expected_ids = set(state_model.DEFAULT_MODEL.district_ids)
    if len(times) != ANTECEDENT_SPINUP_HOURS or set(rainfall) != expected_ids:
        return empty, {**unavailable, "reason": "antecedent forcing shape is incomplete"}
    if any(len(rainfall[did]) != len(times) for did in expected_ids):
        return empty, {**unavailable, "reason": "antecedent district series lengths differ"}
    if snapshot.get("antecedent_interval_semantics") != (
        "timestamp is interval end; precipitation is the preceding-hour sum"
    ):
        return empty, {**unavailable, "reason": "antecedent precipitation interval semantics are unknown"}
    issued_raw = snapshot.get("issued_at")
    if not issued_raw:
        return empty, {**unavailable, "reason": "snapshot has no audited issued_at"}
    issued_at = datetime.fromisoformat(str(issued_raw).replace("Z", "+00:00"))
    parsed = [datetime.fromisoformat(str(value).replace("Z", "+00:00")) for value in times]
    if issued_at.tzinfo is None or any(item.tzinfo is None for item in parsed):
        return empty, {**unavailable, "reason": "antecedent or issuance time lacks timezone"}
    if any(
        (right - left).total_seconds() != 3600.0
        for left, right in zip(parsed, parsed[1:])
    ) or parsed[-1] > issued_at.astimezone(parsed[-1].tzinfo):
        return empty, {**unavailable, "reason": "antecedent hours are discontinuous or not yet available"}
    future_times = list(snapshot.get("times") or [])
    if not future_times:
        return empty, {**unavailable, "reason": "forecast has no future valid time"}
    first_future = datetime.fromisoformat(str(future_times[0]).replace("Z", "+00:00"))
    if first_future.tzinfo is None or (first_future - parsed[-1]).total_seconds() != 3600.0:
        return empty, {**unavailable, "reason": "antecedent and forecast axes are not contiguous"}

    boundary = ocean.build_boundary(
        times, {}, snapshot.get("antecedent_city") or []
    )
    spinup = state_model.DEFAULT_MODEL.simulate_ensemble(
        rainfall,
        tide_m=boundary["total_level_m"],
        initial_depth_mm=empty,
        n_members=n_members,
        seed=stable_seed(
            snapshot.get("forecast_run_id", "unknown"), MODEL_VERSION, "antecedent-spinup"
        ),
        thresholds_mm=PROBABILITY_THRESHOLDS_MM,
        sampled_parameters=sampled_parameters,
    )
    final_depth = np.asarray(spinup["members_depth_mm"], dtype=float)[:, -1, :]
    return final_depth, {
        "applied": True,
        "hours": len(times),
        "start": times[0],
        "end": times[-1],
        "source": snapshot.get("antecedent_provenance"),
        "interval_semantics": snapshot.get("antecedent_interval_semantics"),
        "state": "surface-water storage/depth only; no soil-moisture state",
        "mass_balance": spinup["audit"],
        "final_depth_p50_m": {
            did: _round(np.median(final_depth[:, index]) / 1000.0)
            for index, did in enumerate(state_model.DEFAULT_MODEL.district_ids)
        },
    }


def initial_analysis_for_snapshot(snapshot, n_members=ENSEMBLE_SIZE):
    """Build and observe a member-wise initial state without hard assignment.

    A point/station median is not assumed to equal a district-wide depth exactly.
    The observation operator is therefore accompanied by a deliberately broad
    0.10 m representativeness error and an explicit prior-state spread.  This is
    still an uncalibrated operator, but it is materially safer than replacing an
    entire district state with a single point value.
    """

    forecast_run_id = snapshot.get("forecast_run_id", "unknown")
    seed = stable_seed(forecast_run_id, MODEL_VERSION, CANONICAL_ENSEMBLE_SALT)
    samples = state_model.DEFAULT_MODEL.sample_parameters(
        n_members=int(n_members), seed=seed
    )
    prior, spinup = _antecedent_spinup(snapshot, samples, n_members)
    base_metadata = {
        "initial_state_source": (
            "antecedent-forcing physical spin-up" if spinup["applied"] else "zero-depth fallback"
        ),
        "antecedent_spinup": spinup,
    }
    issued_at = snapshot.get("issued_at")
    if not issued_at:
        return prior, {}, samples, {
            **base_metadata,
            "applied": False,
            "filter": None,
            "observed_districts": [],
            "analysis_cutoff": None,
            "reason": "forecast snapshot has no issued_at; observation assimilation disabled fail-closed",
            "observation_operator": "unavailable(missing forecast issuance audit time)",
        }
    analysis_cutoff_dt = datetime.fromisoformat(str(issued_at).replace("Z", "+00:00"))
    if analysis_cutoff_dt.tzinfo is None:
        raise ValueError("forecast snapshot issued_at must include a timezone")
    live = observations.latest_district_observations(
        now=analysis_cutoff_dt,
        available_before=analysis_cutoff_dt,
    )
    if not live:
        return prior, live, samples, {
            **base_metadata,
            "applied": False,
            "filter": None,
            "observed_districts": [],
            "analysis_cutoff": analysis_cutoff_dt.isoformat(),
            "reason": "no fresh district-mapped water-level observations",
            "observation_operator": "unavailable",
        }

    rng = np.random.default_rng(
        stable_seed(forecast_run_id, MODEL_VERSION, "initial-state-prior")
    )
    physical_spinup_prior = prior.copy()
    observations_mm = {}
    errors_mm = {}
    for did, item in sorted(live.items()):
        index = state_model.DEFAULT_MODEL.index[did]
        # Preserve the physical spin-up mean and add explicit structural state
        # uncertainty so a dry/low-spread prior can still be updated. This
        # spread is an information prior, not a physical rainfall flux.
        perturbation = rng.normal(loc=0.0, scale=50.0, size=int(n_members))
        perturbation -= float(np.mean(perturbation))
        prior[:, index] = np.maximum(0.0, prior[:, index] + perturbation)
        observations_mm[did] = float(item["depth_m"]) * 1000.0
        sensor_error_m = 0.03 / max(1.0, np.sqrt(float(item.get("station_count", 1))))
        errors_mm[did] = 1000.0 * float(
            np.hypot(INITIAL_REPRESENTATIVENESS_ERROR_M, sensor_error_m)
        )

    area_m2 = state_model.DEFAULT_MODEL.parameters["area_m2"]
    ponding_area = samples["ponding_fraction"] * area_m2[None, :]
    expanded_area = samples["expanded_ponding_fraction"] * area_m2[None, :]
    physical_spinup_storage = state_model.DEFAULT_MODEL.depth_to_storage(
        physical_spinup_prior, ponding_area, expanded_area
    )
    prior_storage = state_model.DEFAULT_MODEL.depth_to_storage(
        prior, ponding_area, expanded_area
    )
    structural_increment_by_member = np.sum(
        prior_storage - physical_spinup_storage, axis=1
    )
    update = state_model.DEFAULT_MODEL.assimilate_enkf(
        prior_storage,
        observations_mm,
        observation_error_mm=errors_mm,
        localization_radius_km=DEFAULT_INITIAL_LOCALIZATION_RADIUS_KM,
        seed=stable_seed(forecast_run_id, MODEL_VERSION, "initial-ensrf"),
        ponding_area_m2=ponding_area,
        expanded_ponding_area_m2=expanded_area,
    )
    ids = state_model.DEFAULT_MODEL.district_ids
    metadata = {
        **base_metadata,
        "applied": True,
        "filter": update["filter"],
        "observed_districts": list(update["observed_districts"]),
        "analysis_cutoff": analysis_cutoff_dt.isoformat(),
        "observation_error_m": {
            did: _round(errors_mm[did] / 1000.0, 4) for did in observations_mm
        },
        "prior_mean_depth_m": {
            did: _round(update["forecast_mean_depth_mm"][state_model.DEFAULT_MODEL.index[did]] / 1000.0)
            for did in observations_mm
        },
        "posterior_mean_depth_m": {
            did: _round(update["analysis_mean_depth_mm"][state_model.DEFAULT_MODEL.index[did]] / 1000.0)
            for did in observations_mm
        },
        "prior_std_depth_m": {
            did: _round(update["forecast_std_depth_mm"][state_model.DEFAULT_MODEL.index[did]] / 1000.0)
            for did in observations_mm
        },
        "posterior_std_depth_m": {
            did: _round(update["analysis_std_depth_mm"][state_model.DEFAULT_MODEL.index[did]] / 1000.0)
            for did in observations_mm
        },
        "assimilation_increment_mean_m3": _round(
            np.mean(update["ensemble_total_increment_m3"]), 2
        ),
        "structural_prior_increment_mean_m3": _round(
            np.mean(structural_increment_by_member), 2
        ),
        "structural_prior_increment_p10_m3": _round(
            np.quantile(structural_increment_by_member, 0.10), 2
        ),
        "structural_prior_increment_p90_m3": _round(
            np.quantile(structural_increment_by_member, 0.90), 2
        ),
        "total_nonphysical_initial_state_increment_mean_m3": _round(
            np.mean(
                structural_increment_by_member
                + np.asarray(update["ensemble_total_increment_m3"], dtype=float)
            ),
            2,
        ),
        "observation_operator": (
            "estimated(point/station district median -> representative district depth; "
            "0.10 m representativeness error; uncalibrated)"
        ),
        "mass_accounting_note": (
            "spin-up is a conservative physical rollout; structural prior spread and "
            "EnSRF analysis increments are separate non-physical state corrections. "
            + update["mass_accounting_note"]
        ),
        "prior_state_model_error_m": 0.05,
        "prior_state_spread_note": (
            "non-physical structural uncertainty added around spin-up prior at observed nodes; "
            "its volume increment and the observation-analysis increment are accounted separately"
        ),
        "district_ids": list(ids),
    }
    return update["analysis_depth_mm"], live, samples, metadata


def run_ensemble(
    rainfall_by_district,
    tide_m,
    *,
    forecast_run_id="manual",
    seed_salt=CANONICAL_ENSEMBLE_SALT,
    n_members=ENSEMBLE_SIZE,
    drainage_control=1.0,
    pump_efficiency=1.0,
    initial_depth_mm=None,
    sampled_parameters=None,
):
    seed = stable_seed(forecast_run_id, MODEL_VERSION, seed_salt)
    forcing_hash = _manifest_hash({
        "rainfall_by_district": rainfall_by_district,
        "tide_m": tide_m,
        "pump_efficiency": pump_efficiency,
        "drainage_control": drainage_control,
        "initial_depth_mm": {} if initial_depth_mm is None else initial_depth_mm,
    })
    result = state_model.DEFAULT_MODEL.simulate_ensemble(
        rainfall_by_district,
        tide_m=tide_m,
        pump_efficiency=pump_efficiency,
        drainage_control=drainage_control,
        initial_depth_mm=initial_depth_mm,
        n_members=int(n_members),
        seed=seed,
        thresholds_mm=PROBABILITY_THRESHOLDS_MM,
        sampled_parameters=sampled_parameters,
    )
    result["seed"] = seed
    result["forcing_hash"] = forcing_hash
    parameter_hash = _manifest_hash(result["sampled_parameters"])
    result["parameter_ensemble_id"] = _manifest_hash({
        "forecast_run_id": forecast_run_id,
        "model_version": MODEL_VERSION,
        "seed": seed,
        "members": int(n_members),
        "sampled_parameters_hash": parameter_hash,
    })
    result["model_run_id"] = model_run_id(
        forecast_run_id,
        seed,
        {
            "members": int(n_members),
            "seed_salt": seed_salt,
            "forcing_hash": forcing_hash,
            "parameter_ensemble_id": result["parameter_ensemble_id"],
        },
    )
    return result


def _driver(
    district,
    rain,
    tide_m,
    drainage,
    representative_depth_mm,
    runoff_depth_mm=0.0,
    routed_in_depth_mm=0.0,
):
    if float(representative_depth_mm) < 1.0:
        return "排水能力可覆盖当前产流"
    candidates = {
        "局地降雨产流": max(float(runoff_depth_mm), max(0.0, float(rain) - float(drainage))),
        "高潮位顶托排水": max(0.0, float(tide_m) - 0.35) * 35.0 * float(district.get("coastal", 0.0)),
        "低洼地形汇水": float(district.get("low_lying_ratio", 0.0)) * max(0.0, float(rain)),
        "区际地表汇流": max(0.0, float(routed_in_depth_mm)),
    }
    label, score = max(candidates.items(), key=lambda item: item[1])
    return label if score > 0 else "排水能力可覆盖当前产流"


def _series_for_district(district, index, times, rain, ensemble, tide):
    p10 = ensemble["depth_p10_mm"][:, index]
    p50 = ensemble["depth_p50_mm"][:, index]
    p90 = ensemble["depth_p90_mm"][:, index]
    probs = ensemble["exceedance_probability"]
    routed = ensemble["routed_in_depth_p50_mm"][:, index]
    runoff = ensemble["runoff_depth_p50_mm"][:, index]
    drainage = float(state_model.DEFAULT_MODEL.parameters["drainage_capacity_mm_h"][index])
    out = []
    for hour, time_value in enumerate(times):
        depth10_m = _round(p10[hour] / 1000.0, 4)
        depth50_m = _round(p50[hour] / 1000.0, 4)
        depth90_m = _round(p90[hour] / 1000.0, 4)
        threshold_prob = {
            "gt_0_05m": _round(probs[50.0][hour, index]),
            "gt_0_15m": _round(probs[150.0][hour, index]),
            "gt_0_30m": _round(probs[300.0][hour, index]),
            "gt_0_50m": _round(probs[500.0][hour, index]),
        }
        actionable_prob = threshold_prob["gt_0_15m"]
        level = level_from_depth(p50[hour])
        driver = _driver(
            district,
            rain[hour],
            tide[hour],
            drainage,
            p50[hour],
            runoff_depth_mm=runoff[hour],
            routed_in_depth_mm=routed[hour],
        )
        out.append({
            "hour_index": hour,
            "time": time_value,
            "prob": actionable_prob,
            "probability_definition": "P(representative water depth >= 0.15 m)",
            "level": level,
            "level_label": RISK_LEVELS[level],
            "driver": driver,
            "rainfall_mm_h": _round(rain[hour], 2),
            "depth_p10_m": depth10_m,
            "depth_p50_m": depth50_m,
            "depth_p90_m": depth90_m,
            "water_depth_m": {"p10": depth10_m, "p50": depth50_m, "p90": depth90_m},
            "threshold_prob": threshold_prob,
            # Compatibility projection for existing WAM charts.  It now points
            # to the same physical ensemble instead of a teacher-generated label.
            "surrogate": {
                "prob": actionable_prob,
                "depth_p50_m": depth50_m,
                "provenance": "estimated(conservative state-space ensemble; uncalibrated)",
            },
        })
    return out


def build_predict(snapshot, n_members=ENSEMBLE_SIZE):
    times = list(snapshot.get("times") or [])
    if not times:
        raise ValueError("forecast snapshot contains no future time steps")
    rainfall = {did: list(values) for did, values in snapshot["districts"].items()}
    ensemble, boundary, live_observations = ensemble_for_snapshot(
        snapshot, n_members=n_members
    )

    districts_out = []
    for idx, district in enumerate(shenzhen.DISTRICTS):
        did = district["id"]
        series = _series_for_district(
            district, idx, times, rainfall[did], ensemble, boundary["total_level_m"]
        )
        peak_index = select_peak_index(
            ensemble["depth_p50_mm"][:, idx],
            ensemble["exceedance_probability"][150.0][:, idx],
        )
        peak = series[peak_index]
        vulnerability, breakdown = district_vulnerability(district)
        districts_out.append({
            "id": did,
            "name": district["name"],
            "center": district["center"],
            "drainage": district["drainage_design"],
            "elevation": district["elevation_mean"],
            "historical_index": district["historical_flood_index"],
            "vulnerability": vulnerability,
            "vuln_breakdown": breakdown,
            "tag": district["tag"],
            "rainfall": [_round(x, 2) for x in rainfall[did]],
            "cum24": [_round(x, 2) for x in snapshot["cum"][did]],
            "series": series,
            "first_forecast": series[0],
            # Deprecated compatibility alias: this is the first future valid
            # time, not a current observation/analysis.
            "current": series[0],
            "peak": dict(peak),
            "peak_depth_m": peak["depth_p50_m"],
            "duration_above_0_15m_h": sum(item["depth_p50_m"] >= 0.15 for item in series),
            "initial_observation": live_observations.get(did),
        })

    alerts = []
    for district in districts_out:
        peak = district["peak"]
        if peak["level"] >= 3:
            alerts.append({
                "level": peak["level"],
                "level_label": peak["level_label"],
                "district": district["name"],
                "district_id": district["id"],
                "time": peak["time"],
                "driver": peak["driver"],
                "message": (
                    f"{district['name']} 预计 {peak['time']} 代表性积水中位深度约"
                    f" {peak['depth_p50_m']:.2f} m（P90 {peak['depth_p90_m']:.2f} m），"
                    f"主因：{peak['driver']}"
                ),
            })
    alerts.sort(key=lambda item: item["level"], reverse=True)

    current_max = max(d["current"]["level"] for d in districts_out)
    peak_district = max(districts_out, key=lambda d: d["peak"]["depth_p50_m"])
    high_now = [d["name"] for d in districts_out if d["current"]["level"] >= 3]
    overview = {
        "first_forecast_risk_level": current_max,
        "first_forecast_risk_label": RISK_LEVELS[current_max],
        "first_forecast_risk_prob": max(d["current"]["prob"] for d in districts_out),
        "first_forecast_max_depth_m": max(d["current"]["depth_p50_m"] for d in districts_out),
        "high_risk_first_forecast": high_now,
        "high_risk_first_forecast_count": len(high_now),
        # Deprecated aliases retained for the previous frontend contract.
        "current_risk_level": current_max,
        "current_risk_label": RISK_LEVELS[current_max],
        "current_risk_prob": max(d["current"]["prob"] for d in districts_out),
        "current_max_depth_m": max(d["current"]["depth_p50_m"] for d in districts_out),
        "high_risk_now": high_now,
        "high_risk_now_count": len(high_now),
        "peak_hour_index": peak_district["peak"]["hour_index"],
        "peak_time": peak_district["peak"]["time"],
        "peak_risk_level": peak_district["peak"]["level"],
        "peak_risk_label": peak_district["peak"]["level_label"],
        "peak_depth_m": peak_district["peak"]["depth_p50_m"],
        "alerts": alerts,
        "alert_count": len(alerts),
    }

    fallback = bool(snapshot.get("fallback"))
    readiness = observations.data_readiness()
    spinup = ensemble["initial_analysis"]["antecedent_spinup"]
    quality_flags = ["uncalibrated_parameters", "district_scale_not_street_depth"]
    if fallback:
        quality_flags.append("synthetic_rainfall_fallback")
    if not live_observations:
        quality_flags.append("no_fresh_water_level_assimilation")
    if not spinup["applied"]:
        quality_flags.append("no_complete_antecedent_spinup")
    elif fallback:
        quality_flags.append("synthetic_antecedent_spinup")
    return {
        # A pinned forecast is a reproducible product.  Use the forcing-freeze
        # timestamp rather than response wall clock so replay is byte-stable.
        "generated_at": snapshot.get("snapshot_created_at") or snapshot.get("issued_at"),
        "forecast_run_id": snapshot.get("forecast_run_id"),
        "model_run_id": ensemble["model_run_id"],
        "analysis_time": ensemble["initial_analysis"].get("analysis_cutoff") or snapshot.get("issued_at"),
        "forcing_issued_at": snapshot.get("issued_at"),
        "forcing_selection_as_of": snapshot.get("forcing_selection_as_of"),
        "forcing_issued_at_semantics": snapshot.get("issued_at_semantics"),
        "provider_forecast_issued_at": snapshot.get("provider_forecast_issued_at"),
        "first_valid_time": times[0],
        "time_semantics": "series[0] is the first future hourly valid time, not current observed state",
        "city": shenzhen.CITY,
        "forecast_days": max(1, int(np.ceil(len(times) / 24))),
        "step_minutes": 60,
        "scale": "district·hourly ensemble",
        "simulated": False,
        "data_source": "fallback-sample" if fallback else "open-meteo-multi-point",
        "drainage_avg": _round(shenzhen.DRAINAGE_AVG, 2),
        "hours": times,
        "rainfall": [_round(x, 2) for x in snapshot.get("city", [])],
        "districts": districts_out,
        "overview": overview,
        "ocean": boundary,
        "observations": {
            "fresh_districts": live_observations,
            "initialized_from_proxy": False,
            "initialized_from_antecedent_forcing": bool(spinup["applied"]),
            "assimilated": bool(ensemble["initial_analysis"]["applied"]),
            "initial_analysis": ensemble["initial_analysis"],
            "stale_data_not_assimilated": not bool(live_observations),
        },
        "data_readiness": readiness,
        "quality_flags": quality_flags,
        "model": {
            "name": MODEL_NAME,
            "version": MODEL_VERSION,
            "family": "conservative graph state-space + parameter ensemble + localized EnSRF",
            "state": "surface-water storage (m3); representative depth (m)",
            "members": int(ensemble["n_members"]),
            "thresholds_m": [x / 1000.0 for x in PROBABILITY_THRESHOLDS_MM],
            "probability_definition": "empirical ensemble exceedance; not yet observation-calibrated",
            "mass_balance": ensemble["audit"],
            "levels": RISK_LEVELS,
            "notes": (
                "降雨产流、排水、河道/边界外排、潮位顶托与DEM下坡区际汇流共同推进有量纲水量状态；"
                "完整可用时用前24个已结束小时的降雨做地表存水spin-up，再进行一次起报观测更新；"
                "集合扰动给出P10/P50/P90和超阈概率。当前事件观测不足，结果用于规划推演，"
                "不能宣称已达到业务化预报精度。"
            ),
        },
        "hazard_model": {
            "name": MODEL_NAME,
            "equation": "S(t+1)=S(t)+runoff+routed_in-routed_out-drainage-external_outflow; depth=two-stage inverse storage curve",
            "provenance": state_model.PARAMETER_PROVENANCE,
            "note": "全部区际通量由同一时刻状态同步计算，并逐步记录质量账本。",
        },
        "provenance": {
            "rainfall_forecast": "simulated(fallback storm)" if fallback else "predicted(Open-Meteo)",
            "antecedent_surface_state": spinup.get("source") if spinup["applied"] else "unavailable(zero-depth fallback)",
            "water_level_initial_state": "observed(fresh only)" if live_observations else "unavailable(stale cache excluded)",
            "dem_landcover_roads": "observed-derived(project local GIS assets)",
            "routing_and_hydraulic_parameters": "estimated/assumed; exposed for calibration",
            "risk_probability": "estimated(parameter ensemble exceedance; uncalibrated)",
        },
    }


def peak_depth_by_district(snapshot, n_members=ENSEMBLE_SIZE):
    """Small shared helper for accessibility and downstream impact models."""
    ensemble, _, _ = ensemble_for_snapshot(snapshot, n_members=n_members)
    return {
        did: float(np.max(ensemble["depth_p50_mm"][:, index]))
        for index, did in enumerate(ensemble["district_ids"])
    }


def ensemble_for_snapshot(
    snapshot, n_members=ENSEMBLE_SIZE, seed_salt=CANONICAL_ENSEMBLE_SALT
):
    """Expose one immutable-in-practice canonical ensemble per snapshot.

    The first consumer freezes both the fresh-observation cutoff and parameter
    members on the archived snapshot object.  Predict, simulate, street and grid
    products therefore cannot silently acquire different initial states while
    claiming the same forcing snapshot.
    """
    times = list(snapshot.get("times") or [])
    if not times:
        raise ValueError("forecast snapshot contains no future time steps")
    if seed_salt != CANONICAL_ENSEMBLE_SALT:
        raise ValueError("online products must use the canonical parameter ensemble")
    global _NEXT_SNAPSHOT_CACHE_TOKEN
    with _ENSEMBLE_LOCK:
        # Keep only a tiny scalar token on the archived forcing.  Storing the
        # full NumPy ensemble inside every one of the 32 archived snapshots can
        # retain hundreds of MB after a sequence of long-horizon requests.
        snapshot_token = snapshot.get("_canonical_cache_token")
        if snapshot_token is None:
            _NEXT_SNAPSHOT_CACHE_TOKEN += 1
            snapshot_token = _NEXT_SNAPSHOT_CACHE_TOKEN
            snapshot["_canonical_cache_token"] = snapshot_token
        cache_key = (
            int(snapshot_token), MODEL_VERSION, int(n_members), str(seed_salt)
        )
        cached = _CANONICAL_ENSEMBLE_CACHE.get(cache_key)
        if cached is not None:
            _CANONICAL_ENSEMBLE_CACHE.move_to_end(cache_key)
            return cached
        boundary = ocean.build_boundary(times, {}, snapshot.get("city") or [])
        initial_members, observations_used, parameter_samples, initial_analysis = (
            initial_analysis_for_snapshot(snapshot, n_members=n_members)
        )
        ensemble = run_ensemble(
            snapshot["districts"],
            boundary["total_level_m"],
            forecast_run_id=snapshot.get("forecast_run_id", "unknown"),
            seed_salt=seed_salt,
            n_members=n_members,
            initial_depth_mm=initial_members,
            sampled_parameters=parameter_samples,
        )
        ensemble["initial_analysis"] = initial_analysis
        result = (ensemble, boundary, observations_used)
        _CANONICAL_ENSEMBLE_CACHE[cache_key] = result
        _CANONICAL_ENSEMBLE_CACHE.move_to_end(cache_key)
        while len(_CANONICAL_ENSEMBLE_CACHE) > MAX_CANONICAL_ENSEMBLE_CACHE:
            _CANONICAL_ENSEMBLE_CACHE.popitem(last=False)
        return result


__all__ = [
    "MODEL_NAME",
    "MODEL_VERSION",
    "ENSEMBLE_SIZE",
    "MAX_CANONICAL_ENSEMBLE_CACHE",
    "CANONICAL_ENSEMBLE_SALT",
    "PROBABILITY_THRESHOLDS_MM",
    "stable_seed",
    "model_run_id",
    "fresh_initial_depth_mm",
    "initial_analysis_for_snapshot",
    "run_ensemble",
    "build_predict",
    "peak_depth_by_district",
    "ensemble_for_snapshot",
]
