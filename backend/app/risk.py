# -*- coding: utf-8 -*-
"""Shared, unit-aware risk projection helpers.

The forecasting core predicts water depth in millimetres.  Product-facing risk
levels are a documented projection of that physical quantity; they are not a
second learned model and must not be presented as calibrated probabilities.
"""
from __future__ import annotations

import numpy as np


RISK_LEVELS = ["无", "低", "中", "高", "极高"]
DEPTH_LEVEL_THRESHOLDS_MM = (50.0, 150.0, 300.0, 500.0)
ACTIONABLE_DEPTH_MM = 150.0


def level_from_depth(depth_mm: float) -> int:
    """Map median representative depth to the five existing UI levels."""
    value = max(0.0, float(depth_mm))
    return int(sum(value >= threshold for threshold in DEPTH_LEVEL_THRESHOLDS_MM))


def level_label(depth_mm: float) -> str:
    return RISK_LEVELS[level_from_depth(depth_mm)]


def exceedance_probability(member_depth_mm, threshold_mm=ACTIONABLE_DEPTH_MM):
    """Empirical ensemble probability of exceeding a physical depth threshold."""
    values = np.asarray(member_depth_mm, dtype=float)
    if values.ndim < 1:
        raise ValueError("member_depth_mm must include an ensemble dimension")
    return np.mean(values >= float(threshold_mm), axis=0)


def district_vulnerability(district):
    """Static exposure index retained for explanation, not used as a label."""
    elevation = float(district.get("elevation_mean", 30.0))
    elevation_term = 1.0 / (1.0 + np.exp((elevation - 40.0) / 25.0))
    breakdown = {
        "low_lying": round(float(district.get("low_lying_ratio", 0.3)), 3),
        "impervious": round(float(district.get("impervious_ratio", 0.4)), 3),
        "elevation": round(float(elevation_term), 3),
        "historical": round(float(district.get("historical_flood_index", 0.0)), 3),
        "coastal": round(float(district.get("coastal", 0.0)), 3),
    }
    value = (
        0.30 * breakdown["low_lying"]
        + 0.20 * breakdown["impervious"]
        + 0.15 * breakdown["elevation"]
        + 0.20 * breakdown["historical"]
        + 0.15 * breakdown["coastal"]
    )
    return round(float(np.clip(value, 0.0, 1.0)), 3), breakdown


def bounded_local_depth_factor(elevation_m, impervious_ratio, district):
    """GIS-informed but deliberately bounded district-to-local downscaling.

    This is not a 2-D hydraulic solver.  It only ranks local cells within the
    district ensemble using relative elevation and imperviousness, capped to
    prevent unsupported street-level precision.
    """
    district_elevation = float(district.get("elevation_mean", 30.0))
    district_impervious = float(district.get("impervious_ratio", 0.4))
    elevation_term = np.exp(np.clip((district_elevation - float(elevation_m)) / 80.0, -0.45, 0.45))
    impervious_term = 1.0 + 0.55 * (float(impervious_ratio) - district_impervious)
    return float(np.clip(elevation_term * impervious_term, 0.60, 1.65))


__all__ = [
    "RISK_LEVELS",
    "DEPTH_LEVEL_THRESHOLDS_MM",
    "ACTIONABLE_DEPTH_MM",
    "level_from_depth",
    "level_label",
    "exceedance_probability",
    "district_vulnerability",
    "bounded_local_depth_factor",
]
