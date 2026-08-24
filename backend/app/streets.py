# -*- coding: utf-8 -*-
"""Street-sample downscaling of the district physical ensemble.

This is deliberately a bounded GIS ranking layer, not street-scale hydraulics.
It retains district water volume dynamics and adjusts representative depth using
local DEM elevation and WorldCover imperviousness.
"""
from __future__ import annotations

import json
from pathlib import Path
import time

import numpy as np

from . import forecasting, shenzhen, weather
from .risk import bounded_local_depth_factor, district_vulnerability


STREET_FEATURES = Path(__file__).resolve().parent.parent / "data" / "street_features.json"
_CACHE = {}


def _load_street_features():
    if not STREET_FEATURES.exists():
        return {}
    rows = json.loads(STREET_FEATURES.read_text(encoding="utf-8"))
    return {row["name"]: row for row in rows}


def _street_vulnerability(feature, district):
    base, _ = district_vulnerability(district)
    factor = bounded_local_depth_factor(
        feature.get("elevation", district["elevation_mean"]),
        feature.get("impervious", district.get("impervious_ratio", 0.4)),
        district,
    )
    return float(np.clip(base * factor, 0.0, 1.0))


def build_street_risk(
    forecast_days=3, n_members=forecasting.ENSEMBLE_SIZE, snapshot=None
):
    snapshot = snapshot or weather.forecast_snapshot(forecast_days)
    ensemble, _, observations_used = forecasting.ensemble_for_snapshot(
        snapshot, n_members=n_members
    )
    members = np.asarray(ensemble["members_depth_mm"], dtype=float)
    ids = list(ensemble["district_ids"])
    features = _load_street_features()
    out = []
    for name, district_id, lat, lon in shenzhen.SUBDISTRICT_POINTS:
        district = shenzhen.get_district(district_id)
        if district is None:
            continue
        feature = features.get(name, {})
        elevation = float(feature.get("elevation", district["elevation_mean"]))
        impervious = float(feature.get("impervious", district.get("impervious_ratio", 0.4)))
        factor = bounded_local_depth_factor(elevation, impervious, district)
        local = members[:, :, ids.index(district_id)] * factor
        p10, p50, p90 = np.quantile(local, (0.1, 0.5, 0.9), axis=0) / 1000.0
        probability = np.mean(local >= 150.0, axis=0)
        any_time_probability = float(np.mean(np.max(local, axis=1) >= 150.0))
        peak_hour = forecasting.select_peak_index(p50, probability)
        out.append({
            "name": name,
            "district_id": district_id,
            "lat": lat,
            "lon": lon,
            "vulnerability": round(_street_vulnerability(feature, district), 3),
            "impervious": round(impervious, 3),
            "elevation": round(elevation, 1),
            "downscale_factor": round(factor, 3),
            "risk": [round(float(value), 4) for value in probability],
            "peak": round(any_time_probability, 4),
            "peak_probability_definition": "P(max over displayed horizon depth >= 0.15 m)",
            "peak_hour": peak_hour,
            "peak_depth_p10_m": round(float(p10[peak_hour]), 4),
            "peak_depth_p50_m": round(float(p50[peak_hour]), 4),
            "peak_depth_p90_m": round(float(p90[peak_hour]), 4),
            "depth_p50_m": [round(float(value), 4) for value in p50],
        })
    out.sort(key=lambda item: (item["peak_depth_p50_m"], item["peak"]), reverse=True)
    flags = ["bounded_gis_downscale", "not_street_hydraulics", "uncalibrated_parameters"]
    if snapshot.get("fallback"):
        flags.append("synthetic_rainfall_fallback")
    return {
        "source": "fallback-sample" if snapshot.get("fallback") else "open-meteo-multi-point",
        "forecast_run_id": snapshot.get("forecast_run_id"),
        "forecast_days": max(1, int(np.ceil(len(snapshot["times"]) / 24.0))),
        "model_run_id": ensemble["model_run_id"],
        "model": "district conservative ensemble + bounded local GIS depth factor",
        "probability_definition": "P(representative local depth >= 0.15 m)",
        "times": snapshot["times"],
        "n_streets": len(out),
        "streets": out,
        "initial_observations": observations_used,
        "quality_flags": flags,
        "provenance": {
            "district_dynamics": "estimated(conservative ensemble state-space)",
            "elevation_impervious": "observed-derived(project local DEM/WorldCover)",
            "local_downscale": "estimated(bounded ranking factor 0.60..1.65)",
        },
    }


def get_street_risk(forecast_days=3, snapshot=None):
    days = int(forecast_days)
    key = (snapshot.get("forecast_run_id") if snapshot else None, days)
    cached = _CACHE.get(key)
    if cached and time.time() - cached["ts"] < 300:
        return cached["data"]
    data = build_street_risk(days, snapshot=snapshot)
    _CACHE[key] = {"ts": time.time(), "data": data}
    while len(_CACHE) > 16:
        _CACHE.pop(next(iter(_CACHE)))
    return data


__all__ = ["build_street_risk", "get_street_risk"]
