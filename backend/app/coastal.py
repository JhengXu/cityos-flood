# -*- coding: utf-8 -*-
"""Conservative coastal inundation model driven by observed/forecast sea level.

Marine water is accounted separately from rainfall water.  The model is a
district-scale screening model: crest levels and hydraulic widths are explicit
priors and must be replaced by surveyed defence/outfall geometry for operations.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
import numpy as np

from . import ocean_data, state_model


DEFAULT_COASTAL_GEOMETRY = {
    "futian": {"crest_m": 1.55, "width_m": 90.0, "return_rate_h": 0.10},
    "nanshan": {"crest_m": 1.45, "width_m": 130.0, "return_rate_h": 0.11},
    "baoan": {"crest_m": 1.35, "width_m": 150.0, "return_rate_h": 0.09},
    "yantian": {"crest_m": 1.65, "width_m": 70.0, "return_rate_h": 0.14},
    "dapeng": {"crest_m": 1.40, "width_m": 110.0, "return_rate_h": 0.12},
}


def boundary_from_levels(
    times: Sequence[str],
    observed_level_m: Sequence[float],
    *,
    predicted_tide_m: Sequence[float] | None = None,
    surge_residual_m: Sequence[float] | None = None,
    station_id: str,
    datum: str,
    source: str,
    available_at: str,
) -> dict[str, Any]:
    """Build an auditable real-data boundary without silently filling gaps."""
    level = np.asarray(observed_level_m, dtype=float)
    if len(times) == 0 or level.shape != (len(times),):
        raise ValueError("times and observed_level_m must be non-empty and equal length")
    if np.any(~np.isfinite(level)):
        raise ValueError("observed sea levels must be finite; missing values require explicit QC")
    if np.any((level < -5.0) | (level > 8.0)):
        raise ValueError("observed sea levels must be within the QC range -5..8 m")
    if not station_id or not datum or not source or not available_at:
        raise ValueError("station_id, datum, source and available_at are required")
    try:
        parsed_times = [ocean_data.parse_timestamp(value) for value in times]
        parsed_available = ocean_data.parse_timestamp(available_at)
    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc)) from exc
    if any(right <= left for left, right in zip(parsed_times, parsed_times[1:])):
        raise ValueError("boundary times must be strictly increasing")
    if parsed_available < parsed_times[0]:
        raise ValueError("available_at cannot precede the first observed sea level")
    tide = level if predicted_tide_m is None else np.asarray(predicted_tide_m, dtype=float)
    surge = level - tide if surge_residual_m is None else np.asarray(surge_residual_m, dtype=float)
    if tide.shape != level.shape or surge.shape != level.shape:
        raise ValueError("tide and surge components must match observed levels")
    if np.any(~np.isfinite(tide)) or np.any(~np.isfinite(surge)):
        raise ValueError("tide and surge components must be finite")
    return {
        "times": list(times),
        "astronomical_tide_m": tide.tolist(),
        "storm_surge_m": surge.tolist(),
        "total_level_m": level.tolist(),
        "station": {"id": station_id, "datum": datum, "quality": "observed", "updated_at": available_at},
        "provenance": {
            "sea_level": f"observed({source})",
            "astronomical_tide": "observed-derived" if predicted_tide_m is not None else "not-separated",
            "storm_surge": "observed-derived-residual",
        },
        "uncertainty": {"level": "source-reported", "reason": "preserves station datum and availability time"},
    }


class CoastalCompoundModel:
    def __init__(self, surface_model: state_model.DistrictStateModel | None = None, geometry=None):
        self.surface_model = surface_model or state_model.DEFAULT_MODEL
        self.ids = self.surface_model.district_ids
        supplied = geometry or DEFAULT_COASTAL_GEOMETRY
        self.geometry = {did: dict(supplied.get(did, {})) for did in self.ids}

    def simulate(
        self,
        rainfall_by_district,
        boundary: Mapping[str, Any],
        *,
        initial_depth_mm=None,
        pump_efficiency=1.0,
        drainage_control=1.0,
    ) -> dict[str, Any]:
        levels = np.asarray(boundary.get("total_level_m"), dtype=float)
        if levels.ndim != 1 or not len(levels) or np.any(~np.isfinite(levels)):
            raise ValueError("boundary.total_level_m must be a finite non-empty series")
        surface = self.surface_model.simulate(
            rainfall_by_district, tide_m=levels, initial_depth_mm=initial_depth_mm,
            pump_efficiency=pump_efficiency, drainage_control=drainage_control,
        )
        if surface["storage_m3"].shape[0] != len(levels):
            raise ValueError("sea-level and rainfall horizons must match")
        nt, nd = surface["storage_m3"].shape
        marine = np.zeros((nt, nd), dtype=float)
        inflow = np.zeros_like(marine)
        returned = np.zeros_like(marine)
        previous = np.zeros(nd, dtype=float)
        for t in range(nt):
            for j, did in enumerate(self.ids):
                cfg = self.geometry.get(did) or {}
                if not cfg:
                    continue
                head = max(0.0, float(levels[t]) - float(cfg["crest_m"]))
                # Broad-crested weir screening equation, Q=C*b*h^(3/2), dt=1h.
                q_m3_s = 1.6 * float(cfg["width_m"]) * head ** 1.5
                inflow[t, j] = q_m3_s * 3600.0 * self.surface_model.dt_hours
                low_tide_relief = float(np.clip((float(cfg["crest_m"]) - levels[t]) / 0.8, 0.0, 1.0))
                fraction = 1.0 - np.exp(-float(cfg["return_rate_h"]) * low_tide_relief * self.surface_model.dt_hours)
                returned[t, j] = min(previous[j] + inflow[t, j], (previous[j] + inflow[t, j]) * fraction)
            previous = np.maximum(0.0, previous + inflow[t] - returned[t])
            marine[t] = previous
        total_storage = surface["storage_m3"] + marine
        total_depth = self.surface_model.storage_to_depth(total_storage)
        marine_closure = float(marine[-1].sum() + returned.sum() - inflow.sum())
        scale = max(1.0, float(inflow.sum()))
        return {
            "district_ids": self.ids,
            "times": list(boundary.get("times") or range(nt)),
            "surface_storage_m3": surface["storage_m3"],
            "marine_storage_m3": marine,
            "total_storage_m3": total_storage,
            "marine_inflow_m3": inflow,
            "marine_return_m3": returned,
            "total_depth_mm": total_depth,
            "surface": surface,
            "boundary": dict(boundary),
            "audit": {
                "surface": surface["audit"],
                "marine_inflow_m3": float(inflow.sum()),
                "marine_return_m3": float(returned.sum()),
                "final_marine_storage_m3": float(marine[-1].sum()),
                "marine_closure_error_m3": marine_closure,
                "marine_conservative": abs(marine_closure) <= 1e-9 * scale + 1e-6,
            },
            "provenance": "conservative compound pluvial-coastal screening model",
        }


DEFAULT_MODEL = CoastalCompoundModel()
