# -*- coding: utf-8 -*-
"""Localized ensemble Kalman assimilation for observed flood-water depth."""
from __future__ import annotations

from datetime import datetime, timedelta
import numpy as np

from . import forecasting, shenzhen, state_model


DEFAULT_OBSERVATION_ERROR_M = 0.10
DEFAULT_LOCALIZATION_RADIUS_KM = 25.0


def _validate(district_id, observed_depth_m, at_hour, time_steps):
    if shenzhen.get_district(district_id) is None:
        raise ValueError(f"未知行政区: {district_id}")
    observed = float(observed_depth_m)
    if not np.isfinite(observed) or observed < 0.0 or observed > 5.0:
        raise ValueError("observed_h 必须是 0..5 m 的有限水深")
    hour = int(at_hour)
    if hour < 0 or hour >= int(time_steps):
        raise ValueError(f"at_hour 必须位于 0..{max(0, time_steps - 1)}")
    return observed, hour


def _continue_members(ensemble, analysis_depth_mm, rainfall, tide, at_hour):
    """Roll every analysis member forward with its original parameters."""
    corrected = np.asarray(ensemble["members_depth_mm"], dtype=float).copy()
    corrected[:, at_hour, :] = analysis_depth_mm
    if at_hour >= corrected.shape[1] - 1:
        return corrected

    ids = tuple(ensemble["district_ids"])
    future_rain = {did: list(rainfall[did][at_hour + 1 :]) for did in ids}
    future_tide = list(tide[at_hour + 1 :])
    sampled = ensemble["sampled_parameters"]
    for member in range(corrected.shape[0]):
        overrides = {key: values[member] for key, values in sampled.items()}
        rollout = state_model.DEFAULT_MODEL.simulate(
            future_rain,
            tide_m=future_tide,
            initial_depth_mm=analysis_depth_mm[member],
            parameter_overrides=overrides,
        )
        corrected[member, at_hour + 1 :, :] = rollout["depth_mm"]
    return corrected


