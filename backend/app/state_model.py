# -*- coding: utf-8 -*-
"""Conservative district-scale pluvial-flood state-space model.

The previous ``hazard`` model mixed dimensionless district states in-place.  This
module instead keeps the prognostic state as a physical surface-water volume
(``m3``), derives water depth through a continuous two-stage storage curve, and
computes all graph fluxes from the same pre-routing state.  Every time step therefore has
an explicit, inspectable water balance::

    S[t+1] = S[t] + runoff + routed_in - routed_out - drainage - external_outflow

The model is deliberately a *grey-box baseline*, not a replacement for a
calibrated SWMM/2-D solver.  Parameters derived from GIS attributes are exposed
with provenance and can be calibrated as event observations become available.

Public API
----------
``DistrictStateModel.simulate``
    Deterministic depth/volume rollout with a node and system mass ledger.
``DistrictStateModel.simulate_ensemble``
    Parameter ensemble with P10/P50/P90 and threshold exceedance probability.
``DistrictStateModel.assimilate_enkf``
    Deterministic localised ensemble square-root update from observed depths
    (the legacy method name is retained for API compatibility).

Only NumPy and the Python standard library are required.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np

from .shenzhen import DISTRICTS


# Approximate administrative land areas.  They convert rainfall depth to volume;
# callers can override them through an ``area_km2`` field on district records.
# They are intentionally kept separate from learned/calibrated parameters.
DEFAULT_AREA_KM2 = {
    "futian": 78.7,
    "luohu": 78.8,
    "nanshan": 187.5,
    "baoan": 397.0,
    "longgang": 388.2,
    "yantian": 74.9,
    "longhua": 175.6,
    "pingshan": 168.0,
    "guangming": 156.1,
    "dapeng": 600.0,
}

DEFAULT_THRESHOLDS_MM = (150.0, 300.0, 500.0)
DEFAULT_STAGE_BREAK_MM = 150.0
DEFAULT_ADJACENCIES = {
    frozenset(pair)
    for pair in (
        ("baoan", "nanshan"),
        ("baoan", "longhua"),
        ("baoan", "guangming"),
        ("nanshan", "futian"),
        ("futian", "luohu"),
        ("futian", "longhua"),
        ("luohu", "longgang"),
        ("luohu", "yantian"),
        ("longgang", "longhua"),
        ("longgang", "pingshan"),
        ("longgang", "dapeng"),
        ("longgang", "yantian"),
        ("longhua", "guangming"),
        ("pingshan", "dapeng"),
        ("yantian", "dapeng"),
    )
}
PARAMETER_PROVENANCE = {
    "elevation_mean_m": "observed-derived: backend/data/gis_features.json DEM zonal mean",
    "impervious_ratio": "observed-derived: WorldCover zonal feature",
    "low_lying_ratio": "observed-derived: DEM zonal feature",
    "drainage_capacity_mm_h": "observed-derived proxy: GIS/road/land-cover feature pipeline",
    "coastal_exposure": "observed-derived backwater susceptibility proxy; not coastline/outfall geometry",
    "area_km2": "assumed: approximate administrative land area; override with authoritative polygon area",
    "runoff_coefficient": "estimated from impervious and low-lying fractions; calibrate to event runoff",
    "ponding_fraction": "estimated from low-lying and impervious fractions; calibrate to inundation maps",
    "expanded_ponding_fraction": "assumed stage-storage expansion above 0.15 m; calibrate to inundation maps",
    "stage_break_mm": "assumed 0.15 m stage-storage breakpoint; calibrate to observed inundation extent",
    "depression_storage_mm": "estimated shallow-surface detention threshold; calibrate to recession curves",
    "external_outflow_rate_h": "assumed river/channel/boundary export prior; calibrate to recession curves",
    "external_gravity_share": "assumed tide-sensitive share of external export; replace with mapped outfalls/channels",
    "routing": "estimated from DEM elevation drop across assumed administrative adjacencies; replace with subcatchment/pipe topology",
}


@dataclass(frozen=True)
class FlowEdge:
    """A directed, downhill internal transfer path between district reservoirs."""

    source: str
    target: str
    distance_km: float
    elevation_drop_m: float
    slope: float
    rate_per_h: float
    share: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _haversine_km(a: Sequence[float], b: Sequence[float]) -> float:
    lat1, lon1 = math.radians(float(a[0])), math.radians(float(a[1]))
    lat2, lon2 = math.radians(float(b[0])), math.radians(float(b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    q = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return 6371.0088 * 2.0 * math.asin(min(1.0, math.sqrt(q)))


def _load_local_gis_features() -> Dict[str, Dict[str, Any]]:
    """Read project-local features without invoking any network-backed loader."""

    path = Path(__file__).resolve().parent.parent / "data" / "gis_features.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _lognormal_multiplier(rng: np.random.Generator, cv: float, size: Any) -> np.ndarray:
    """Mean-one lognormal draws parameterised by coefficient of variation."""

    if cv <= 0.0:
        return np.ones(size, dtype=float)
    sigma2 = math.log1p(float(cv) ** 2)
    return rng.lognormal(mean=-0.5 * sigma2, sigma=math.sqrt(sigma2), size=size)


class DistrictStateModel:
    """Ten-node conservative graph state model for Shenzhen surface flooding.

    Parameters are district scale and should not be interpreted as street-scale
    hydraulics.  ``dt_hours`` may be fractional; rates are converted using an
    exponential finite-step fraction for numerical stability.
    """

    def __init__(
        self,
        districts: Optional[Sequence[Mapping[str, Any]]] = None,
        dt_hours: float = 1.0,
        max_edge_distance_km: float = 25.0,
        max_downstream_edges: int = 2,
        allowed_adjacencies: Optional[Iterable[Iterable[str]]] = DEFAULT_ADJACENCIES,
    ) -> None:
        if not np.isfinite(dt_hours) or dt_hours <= 0.0:
            raise ValueError("dt_hours must be finite and positive")
        if max_downstream_edges < 0:
            raise ValueError("max_downstream_edges must be non-negative")

        base = list(districts if districts is not None else DISTRICTS)
        if not base:
            raise ValueError("at least one district is required")
        ids = [str(d["id"]) for d in base]
        if len(ids) != len(set(ids)):
            raise ValueError("district ids must be unique")

        gis = _load_local_gis_features()
        enriched = []
        for item in base:
            d = dict(item)
            # The existing network-backed elevation loader can fall back to a
            # city-wide constant.  Prefer the already downloaded DEM aggregate.
            local = gis.get(str(d["id"]), {})
            for key in (
                "elevation_mean",
                "low_lying_ratio",
                "impervious_ratio",
                "coastal",
                "drainage_design",
                "road_km",
            ):
                if key in local:
                    d[key] = local[key]
            enriched.append(d)

        self.districts = tuple(enriched)
        self.district_ids = tuple(str(d["id"]) for d in enriched)
        self.index = {did: i for i, did in enumerate(self.district_ids)}
        self.n_districts = len(self.district_ids)
        self.dt_hours = float(dt_hours)
        self.max_edge_distance_km = float(max_edge_distance_km)
        self.max_downstream_edges = int(max_downstream_edges)
        self.allowed_adjacencies = (
            None
            if allowed_adjacencies is None
            else frozenset(frozenset(map(str, pair)) for pair in allowed_adjacencies)
        )

        self.centers = np.asarray([d["center"] for d in enriched], dtype=float)
        self.distance_km = self._distance_matrix()
        self.parameters = self._derive_parameters()
        self.edges = tuple(self._build_flow_edges())
        self._routing_rate = self._routing_matrix()

    # ------------------------------------------------------------------
    # Construction and parameter derivation
    # ------------------------------------------------------------------
    def _distance_matrix(self) -> np.ndarray:
        out = np.zeros((self.n_districts, self.n_districts), dtype=float)
        for i in range(self.n_districts):
            for j in range(i + 1, self.n_districts):
                dist = _haversine_km(self.centers[i], self.centers[j])
                out[i, j] = out[j, i] = dist
        return out

    def _derive_parameters(self) -> Dict[str, np.ndarray]:
        area = np.asarray(
            [
                float(d.get("area_km2", DEFAULT_AREA_KM2.get(str(d["id"]), 100.0)))
                for d in self.districts
            ],
            dtype=float,
        )
        elevation = np.asarray([float(d.get("elevation_mean", 30.0)) for d in self.districts])
        impervious = np.clip(
            np.asarray([float(d.get("impervious_ratio", 0.4)) for d in self.districts]), 0.0, 1.0
        )
        low = np.clip(
            np.asarray([float(d.get("low_lying_ratio", 0.3)) for d in self.districts]), 0.0, 1.0
        )
        coastal = np.clip(
            np.asarray([float(d.get("coastal", 0.0)) for d in self.districts]), 0.0, 1.0
        )
        drainage = np.maximum(
            np.asarray([float(d.get("drainage_design", 25.0)) for d in self.districts]), 0.0
        )

        # Event runoff coefficient: pervious areas still produce runoff during a
        # saturated extreme event, while impervious and low-lying areas respond
        # faster.  Values remain dimensionless and bounded.
        runoff = np.clip(0.18 + 0.68 * impervious + 0.12 * low, 0.20, 0.92)

        # Only part of a district is a hydraulically connected surface ponding
        # reservoir at shallow stage.  Above 0.15 m, floodplain area expands;
        # this two-stage storage curve avoids turning district-equivalent runoff
        # into implausible multi-metre depths without clipping water mass.
        ponding_fraction = np.clip(0.025 + 0.14 * low + 0.035 * impervious, 0.025, 0.20)
        expanded_ponding_fraction = np.clip(
            0.20 + 0.20 * low + 0.08 * impervious,
            np.maximum(ponding_fraction, 0.20),
            0.48,
        )
        area_m2 = area * 1_000_000.0
        ponding_area_m2 = area_m2 * ponding_fraction
        expanded_ponding_area_m2 = area_m2 * expanded_ponding_fraction

        # Surface/channel export is distinct from designed drainage.  It only
        # acts above depression storage and remains tide-sensitive in coastal
        # districts.  Rates are explicit uncalibrated priors, not fitted truth.
        external_outflow_rate_h = np.clip(
            0.055 + 0.10 * coastal + 0.035 * (1.0 - low), 0.05, 0.20
        )
        external_gravity_share = np.clip(0.30 + 0.55 * coastal, 0.30, 0.85)
        depression_storage_mm = np.clip(25.0 + 35.0 * low, 25.0, 60.0)

        return {
            "area_km2": area,
            "area_m2": area_m2,
            "elevation_mean_m": elevation,
            "impervious_ratio": impervious,
            "low_lying_ratio": low,
            "coastal_exposure": coastal,
            "drainage_capacity_mm_h": drainage,
            "runoff_coefficient": runoff,
            "ponding_fraction": ponding_fraction,
            "ponding_area_m2": ponding_area_m2,
            "expanded_ponding_fraction": expanded_ponding_fraction,
            "expanded_ponding_area_m2": expanded_ponding_area_m2,
            "stage_break_mm": np.full(self.n_districts, DEFAULT_STAGE_BREAK_MM),
            "depression_storage_mm": depression_storage_mm,
            "external_outflow_rate_h": external_outflow_rate_h,
            "external_gravity_share": external_gravity_share,
        }

    def _build_flow_edges(self) -> Iterable[FlowEdge]:
        elev = self.parameters["elevation_mean_m"]
        low = self.parameters["low_lying_ratio"]
        edges = []
        for i, source in enumerate(self.district_ids):
            candidates = []
            for j, target in enumerate(self.district_ids):
                if i == j:
                    continue
                if (
                    self.allowed_adjacencies is not None
                    and frozenset((source, target)) not in self.allowed_adjacencies
                ):
                    continue
                dist = float(self.distance_km[i, j])
                drop = float(elev[i] - elev[j])
                if drop <= 0.25 or dist > self.max_edge_distance_km:
                    continue
                slope = drop / max(dist * 1000.0, 1.0)
                # Prefer nearby paths with a clear terrain gradient.  ID is the
                # final tie-breaker so graph construction is input-order neutral.
                score = math.sqrt(slope) / max(dist, 1.0)
                candidates.append((score, target, j, dist, drop, slope))
            candidates.sort(key=lambda x: (-x[0], x[1]))
            chosen = candidates[: self.max_downstream_edges]
            if not chosen:
                continue

            raw = np.asarray([c[0] for c in chosen], dtype=float)
            shares = raw / raw.sum()
            # District routing is intentionally slower than a channel solver.  A
            # lower source ponding ratio implies less detention and faster export.
            source_rate = float(np.clip(0.035 + 1.6 * math.sqrt(max(c[5] for c in chosen)), 0.04, 0.22))
            source_rate *= float(1.0 - 0.35 * low[i])
            for c, share in zip(chosen, shares):
                _, target, _, dist, drop, slope = c
                edges.append(
                    FlowEdge(
                        source=source,
                        target=target,
                        distance_km=dist,
                        elevation_drop_m=drop,
                        slope=slope,
                        rate_per_h=source_rate * float(share),
                        share=float(share),
                    )
                )
        return edges

    def _routing_matrix(self) -> np.ndarray:
        """Matrix ``R[source, target]`` of first-order transfer rates (1/h)."""

        matrix = np.zeros((self.n_districts, self.n_districts), dtype=float)
        for edge in self.edges:
            matrix[self.index[edge.source], self.index[edge.target]] = edge.rate_per_h
        return matrix

    def describe(self) -> Dict[str, Any]:
        """Return JSON-friendly topology, physical parameters, and provenance."""

        return {
            "district_ids": list(self.district_ids),
            "dt_hours": self.dt_hours,
            "parameters": {
                key: {did: float(values[i]) for i, did in enumerate(self.district_ids)}
                for key, values in self.parameters.items()
                if key not in {"area_m2", "ponding_area_m2", "expanded_ponding_area_m2"}
            },
            "edges": [edge.to_dict() for edge in self.edges],
            "provenance": dict(PARAMETER_PROVENANCE),
            "limitations": (
                "district-scale grey-box routing; replace centroid edges and assumed areas "
                "with authoritative subcatchment/pipe topology before operational use"
            ),
        }

    # ------------------------------------------------------------------
    # Input handling and physical transforms
    # ------------------------------------------------------------------
    @staticmethod
    def _as_1d(value: Any, name: str) -> np.ndarray:
        arr = np.asarray(value, dtype=float)
        if arr.ndim == 0:
            arr = arr.reshape(1)
        if arr.ndim != 1:
            raise ValueError(f"{name} values must be scalars or one-dimensional sequences")
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"{name} contains non-finite values")
        return arr

    def _rainfall_matrix(self, rainfall_by_district: Any) -> np.ndarray:
        if isinstance(rainfall_by_district, Mapping):
            unknown = set(rainfall_by_district) - set(self.district_ids)
            missing = set(self.district_ids) - set(rainfall_by_district)
            if unknown:
                raise ValueError(f"unknown rainfall districts: {sorted(unknown)}")
            if missing:
                raise ValueError(f"missing rainfall districts: {sorted(missing)}")
            series = {
                did: self._as_1d(rainfall_by_district[did], "rainfall") for did in self.district_ids
            }
            lengths = {len(v) for v in series.values()}
            non_scalar = {length for length in lengths if length != 1}
            if len(non_scalar) > 1:
                raise ValueError("district rainfall sequences must have the same length")
            time_steps = next(iter(non_scalar), 1)
            columns = [
                np.full(time_steps, arr[0], dtype=float) if len(arr) == 1 else arr for arr in series.values()
            ]
            matrix = np.column_stack(columns)
        else:
            arr = np.asarray(rainfall_by_district, dtype=float)
            if arr.ndim == 1 and self.n_districts == 1:
                matrix = arr[:, None]
            elif arr.ndim == 2 and arr.shape[1] == self.n_districts:
                matrix = arr
            else:
                raise ValueError("rainfall must be a district mapping or an array shaped (time, district)")
        if matrix.shape[0] == 0:
            raise ValueError("rainfall must contain at least one time step")
        if not np.all(np.isfinite(matrix)) or np.any(matrix < 0.0):
            raise ValueError("rainfall must be finite and non-negative")
        return matrix.astype(float, copy=False)

    def _forcing_matrix(self, value: Any, time_steps: int, name: str) -> np.ndarray:
        if isinstance(value, Mapping):
            unknown = set(value) - set(self.district_ids)
            if unknown:
                raise ValueError(f"unknown {name} districts: {sorted(unknown)}")
            columns = []
            for did in self.district_ids:
                arr = self._as_1d(value.get(did, 1.0 if name != "tide_m" else 0.0), name)
                if len(arr) == 1:
                    arr = np.full(time_steps, arr[0], dtype=float)
                if len(arr) != time_steps:
                    raise ValueError(f"{name} sequence for {did} has the wrong length")
                columns.append(arr)
            return np.column_stack(columns)

        arr = np.asarray(value, dtype=float)
        if arr.ndim == 0:
            out = np.full((time_steps, self.n_districts), float(arr), dtype=float)
        elif arr.ndim == 1:
            if len(arr) != time_steps:
                raise ValueError(f"{name} sequence has the wrong length")
            out = np.repeat(arr[:, None], self.n_districts, axis=1)
        elif arr.ndim == 2 and arr.shape == (time_steps, self.n_districts):
            out = arr.astype(float, copy=False)
        else:
            raise ValueError(f"{name} must be scalar, a time series, district mapping, or (time, district) array")
        if not np.all(np.isfinite(out)):
            raise ValueError(f"{name} contains non-finite values")
        return out

    def _initial_depth_vector(self, value: Any) -> np.ndarray:
        if value is None:
            return np.zeros(self.n_districts, dtype=float)
        if isinstance(value, Mapping):
            unknown = set(value) - set(self.district_ids)
            if unknown:
                raise ValueError(f"unknown initial-depth districts: {sorted(unknown)}")
            out = np.asarray([float(value.get(did, 0.0)) for did in self.district_ids])
        else:
            arr = np.asarray(value, dtype=float)
            if arr.ndim == 0:
                out = np.full(self.n_districts, float(arr), dtype=float)
            elif arr.shape == (self.n_districts,):
                out = arr.astype(float, copy=False)
            else:
                raise ValueError("initial_depth_mm must be scalar, district mapping, or district vector")
        if not np.all(np.isfinite(out)) or np.any(out < 0.0):
            raise ValueError("initial_depth_mm must be finite and non-negative")
        return out

    def depth_to_storage(
        self,
        depth_mm: Any,
        ponding_area_m2: Optional[np.ndarray] = None,
        expanded_ponding_area_m2: Optional[np.ndarray] = None,
        stage_break_mm: Any = DEFAULT_STAGE_BREAK_MM,
    ) -> np.ndarray:
        shallow_area = (
            self.parameters["ponding_area_m2"]
            if ponding_area_m2 is None
            else np.asarray(ponding_area_m2, dtype=float)
        )
        expanded_area = (
            self.parameters["expanded_ponding_area_m2"]
            if expanded_ponding_area_m2 is None
            else np.asarray(expanded_ponding_area_m2, dtype=float)
        )
        depth = np.asarray(depth_mm, dtype=float)
        stage_break = np.asarray(stage_break_mm, dtype=float)
        return (
            np.minimum(depth, stage_break) / 1000.0 * shallow_area
            + np.maximum(depth - stage_break, 0.0) / 1000.0 * expanded_area
        )

    def storage_to_depth(
        self,
        storage_m3: Any,
        ponding_area_m2: Optional[np.ndarray] = None,
        expanded_ponding_area_m2: Optional[np.ndarray] = None,
        stage_break_mm: Any = DEFAULT_STAGE_BREAK_MM,
    ) -> np.ndarray:
        shallow_area = (
            self.parameters["ponding_area_m2"]
            if ponding_area_m2 is None
            else np.asarray(ponding_area_m2, dtype=float)
        )
        expanded_area = (
            self.parameters["expanded_ponding_area_m2"]
            if expanded_ponding_area_m2 is None
            else np.asarray(expanded_ponding_area_m2, dtype=float)
        )
        storage = np.asarray(storage_m3, dtype=float)
        stage_break = np.asarray(stage_break_mm, dtype=float)
        break_storage = stage_break / 1000.0 * shallow_area
        shallow_depth = storage / shallow_area * 1000.0
        deep_depth = stage_break + (storage - break_storage) / expanded_area * 1000.0
        return np.where(storage <= break_storage, shallow_depth, deep_depth)

    @staticmethod
    def _tide_factor(tide_m: np.ndarray, coastal: np.ndarray) -> np.ndarray:
        """Gravity-drainage availability; high sea levels cannot improve it."""

        # Smooth transition around a 0.5 m local boundary proxy.  The lower bound
        # retains pressurised/pumped capacity and avoids a hard discontinuity.
        x = np.clip((tide_m - 0.5) / 0.25, -40.0, 40.0)
        backwater = 1.0 / (1.0 + np.exp(-x))
        return np.clip(1.0 - 0.78 * coastal * backwater, 0.15, 1.0)

    def _resolved_parameters(self, overrides: Optional[Mapping[str, Any]]) -> Dict[str, np.ndarray]:
        resolved = {key: value.copy() for key, value in self.parameters.items()}
        routing_multiplier = np.ones(self.n_districts, dtype=float)
        if overrides:
            allowed = {
                "runoff_coefficient",
                "drainage_capacity_mm_h",
                "ponding_fraction",
                "expanded_ponding_fraction",
                "external_outflow_rate_h",
                "routing_multiplier",
            }
            unknown = set(overrides) - allowed
            if unknown:
                raise ValueError(f"unknown parameter overrides: {sorted(unknown)}")
            for key, value in overrides.items():
                arr = np.asarray(value, dtype=float)
                if arr.ndim == 0:
                    arr = np.full(self.n_districts, float(arr), dtype=float)
                if arr.shape != (self.n_districts,) or not np.all(np.isfinite(arr)):
                    raise ValueError(f"override {key} must be finite scalar or district vector")
                if key == "routing_multiplier":
                    routing_multiplier = np.maximum(arr, 0.0)
                else:
                    resolved[key] = arr.copy()
        resolved["runoff_coefficient"] = np.clip(resolved["runoff_coefficient"], 0.0, 1.0)
        resolved["drainage_capacity_mm_h"] = np.maximum(resolved["drainage_capacity_mm_h"], 0.0)
        resolved["ponding_fraction"] = np.clip(resolved["ponding_fraction"], 0.005, 0.5)
        resolved["expanded_ponding_fraction"] = np.clip(
            np.maximum(resolved["expanded_ponding_fraction"], resolved["ponding_fraction"]),
            0.02,
            0.8,
        )
        resolved["external_outflow_rate_h"] = np.maximum(
            resolved["external_outflow_rate_h"], 0.0
        )
        resolved["ponding_area_m2"] = resolved["area_m2"] * resolved["ponding_fraction"]
        resolved["expanded_ponding_area_m2"] = (
            resolved["area_m2"] * resolved["expanded_ponding_fraction"]
        )
        resolved["routing_multiplier"] = routing_multiplier
        return resolved

    # ------------------------------------------------------------------
    # Conservative forecast model
    # ------------------------------------------------------------------
    def simulate(
        self,
        rainfall_by_district: Any,
        tide_m: Any = 0.0,
        pump_efficiency: Any = 1.0,
        drainage_control: Any = 1.0,
        initial_depth_mm: Any = None,
        parameter_overrides: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run a synchronous water-volume forecast.

        ``rainfall_by_district`` is a ``{district_id: [mm/h, ...]}`` mapping or
        a ``(time, district)`` array.  Tide is in metres; pump efficiency is in
        ``[0, 1]``; drainage control is a non-negative operational multiplier
        (values above one represent temporary/mobile capacity).
        """

        rain = self._rainfall_matrix(rainfall_by_district)
        time_steps = rain.shape[0]
        tide = self._forcing_matrix(tide_m, time_steps, "tide_m")
        pump = self._forcing_matrix(pump_efficiency, time_steps, "pump_efficiency")
        control = self._forcing_matrix(drainage_control, time_steps, "drainage_control")
        if np.any((pump < 0.0) | (pump > 1.0)):
            raise ValueError("pump_efficiency must be between 0 and 1")
        if np.any(control < 0.0):
            raise ValueError("drainage_control must be non-negative")

        params = self._resolved_parameters(parameter_overrides)
        initial_depth = self._initial_depth_vector(initial_depth_mm)
        storage = self.depth_to_storage(
            initial_depth,
            params["ponding_area_m2"],
            params["expanded_ponding_area_m2"],
            params["stage_break_mm"],
        )

        shape = (time_steps, self.n_districts)
        storage_before = np.zeros(shape, dtype=float)
        storage_after = np.zeros(shape, dtype=float)
        depth = np.zeros(shape, dtype=float)
        runoff_volume = np.zeros(shape, dtype=float)
        drainage_volume = np.zeros(shape, dtype=float)
        routed_in = np.zeros(shape, dtype=float)
        routed_out = np.zeros(shape, dtype=float)
        external_outflow = np.zeros(shape, dtype=float)
        node_residual = np.zeros(shape, dtype=float)
        system_residual = np.zeros(time_steps, dtype=float)

        # Source-wise routing rates are perturbed/calibrated without changing edge
        # shares.  Finite-step fractions are <= 1 for every positive dt.
        route_rate = self._routing_rate * params["routing_multiplier"][:, None]
        source_rate = route_rate.sum(axis=1)
        route_share = np.divide(
            route_rate,
            source_rate[:, None],
            out=np.zeros_like(route_rate),
            where=source_rate[:, None] > 0.0,
        )
        depression_storage = self.depth_to_storage(
            params["depression_storage_mm"],
            params["ponding_area_m2"],
            params["expanded_ponding_area_m2"],
            params["stage_break_mm"],
        )

        initial_storage = storage.copy()
        for t in range(time_steps):
            before = storage.copy()
            runoff = rain[t] / 1000.0 * params["area_m2"] * params["runoff_coefficient"] * self.dt_hours
            available = before + runoff

            tide_availability = self._tide_factor(tide[t], params["coastal_exposure"])
            # 65% gravity network (tide-sensitive), 35% pumped component.  A
            # drainage-control multiplier acts on the combined operating capacity.
            operating_factor = control[t] * (0.65 * tide_availability + 0.35 * pump[t])
            capacity = (
                params["drainage_capacity_mm_h"]
                / 1000.0
                * params["area_m2"]
                # ``drainage_design`` is a design *rainfall intensity*, not a
                # clear-water depth removed over the whole district.  Convert it
                # through the same event runoff coefficient as rainfall so the
                # nominal onset remains near rain > design intensity (rather than
                # the erroneous rain > design/runoff_coefficient threshold).
                * params["runoff_coefficient"]
                * operating_factor
                * self.dt_hours
            )
            drained = np.minimum(available, np.maximum(capacity, 0.0))
            remaining = available - drained

            # Internal routing and river/city-boundary export compete for the
            # same mobile surface storage.  Both are calculated synchronously
            # from the pre-routing state; incoming water cannot be re-exported
            # in the same step.
            gravity_share = params["external_gravity_share"]
            external_rate = params["external_outflow_rate_h"] * (
                gravity_share * tide_availability + (1.0 - gravity_share) * pump[t]
            )
            combined_rate = source_rate + external_rate
            export_fraction = 1.0 - np.exp(-combined_rate * self.dt_hours)
            mobile = np.maximum(remaining - depression_storage, 0.0)
            total_export = mobile * export_fraction
            internal_export = np.divide(
                total_export * source_rate,
                combined_rate,
                out=np.zeros_like(total_export),
                where=combined_rate > 0.0,
            )
            boundary_export = np.divide(
                total_export * external_rate,
                combined_rate,
                out=np.zeros_like(total_export),
                where=combined_rate > 0.0,
            )
            edge_flux = internal_export[:, None] * route_share
            incoming = edge_flux.sum(axis=0)
            after = remaining - internal_export - boundary_export + incoming
            after = np.maximum(after, 0.0)  # guards only floating-point fuzz

            residual = after - (
                before + runoff + incoming - internal_export - boundary_export - drained
            )
            sys_residual = float(
                after.sum()
                - (before.sum() + runoff.sum() - drained.sum() - boundary_export.sum())
            )

            storage_before[t] = before
            storage_after[t] = after
            runoff_volume[t] = runoff
            drainage_volume[t] = drained
            routed_in[t] = incoming
            routed_out[t] = internal_export
            external_outflow[t] = boundary_export
            node_residual[t] = residual
            system_residual[t] = sys_residual
            depth[t] = self.storage_to_depth(
                after,
                params["ponding_area_m2"],
                params["expanded_ponding_area_m2"],
                params["stage_break_mm"],
            )
            storage = after

        closure_error = float(
            storage_after[-1].sum()
            + drainage_volume.sum()
            + external_outflow.sum()
            - initial_storage.sum()
            - runoff_volume.sum()
        )
        scale = max(1.0, float(initial_storage.sum() + runoff_volume.sum()))
        audit = {
            "initial_storage_m3": float(initial_storage.sum()),
            "rainfall_runoff_m3": float(runoff_volume.sum()),
            "drainage_m3": float(drainage_volume.sum()),
            "external_outflow_m3": float(external_outflow.sum()),
            "final_storage_m3": float(storage_after[-1].sum()),
            "internal_routed_m3": float(routed_out.sum()),
            "closure_error_m3": closure_error,
            "relative_closure_error": closure_error / scale,
            "max_abs_node_residual_m3": float(np.max(np.abs(node_residual))),
            "max_abs_system_residual_m3": float(np.max(np.abs(system_residual))),
            "conservative": bool(abs(closure_error) <= 1e-9 * scale + 1e-6),
        }

        return {
            "district_ids": self.district_ids,
            "dt_hours": self.dt_hours,
            "depth_mm": depth,
            "storage_m3": storage_after,
            "initial_depth_mm": initial_depth,
            "initial_storage_m3": initial_storage,
            "rainfall_runoff_m3": runoff_volume,
            "drainage_m3": drainage_volume,
            "routed_in_m3": routed_in,
            "routed_out_m3": routed_out,
            "external_outflow_m3": external_outflow,
            "storage_before_m3": storage_before,
            "mass_balance_residual_m3": node_residual,
            "system_mass_balance_residual_m3": system_residual,
            "audit": audit,
            "edges": tuple(edge.to_dict() for edge in self.edges),
            "parameter_provenance": dict(PARAMETER_PROVENANCE),
        }

    def sample_parameters(
        self,
        n_members: int = 100,
        seed: Optional[int] = 42,
        parameter_cv: Optional[Mapping[str, float]] = None,
    ) -> Dict[str, np.ndarray]:
        """Draw a reusable parameter ensemble for paired/canonical experiments."""

        if int(n_members) != n_members or n_members < 2:
            raise ValueError("n_members must be an integer >= 2")
        cv = {
            "runoff_coefficient": 0.12,
            "drainage_capacity_mm_h": 0.20,
            "ponding_fraction": 0.18,
            "expanded_ponding_fraction": 0.12,
            "external_outflow_rate_h": 0.35,
            "routing_multiplier": 0.25,
        }
        if parameter_cv:
            unknown = set(parameter_cv) - set(cv)
            if unknown:
                raise ValueError(f"unknown parameter CVs: {sorted(unknown)}")
            for key, value in parameter_cv.items():
                if not np.isfinite(value) or value < 0.0:
                    raise ValueError("parameter CVs must be finite and non-negative")
                cv[key] = float(value)

        rng = np.random.default_rng(seed)
        n = self.n_districts
        sampled = {key: [] for key in cv}
        for _ in range(int(n_members)):
            ponding = np.clip(
                self.parameters["ponding_fraction"]
                * _lognormal_multiplier(rng, cv["ponding_fraction"], n),
                0.005,
                0.5,
            )
            values = {
                "runoff_coefficient": np.clip(
                    self.parameters["runoff_coefficient"]
                    * _lognormal_multiplier(rng, cv["runoff_coefficient"], n),
                    0.05,
                    0.98,
                ),
                "drainage_capacity_mm_h": self.parameters["drainage_capacity_mm_h"]
                * _lognormal_multiplier(rng, cv["drainage_capacity_mm_h"], n),
                "ponding_fraction": ponding,
                "expanded_ponding_fraction": np.clip(
                    self.parameters["expanded_ponding_fraction"]
                    * _lognormal_multiplier(rng, cv["expanded_ponding_fraction"], n),
                    np.maximum(ponding, 0.02),
                    0.8,
                ),
                "external_outflow_rate_h": self.parameters["external_outflow_rate_h"]
                * _lognormal_multiplier(rng, cv["external_outflow_rate_h"], n),
                "routing_multiplier": _lognormal_multiplier(
                    rng, cv["routing_multiplier"], n
                ),
            }
            for key, value in values.items():
                sampled[key].append(value)
        return {key: np.asarray(values, dtype=float) for key, values in sampled.items()}

    def simulate_ensemble(
        self,
        rainfall_by_district: Any,
        tide_m: Any = 0.0,
        pump_efficiency: Any = 1.0,
        drainage_control: Any = 1.0,
        initial_depth_mm: Any = None,
        n_members: int = 100,
        seed: Optional[int] = 42,
        thresholds_mm: Sequence[float] = DEFAULT_THRESHOLDS_MM,
        parameter_cv: Optional[Mapping[str, float]] = None,
        sampled_parameters: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run a multi-parameter ensemble and return uncertainty-output shapes.

        Uncertainty spans runoff conversion, effective drainage, shallow and
        expanded storage areas, graph travel rate and external export.  This
        represents *parameter* uncertainty only; callers should also pass rainfall
        forecast members when meteorological ensembles become available.
        """

        if int(n_members) != n_members or n_members < 2:
            raise ValueError("n_members must be an integer >= 2")
        thresholds = np.asarray(tuple(thresholds_mm), dtype=float)
        if thresholds.ndim != 1 or np.any(~np.isfinite(thresholds)) or np.any(thresholds < 0.0):
            raise ValueError("thresholds_mm must be finite and non-negative")

        if sampled_parameters is not None and parameter_cv is not None:
            raise ValueError("provide sampled_parameters or parameter_cv, not both")
        if sampled_parameters is None:
            sampled = self.sample_parameters(n_members, seed, parameter_cv)
        else:
            expected = {
                "runoff_coefficient",
                "drainage_capacity_mm_h",
                "ponding_fraction",
                "expanded_ponding_fraction",
                "external_outflow_rate_h",
                "routing_multiplier",
            }
            unknown = set(sampled_parameters) - expected
            missing = expected - set(sampled_parameters)
            if unknown or missing:
                raise ValueError(
                    f"sampled_parameters keys mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
                )
            sampled = {
                key: np.asarray(value, dtype=float)
                for key, value in sampled_parameters.items()
            }
            if any(value.shape != (int(n_members), self.n_districts) for value in sampled.values()):
                raise ValueError("sampled parameter arrays must have shape (members, districts)")
            if any(np.any(~np.isfinite(value)) for value in sampled.values()):
                raise ValueError("sampled parameter arrays must be finite")

        if initial_depth_mm is None or isinstance(initial_depth_mm, Mapping):
            initial_members = np.repeat(
                self._initial_depth_vector(initial_depth_mm)[None, :], int(n_members), axis=0
            )
        else:
            initial_array = np.asarray(initial_depth_mm, dtype=float)
            if initial_array.shape == (self.n_districts,):
                initial_members = np.repeat(initial_array[None, :], int(n_members), axis=0)
            elif initial_array.shape == (int(n_members), self.n_districts):
                initial_members = initial_array
            elif initial_array.ndim == 0:
                initial_members = np.full(
                    (int(n_members), self.n_districts), float(initial_array), dtype=float
                )
            else:
                raise ValueError(
                    "initial_depth_mm must be scalar, district mapping/vector, or member-by-district array"
                )
            if np.any(~np.isfinite(initial_members)) or np.any(initial_members < 0.0):
                raise ValueError("initial_depth_mm must be finite and non-negative")

        members_depth = []
        members_storage = []
        members_runoff_depth = []
        members_drainage_depth = []
        members_routed_in_depth = []
        members_routed_out_depth = []
        members_external_outflow_depth = []
        member_audits = []
        for member in range(int(n_members)):
            overrides = {
                key: values[member] for key, values in sampled.items()
            }
            result = self.simulate(
                rainfall_by_district,
                tide_m=tide_m,
                pump_efficiency=pump_efficiency,
                drainage_control=drainage_control,
                initial_depth_mm=initial_members[member],
                parameter_overrides=overrides,
            )
            members_depth.append(result["depth_mm"])
            members_storage.append(result["storage_m3"])
            ponding_area = overrides["ponding_fraction"] * self.parameters["area_m2"]
            volume_to_depth = 1000.0 / ponding_area[None, :]
            members_runoff_depth.append(result["rainfall_runoff_m3"] * volume_to_depth)
            members_drainage_depth.append(result["drainage_m3"] * volume_to_depth)
            members_routed_in_depth.append(result["routed_in_m3"] * volume_to_depth)
            members_routed_out_depth.append(result["routed_out_m3"] * volume_to_depth)
            members_external_outflow_depth.append(
                result["external_outflow_m3"] * volume_to_depth
            )
            member_audits.append(result["audit"])

        depth_ensemble = np.asarray(members_depth, dtype=float)
        storage_ensemble = np.asarray(members_storage, dtype=float)
        runoff_depth_ensemble = np.asarray(members_runoff_depth, dtype=float)
        drainage_depth_ensemble = np.asarray(members_drainage_depth, dtype=float)
        routed_in_depth_ensemble = np.asarray(members_routed_in_depth, dtype=float)
        routed_out_depth_ensemble = np.asarray(members_routed_out_depth, dtype=float)
        external_outflow_depth_ensemble = np.asarray(
            members_external_outflow_depth, dtype=float
        )
        q10, q50, q90 = np.quantile(depth_ensemble, (0.10, 0.50, 0.90), axis=0)
        exceedance = {
            float(threshold): np.mean(depth_ensemble >= threshold, axis=0) for threshold in thresholds
        }
        max_closure = max(abs(float(item["closure_error_m3"])) for item in member_audits)

        return {
            "district_ids": self.district_ids,
            "n_members": int(n_members),
            "members_depth_mm": depth_ensemble,
            "members_storage_m3": storage_ensemble,
            "members_initial_depth_mm": initial_members.copy(),
            "members_ponding_area_m2": (
                sampled["ponding_fraction"]
                * self.parameters["area_m2"][None, :]
            ),
            "members_expanded_ponding_area_m2": (
                sampled["expanded_ponding_fraction"]
                * self.parameters["area_m2"][None, :]
            ),
            "depth_p10_mm": q10,
            "depth_p50_mm": q50,
            "depth_p90_mm": q90,
            "runoff_depth_p50_mm": np.quantile(runoff_depth_ensemble, 0.50, axis=0),
            "drainage_depth_p50_mm": np.quantile(drainage_depth_ensemble, 0.50, axis=0),
            "routed_in_depth_p50_mm": np.quantile(routed_in_depth_ensemble, 0.50, axis=0),
            "routed_out_depth_p50_mm": np.quantile(routed_out_depth_ensemble, 0.50, axis=0),
            "external_outflow_depth_p50_mm": np.quantile(
                external_outflow_depth_ensemble, 0.50, axis=0
            ),
            "exceedance_probability": exceedance,
            "thresholds_mm": thresholds,
            "sampled_parameters": {
                key: values.copy() for key, values in sampled.items()
            },
            "member_audits": tuple(member_audits),
            "audit": {
                "all_members_conservative": all(item["conservative"] for item in member_audits),
                "max_abs_closure_error_m3": float(max_closure),
            },
        }

    # ------------------------------------------------------------------
    # Ensemble Kalman data assimilation
    # ------------------------------------------------------------------
    def assimilate_enkf(
        self,
        ensemble_storage_m3: Any,
        observations_mm: Mapping[str, float],
        observation_error_mm: Any = 20.0,
        localization_radius_km: float = 25.0,
        seed: Optional[int] = 42,
        ponding_area_m2: Optional[Any] = None,
        expanded_ponding_area_m2: Optional[Any] = None,
        stage_break_mm: Any = DEFAULT_STAGE_BREAK_MM,
    ) -> Dict[str, Any]:
        """Assimilate sparse water-depth observations into a volume ensemble.

        The forecast state and returned analysis state are in ``m3`` so they can
        be passed directly into subsequent physical forecasting.  Covariances are
        evaluated in water-depth space to avoid district-area scale artefacts.
        The observation-induced volume increment is reported explicitly: EnSRF is
        an information correction and is not falsely presented as a physical flux.
        """

        storage = np.asarray(ensemble_storage_m3, dtype=float)
        if storage.ndim != 2 or storage.shape[1] != self.n_districts or storage.shape[0] < 2:
            raise ValueError("ensemble_storage_m3 must have shape (members, districts), members >= 2")
        if np.any(~np.isfinite(storage)) or np.any(storage < 0.0):
            raise ValueError("ensemble_storage_m3 must be finite and non-negative")
        if not isinstance(observations_mm, Mapping):
            raise ValueError("observations_mm must be a district mapping")
        unknown = set(observations_mm) - set(self.district_ids)
        if unknown:
            raise ValueError(f"unknown observed districts: {sorted(unknown)}")
        if not np.isfinite(localization_radius_km) or localization_radius_km <= 0.0:
            raise ValueError("localization_radius_km must be finite and positive")

        observed_ids = tuple(sorted((str(key) for key in observations_mm), key=self.index.get))
        obs_indices = np.asarray([self.index[did] for did in observed_ids], dtype=int)
        obs = np.asarray([float(observations_mm[did]) for did in observed_ids], dtype=float)
        if np.any(~np.isfinite(obs)) or np.any(obs < 0.0):
            raise ValueError("observed water depths must be finite and non-negative")

        if isinstance(observation_error_mm, Mapping):
            errors = np.asarray([float(observation_error_mm.get(did, 20.0)) for did in observed_ids])
        else:
            err = np.asarray(observation_error_mm, dtype=float)
            if err.ndim == 0:
                errors = np.full(len(observed_ids), float(err), dtype=float)
            elif err.shape == (len(observed_ids),):
                errors = err
            else:
                raise ValueError("observation_error_mm has the wrong shape")
        if np.any(~np.isfinite(errors)) or np.any(errors <= 0.0):
            raise ValueError("observation errors must be finite and positive")

        if ponding_area_m2 is None:
            pond_area = self.parameters["ponding_area_m2"]
        else:
            pond_area = np.asarray(ponding_area_m2, dtype=float)
            valid_shapes = {(self.n_districts,), storage.shape}
            if pond_area.shape not in valid_shapes or np.any(~np.isfinite(pond_area)) or np.any(pond_area <= 0):
                raise ValueError(
                    "ponding_area_m2 must be a finite positive district vector or member-by-district array"
                )

        if expanded_ponding_area_m2 is None:
            expanded_area = self.parameters["expanded_ponding_area_m2"]
        else:
            expanded_area = np.asarray(expanded_ponding_area_m2, dtype=float)
            valid_shapes = {(self.n_districts,), storage.shape}
            if (
                expanded_area.shape not in valid_shapes
                or np.any(~np.isfinite(expanded_area))
                or np.any(expanded_area <= 0)
            ):
                raise ValueError(
                    "expanded_ponding_area_m2 must be a finite positive district vector or member-by-district array"
                )

        forecast_depth = self.storage_to_depth(
            storage, pond_area, expanded_area, stage_break_mm
        )
        if not observations_mm:
            return {
                "district_ids": self.district_ids,
                "forecast_storage_m3": storage.copy(),
                "analysis_storage_m3": storage.copy(),
                "forecast_depth_mm": forecast_depth,
                "analysis_depth_mm": forecast_depth.copy(),
                "assimilation_increment_m3": np.zeros_like(storage),
                "observed_districts": tuple(),
                "kalman_gain": np.zeros((self.n_districts, 0)),
            }
        members = storage.shape[0]

        # Deterministic serial ensemble square-root filter (EnSRF).  Compared with
        # A deterministic EnSRF avoids the Monte-Carlo noise of a
        # perturbed-observation EnKF in the analysis
        # mean and contracts the observed-node spread predictably.  ``seed`` is
        # retained in the API for backwards-compatible reproducibility metadata.
        analysis_depth = forecast_depth.copy()
        gains = []
        innovations = []
        for k, obs_idx in enumerate(obs_indices):
            mean = analysis_depth.mean(axis=0)
            anomalies = analysis_depth - mean[None, :]
            y_anomaly = anomalies[:, obs_idx]
            forecast_variance = float(y_anomaly @ y_anomaly / (members - 1))
            total_variance = forecast_variance + float(errors[k] ** 2)
            cross_cov = anomalies.T @ y_anomaly / (members - 1)

            localisation = np.exp(
                -((self.distance_km[:, obs_idx] / float(localization_radius_km)) ** 2)
            )
            gain = cross_cov * localisation / total_variance
            innovation = float(obs[k] - mean[obs_idx])
            analysis_mean = mean + gain * innovation

            # Whitaker-Hamill square-root anomaly adjustment.  For the observed
            # component this gives the Kalman posterior variance without adding
            # artificial observation perturbations.
            alpha = 1.0 / (1.0 + math.sqrt(float(errors[k] ** 2) / total_variance))
            analysis_anomalies = anomalies - alpha * y_anomaly[:, None] * gain[None, :]
            analysis_depth = np.maximum(analysis_mean[None, :] + analysis_anomalies, 0.0)
            gains.append(gain)
            innovations.append(innovation)

        kalman_gain = np.column_stack(gains)
        analysis_storage = self.depth_to_storage(
            analysis_depth, pond_area, expanded_area, stage_break_mm
        )
        increment = analysis_storage - storage

        return {
            "district_ids": self.district_ids,
            "observed_districts": observed_ids,
            "forecast_storage_m3": storage.copy(),
            "analysis_storage_m3": analysis_storage,
            "forecast_depth_mm": forecast_depth,
            "analysis_depth_mm": analysis_depth,
            "forecast_mean_depth_mm": forecast_depth.mean(axis=0),
            "analysis_mean_depth_mm": analysis_depth.mean(axis=0),
            "forecast_std_depth_mm": forecast_depth.std(axis=0, ddof=1),
            "analysis_std_depth_mm": analysis_depth.std(axis=0, ddof=1),
            "assimilation_increment_m3": increment,
            "ensemble_total_increment_m3": increment.sum(axis=1),
            "kalman_gain": kalman_gain,
            "innovation_mm": np.asarray(innovations, dtype=float),
            "observation_error_mm": errors,
            "localization_radius_km": float(localization_radius_km),
            "filter": "deterministic serial EnSRF",
            "seed": seed,
            "mass_accounting_note": (
                "assimilation_increment_m3 is an explicit observation correction, not a physical water flux"
            ),
        }


# A ready-to-use singleton and functional wrappers keep integration lightweight.
DEFAULT_MODEL = DistrictStateModel()


def simulate(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return DEFAULT_MODEL.simulate(*args, **kwargs)


def simulate_ensemble(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return DEFAULT_MODEL.simulate_ensemble(*args, **kwargs)


def assimilate_enkf(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return DEFAULT_MODEL.assimilate_enkf(*args, **kwargs)


__all__ = [
    "DEFAULT_AREA_KM2",
    "DEFAULT_THRESHOLDS_MM",
    "PARAMETER_PROVENANCE",
    "FlowEdge",
    "DistrictStateModel",
    "DEFAULT_MODEL",
    "simulate",
    "simulate_ensemble",
    "assimilate_enkf",
]
