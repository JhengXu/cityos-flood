# -*- coding: utf-8 -*-
"""Unified typhoon forcing and multi-hazard orchestration."""
from __future__ import annotations

from typing import Mapping, Sequence
import numpy as np

from . import coastal, geohazard, ocean, river, shenzhen, state_model


def forcing_from_track(times: Sequence[str], track: Sequence[Mapping], district_centers=None):
    """Convert an auditable hourly track into rain, wind, pressure and surge forcing."""
    if len(times) != len(track) or not times:
        raise ValueError("times and track must have the same non-empty hourly horizon")
    centers = district_centers or {d["id"]: d["center"] for d in shenzhen.DISTRICTS}
    rainfall = {did: [] for did in centers}; wind = {did: [] for did in centers}
    pressure = []; surge = []
    for point in track:
        required = ("latitude", "longitude", "max_wind_m_s", "central_pressure_hpa", "rain_rate_mm_h")
        if any(k not in point or not np.isfinite(float(point[k])) for k in required):
            raise ValueError("each track point requires finite position, wind, pressure and rain rate")
        lat, lon = float(point["latitude"]), float(point["longitude"])
        vmax = max(0.0, float(point["max_wind_m_s"])); base_rain = max(0.0, float(point["rain_rate_mm_h"]))
        pressure.append(float(point["central_pressure_hpa"]))
        # Pressure deficit plus onshore-wind proxy; explicitly a forecast forcing prior.
        surge.append(max(0.0, (1010.0 - pressure[-1]) * 0.01 + vmax * vmax * 0.00035))
        for did, center in centers.items():
            dist = 111.0 * np.hypot(float(center[0]) - lat, (float(center[1]) - lon) * np.cos(np.radians(lat)))
            attenuation = np.exp(-dist / 140.0)
            rainfall[did].append(base_rain * attenuation)
            wind[did].append(vmax * np.exp(-dist / 220.0))
    return {"times": list(times), "rainfall_mm_h": rainfall, "wind_m_s": wind,
            "central_pressure_hpa": pressure, "storm_surge_m": surge,
            "provenance": "track-derived parametric forcing; preserve source track metadata"}


def wind_damage_state(wind_m_s):
    wind = np.asarray(wind_m_s, dtype=float)
    tree = 1.0 / (1.0 + np.exp(-(wind - 25.0) / 4.0))
    facade = 1.0 / (1.0 + np.exp(-(wind - 38.0) / 5.0))
    return {"tree_failure_probability": tree, "facade_damage_probability": facade,
            "probability_semantics": "uncalibrated fragility prior"}


def simulate(times, track, *, river_rainfall=None, upstream_inflow_m3_s=0.0,
             terrain_by_district=None, mean_sea_level_m=0.0):
    forcing = forcing_from_track(times, track)
    astronomical = ocean.build_boundary(times, {"mean_sea_level_m": mean_sea_level_m, "surge_peak_m": 0.0})
    boundary = dict(astronomical)
    boundary["storm_surge_m"] = list(forcing["storm_surge_m"])
    boundary["total_level_m"] = (np.asarray(astronomical["astronomical_tide_m"]) + np.asarray(forcing["storm_surge_m"])).tolist()
    coast = coastal.DEFAULT_MODEL.simulate(forcing["rainfall_mm_h"], boundary)
    # WorldCover impervious fractions are loaded through the existing GIS
    # pipeline. Slope/geology remain explicit priors until authoritative layers
    # are added; keeping their provenance separate avoids calling them observed.
    index = state_model.DEFAULT_MODEL.index
    terrain = terrain_by_district or {
        "longgang": {"slope_deg": 18.0, "geology_vulnerability": 0.55,
                     "impervious_ratio": float(state_model.DEFAULT_MODEL.parameters["impervious_ratio"][index["longgang"]])},
        "pingshan": {"slope_deg": 22.0, "geology_vulnerability": 0.62,
                     "impervious_ratio": float(state_model.DEFAULT_MODEL.parameters["impervious_ratio"][index["pingshan"]])},
        "dapeng": {"slope_deg": 28.0, "geology_vulnerability": 0.68,
                   "impervious_ratio": float(state_model.DEFAULT_MODEL.parameters["impervious_ratio"][index["dapeng"]])},
    }
    geology = {did: geohazard.DEFAULT_MODEL.simulate(forcing["rainfall_mm_h"][did], **cfg)
               for did, cfg in terrain.items()}
    winds = {did: wind_damage_state(values) for did, values in forcing["wind_m_s"].items()}
    river_input = river_rainfall
    if river_input is None:
        city = np.mean(np.asarray(list(forcing["rainfall_mm_h"].values())), axis=0)
        river_input = {rid: city for rid in river.DEFAULT_MODEL.ids}
    rivers = river.DEFAULT_MODEL.simulate(river_input, upstream_inflow_m3_s)
    return {"forcing": forcing, "coastal_pluvial": coast, "river": rivers,
            "geohazard": geology, "wind_damage": winds,
            "coupling": "shared typhoon forcing; explicit domain states and exchange boundaries",
            "warning": "screening world model; hazard probabilities require event calibration"}
