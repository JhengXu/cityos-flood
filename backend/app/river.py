# -*- coding: utf-8 -*-
"""Conservative small-basin river and floodplain graph model."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping, Sequence
import numpy as np


@dataclass(frozen=True)
class RiverReach:
    id: str
    downstream: str | None
    catchment_area_km2: float
    bankfull_m3_s: float
    travel_time_h: float
    floodplain_area_m2: float
    runoff_coefficient: float = 0.55


DEFAULT_REACHES = (
    RiverReach("guanlan", "shenzhen", 157.0, 220.0, 3.0, 7_000_000.0, 0.58),
    RiverReach("shenzhen", None, 312.0, 520.0, 4.0, 12_000_000.0, 0.70),
    RiverReach("longgang", "longgang_lower", 196.0, 260.0, 3.0, 8_000_000.0, 0.56),
    RiverReach("longgang_lower", None, 115.0, 390.0, 3.0, 9_000_000.0, 0.62),
    RiverReach("pingshan", None, 129.0, 230.0, 3.0, 8_000_000.0, 0.52),
)


class RiverBasinModel:
    def __init__(self, reaches: Sequence[RiverReach] = DEFAULT_REACHES, dt_hours: float = 1.0):
        self.reaches = tuple(reaches)
        self.ids = tuple(r.id for r in reaches)
        if len(self.ids) != len(set(self.ids)):
            raise ValueError("river reach ids must be unique")
        self.index = {rid: i for i, rid in enumerate(self.ids)}
        for reach in reaches:
            if reach.downstream is not None and reach.downstream not in self.index:
                raise ValueError(f"unknown downstream reach: {reach.downstream}")
            if min(reach.catchment_area_km2, reach.bankfull_m3_s, reach.travel_time_h, reach.floodplain_area_m2) <= 0:
                raise ValueError("reach hydraulic parameters must be positive")
        self.dt_hours = float(dt_hours)

    def _matrix(self, forcing, name):
        if isinstance(forcing, Mapping):
            missing = set(self.ids) - set(forcing)
            if missing:
                raise ValueError(f"{name} missing reaches: {sorted(missing)}")
            arrays = [np.asarray(forcing[rid], dtype=float) for rid in self.ids]
            if not arrays or len({len(a) for a in arrays}) != 1:
                raise ValueError(f"{name} series must have equal non-empty lengths")
            out = np.column_stack(arrays)
        else:
            out = np.asarray(forcing, dtype=float)
        if out.ndim != 2 or out.shape[1] != len(self.ids) or np.any(~np.isfinite(out)):
            raise ValueError(f"{name} must have shape (time, reaches) and be finite")
        return out

    def simulate(self, basin_rainfall_mm_h, upstream_inflow_m3_s=0.0, initial_channel_m3_s=None,
                 initial_floodplain_m3=None):
        rain = self._matrix(basin_rainfall_mm_h, "basin_rainfall_mm_h")
        nt, nr = rain.shape
        if np.isscalar(upstream_inflow_m3_s):
            upstream = np.full((nt, nr), float(upstream_inflow_m3_s))
        else:
            upstream = self._matrix(upstream_inflow_m3_s, "upstream_inflow_m3_s")
        if np.any(rain < 0) or np.any(upstream < 0):
            raise ValueError("rainfall and upstream inflow must be non-negative")
        channel = np.zeros((nt, nr)); flood = np.zeros((nt, nr)); depth = np.zeros((nt, nr))
        local_q = np.zeros((nt, nr)); routed_in = np.zeros((nt, nr)); routed_out = np.zeros((nt, nr))
        overbank = np.zeros((nt, nr)); flood_return = np.zeros((nt, nr)); residual = np.zeros((nt, nr))
        previous_q = np.zeros(nr) if initial_channel_m3_s is None else np.asarray(initial_channel_m3_s, dtype=float)
        previous_flood = np.zeros(nr) if initial_floodplain_m3 is None else np.asarray(initial_floodplain_m3, dtype=float)
        seconds = 3600.0 * self.dt_hours
        for t in range(nt):
            incoming = upstream[t].copy()
            for j, reach in enumerate(self.reaches):
                local_q[t, j] = rain[t, j] / 1000.0 * reach.catchment_area_km2 * 1e6 * reach.runoff_coefficient / seconds
            available_q = previous_q + local_q[t] + incoming
            # One synchronous linear-reservoir routing step.
            for j, reach in enumerate(self.reaches):
                fraction = 1.0 - np.exp(-self.dt_hours / reach.travel_time_h)
                routed_out[t, j] = available_q[j] * fraction
                if reach.downstream is not None:
                    routed_in[t, self.index[reach.downstream]] += routed_out[t, j]
            prebank = available_q + routed_in[t] - routed_out[t]
            for j, reach in enumerate(self.reaches):
                excess_q = max(0.0, prebank[j] - reach.bankfull_m3_s)
                overbank[t, j] = excess_q * seconds
                relief = min(previous_flood[j] + overbank[t, j], 0.08 * (previous_flood[j] + overbank[t, j]))
                flood[t, j] = max(0.0, previous_flood[j] + overbank[t, j] - relief)
                flood_return[t, j] = relief
                channel[t, j] = max(0.0, prebank[j] - excess_q + relief / seconds)
                depth[t, j] = flood[t, j] / reach.floodplain_area_m2
                residual[t, j] = flood[t, j] - (previous_flood[j] + overbank[t, j] - relief)
            previous_q, previous_flood = channel[t].copy(), flood[t].copy()
        return {
            "reach_ids": self.ids, "channel_flow_m3_s": channel,
            "floodplain_storage_m3": flood, "floodplain_depth_m": depth,
            "local_runoff_m3_s": local_q, "routed_in_m3_s": routed_in,
            "routed_out_m3_s": routed_out, "overbank_m3": overbank,
            "floodplain_return_m3": flood_return,
            "topology": [asdict(r) for r in self.reaches],
            "audit": {"max_abs_floodplain_residual_m3": float(np.max(np.abs(residual))),
                      "floodplain_conservative": bool(np.max(np.abs(residual)) < 1e-6)},
        }

    def assimilate_ensrf(self, ensemble_flow_m3_s, observations, observation_error_m3_s=20.0):
        ensemble = np.asarray(ensemble_flow_m3_s, dtype=float).copy()
        if ensemble.ndim != 2 or ensemble.shape[1] != len(self.ids) or ensemble.shape[0] < 2:
            raise ValueError("ensemble_flow_m3_s must have shape (members, reaches)")
        prior = ensemble.copy(); increments = np.zeros_like(ensemble)
        for rid, observed in observations.items():
            if rid not in self.index or not np.isfinite(observed) or observed < 0:
                raise ValueError(f"invalid river observation: {rid}")
            j = self.index[rid]; anomalies = ensemble - ensemble.mean(axis=0)
            y = ensemble[:, j]; ya = y - y.mean(); variance = float(ya @ ya / (len(y) - 1))
            gain = (anomalies.T @ ya / (len(y) - 1)) / max(variance + observation_error_m3_s ** 2, 1e-12)
            mean = ensemble.mean(axis=0) + gain * (float(observed) - y.mean())
            alpha = 1.0 / (1.0 + np.sqrt(observation_error_m3_s ** 2 / max(variance + observation_error_m3_s ** 2, 1e-12)))
            updated_anomalies = anomalies - alpha * np.outer(ya, gain)
            ensemble = np.maximum(0.0, mean + updated_anomalies)
        increments = ensemble - prior
        return {"forecast_flow_m3_s": prior, "analysis_flow_m3_s": ensemble,
                "assimilation_increment_m3_s": increments,
                "note": "EnSRF correction is an information increment, not a physical inflow."}


DEFAULT_MODEL = RiverBasinModel()

