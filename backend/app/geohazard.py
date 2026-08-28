# -*- coding: utf-8 -*-
"""Soil-memory runoff coupling and landslide/debris-flow trigger belief state."""
from __future__ import annotations

from typing import Mapping
import numpy as np


class GeoHazardModel:
    def simulate(self, rainfall_mm_h, *, slope_deg, soil_saturation=0.35,
                 geology_vulnerability=0.5, impervious_ratio=0.3, vegetation_fraction=0.5,
                 dt_hours=1.0):
        rain = np.asarray(rainfall_mm_h, dtype=float)
        if rain.ndim != 1 or not len(rain) or np.any(~np.isfinite(rain)) or np.any(rain < 0):
            raise ValueError("rainfall_mm_h must be a finite non-negative series")
        finite = [slope_deg, soil_saturation, geology_vulnerability, impervious_ratio, vegetation_fraction]
        if any(not np.isfinite(float(v)) for v in finite):
            raise ValueError("geohazard parameters must be finite")
        if not 0 <= soil_saturation <= 1 or not 0 <= geology_vulnerability <= 1:
            raise ValueError("soil_saturation and geology_vulnerability must be in [0,1]")
        if not 0 <= impervious_ratio <= 1 or not 0 <= vegetation_fraction <= 1 or not 0 <= slope_deg <= 90:
            raise ValueError("surface fractions and slope are outside physical bounds")
        saturation = np.zeros(len(rain)); runoff_coefficient = np.zeros(len(rain))
        trigger_intensity = np.zeros(len(rain)); trigger_probability = np.zeros(len(rain))
        s = float(soil_saturation); p_survival = 1.0; rolling = []
        for t, value in enumerate(rain):
            infiltration_capacity = 12.0 * (1.0 - s) * (0.5 + 0.5 * vegetation_fraction)
            infiltrated = min(float(value), infiltration_capacity)
            drainage = 0.025 * s
            s = float(np.clip(s + infiltrated / 180.0 - drainage, 0.0, 1.0))
            saturation[t] = s
            z = -1.5 + 2.6 * impervious_ratio + 2.2 * s + 0.025 * slope_deg
            runoff_coefficient[t] = float(np.clip(1.0 / (1.0 + np.exp(-z)), 0.05, 0.98))
            rolling.append(float(value)); rolling = rolling[-24:]
            antecedent = sum(rolling)
            terrain = (slope_deg / 45.0) ** 1.5 * geology_vulnerability * (1.2 - 0.5 * vegetation_fraction)
            intensity = max(0.0, terrain * (0.018 * value + 0.0025 * antecedent) * s - 0.18)
            trigger_intensity[t] = intensity
            step_probability = 1.0 - np.exp(-intensity * dt_hours)
            p_survival *= 1.0 - step_probability
            trigger_probability[t] = 1.0 - p_survival
        return {"soil_saturation": saturation, "runoff_coefficient": runoff_coefficient,
                "trigger_intensity_h": trigger_intensity,
                "trigger_probability": trigger_probability,
                "probability_semantics": "uncalibrated cumulative model-belief; not observed frequency",
                "state": "soil saturation + landslide/debris-flow trigger belief"}


DEFAULT_MODEL = GeoHazardModel()