def assimilate_snapshot(
    snapshot,
    district_id,
    observed_depth_m,
    at_hour=6,
    *,
    observation_error_m=DEFAULT_OBSERVATION_ERROR_M,
    n_members=forecasting.ENSEMBLE_SIZE,
    observation_source="user-supplied",
    observation_timestamp=None,
    observation_quality="provided",
):
    """Assimilate a metre-valued observation into a forecast snapshot.

    Forecast/analysis states are updated in volume space, covariance is computed
    in depth space, and each analysis member is then propagated by the same
    conservative transition used by `/predict` and `/simulate`.
    """
    times = list(snapshot.get("times") or [])
    if not times:
        raise ValueError("forecast snapshot contains no future time steps")
    observed_m, hour = _validate(district_id, observed_depth_m, at_hour, len(times))
    error_m = float(observation_error_m)
    if not np.isfinite(error_m) or error_m <= 0.0:
        raise ValueError("observation_error_m must be finite and positive")

    ensemble, boundary, _ = forecasting.ensemble_for_snapshot(
        snapshot, n_members=n_members
    )
    district_index = ensemble["district_ids"].index(district_id)
    ponding_area = ensemble["members_ponding_area_m2"]
    expanded_ponding_area = ensemble["members_expanded_ponding_area_m2"]
    forecast_depth = np.asarray(ensemble["members_depth_mm"][:, hour, :], dtype=float)

    # Pure parameter ensembles can collapse to exactly zero during dry steps.
    # Represent initial/state uncertainty explicitly so a real non-zero sensor
    # observation can still update the state; this spread is not a physical flux.
    rng = np.random.default_rng(
        forecasting.stable_seed(snapshot.get("forecast_run_id"), district_id, hour, "state-spread")
    )
    state_spread_mm = np.maximum(15.0, 0.20 * np.maximum(forecast_depth.mean(axis=0), 1.0))
    inflated_depth = np.maximum(
        0.0,
        forecast_depth + rng.normal(0.0, state_spread_mm, size=forecast_depth.shape),
    )
    forecast_storage = state_model.DEFAULT_MODEL.depth_to_storage(
        inflated_depth, ponding_area, expanded_ponding_area
    )
    analysis = state_model.DEFAULT_MODEL.assimilate_enkf(
        forecast_storage,
        {district_id: observed_m * 1000.0},
        observation_error_mm=error_m * 1000.0,
        localization_radius_km=DEFAULT_LOCALIZATION_RADIUS_KM,
        seed=forecasting.stable_seed(snapshot.get("forecast_run_id"), district_id, hour, "enkf"),
        ponding_area_m2=ponding_area,
        expanded_ponding_area_m2=expanded_ponding_area,
    )
    corrected_members = _continue_members(
        ensemble,
        analysis["analysis_depth_mm"],
        snapshot["districts"],
        boundary["total_level_m"],
        hour,
    )

    raw_members = np.asarray(ensemble["members_depth_mm"][:, :, district_index], dtype=float)
    corrected_district = corrected_members[:, :, district_index]
    raw_risk = np.mean(raw_members >= 150.0, axis=0)
    corrected_risk = np.mean(corrected_district >= 150.0, axis=0)
    raw_p10, raw_p50, raw_p90 = np.quantile(raw_members, (0.1, 0.5, 0.9), axis=0) / 1000.0
    corr_p10, corr_p50, corr_p90 = np.quantile(corrected_district, (0.1, 0.5, 0.9), axis=0) / 1000.0

    prior_values = analysis["forecast_depth_mm"][:, district_index] / 1000.0
    posterior_values = analysis["analysis_depth_mm"][:, district_index] / 1000.0
    residual = observed_m - float(prior_values.mean())
    gain = float(analysis["kalman_gain"][district_index, 0])
    return {
        "district_id": district_id,
        "at_hour": hour,
        "at_time": times[hour],
        "forecast_run_id": snapshot.get("forecast_run_id"),
        "model_run_id": ensemble["model_run_id"],
        # Legacy names retained, now explicitly in metres rather than a
        # dimensionless hazard proxy.
        "raw_h": [round(float(x), 4) for x in raw_p50],
        "corrected_h": [round(float(x), 4) for x in corr_p50],
        "raw_risk": [round(float(x), 4) for x in raw_risk],
        "corrected_risk": [round(float(x), 4) for x in corrected_risk],
        "raw_depth_p10_m": [round(float(x), 4) for x in raw_p10],
        "raw_depth_p50_m": [round(float(x), 4) for x in raw_p50],
        "raw_depth_p90_m": [round(float(x), 4) for x in raw_p90],
        "corrected_depth_p10_m": [round(float(x), 4) for x in corr_p10],
        "corrected_depth_p50_m": [round(float(x), 4) for x in corr_p50],
        "corrected_depth_p90_m": [round(float(x), 4) for x in corr_p90],
        "prior_mean_depth_m": round(float(prior_values.mean()), 4),
        "posterior_mean_depth_m": round(float(posterior_values.mean()), 4),
        # Deprecated aliases retained for clients that predate the explicit
        # mean/P50 distinction.  They are means, not quantiles.
        "prior_depth_m": round(float(prior_values.mean()), 4),
        "posterior_depth_m": round(float(posterior_values.mean()), 4),
        "prior_std_m": round(float(prior_values.std(ddof=1)), 4),
        "posterior_std_m": round(float(posterior_values.std(ddof=1)), 4),
        "residual": round(float(residual), 4),
        "residual_unit": "m",
        "gain": round(gain, 4),
        "observation": {
            "value": round(observed_m, 4),
            "unit": "m",
            "error_std_m": round(error_m, 4),
            "source": observation_source,
            "timestamp": observation_timestamp or times[hour],
            "quality": observation_quality,
        },
        "state_spread_assumption_m": [round(float(x / 1000.0), 4) for x in state_spread_mm],
        "provenance": "estimated(deterministic localized EnSRF volume-state correction from metre-valued observation)",
        "mass_accounting_note": analysis["mass_accounting_note"],
        "note": "同化增量单独记账，不伪装成降雨、排水或区际通量。",
    }


def assimilate_at(district_id, rseq, observed_value, at_hour, K=None, C=None):
    """Compatibility wrapper for callers that only supply one rainfall series."""
    rain = [max(0.0, float(value)) for value in rseq]
    snapshot = {
        "times": [
            (datetime(2000, 1, 1) + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M")
            for index in range(len(rain))
        ],
        "city": list(rain),
        "districts": {
            district["id"]: list(rain) if district["id"] == district_id else [0.0] * len(rain)
            for district in shenzhen.DISTRICTS
        },
        "forecast_run_id": "compat-assimilation",
    }
    return assimilate_snapshot(snapshot, district_id, observed_value, at_hour)


__all__ = ["assimilate_snapshot", "assimilate_at"]
