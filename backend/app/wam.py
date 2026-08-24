# -*- coding: utf-8 -*-
"""Safe model-based decision loop for the district flood WAM.

This module deliberately implements the deployable step *before* learned RL:
an uncertainty-aware finite-horizon CEM planner backed by the exact conservative
world model used by the forecast API.  It exposes an explicit belief state, action
space, reward/cost function, hard-constraint projection, no-regret guard and a
tamper-evident local audit chain.

The returned action is advisory.  Nothing in this module writes to SCADA or an
actuator, and the API truthfully reports that no RL policy has been trained or
deployed.  Historical operator/MPC trajectories can later train a residual RL
policy without changing this safety boundary.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import os
import threading
from typing import Any, Mapping, Optional
import uuid

import numpy as np

from . import forecasting, shenzhen, state_model


WAM_VERSION = "1.0.0-robust-cem-constant-hold-safe-baseline"
POLICY_TYPE = "model_based_robust_cem_constant_hold_baseline"
EXECUTION_MODE = "advisory_only"
RL_STATUS = "not_trained_not_deployed"

DEFAULT_OBJECTIVE_WEIGHTS = {
    "flood": 8.0,
    "severe": 18.0,
    "uncertainty": 2.0,
    "energy": 0.25,
    "mobilization": 0.20,
}
DEFAULT_CONSTRAINTS = {
    "min_control": 0.75,
    "max_control": 1.25,
    "max_first_step_change": 0.25,
    "emergency_budget_mm_h": 45.0,
    "no_regret_max_depth_increase_mm": 5.0,
}
DEFAULT_PLANNER = {
    "method": "robust_cem_constant_hold",
    "population": 32,
    "iterations": 3,
    "elite_fraction": 0.20,
    "seed": None,
}

AUDIT_LOG = os.environ.get("WAM_AUDIT_LOG", "/tmp/cityos_wam_decisions.jsonl")
AUDIT_LOG_MAX_BYTES = 10 * 1024 * 1024
_AUDIT_LOCK = threading.Lock()
_AUDIT_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_AUDIT_CACHE_MAX = 64
_LAST_AUDIT_DIGEST = "GENESIS"
_AUDIT_CHAIN_LOG: Optional[str] = None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(
        _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def technology_stack() -> dict[str, Any]:
    """Describe implemented components separately from the production roadmap."""

    return {
        "loop": "SENSE → ESTIMATE → WORLD MODEL → PLAN → SAFETY SHIELD → APPROVE → AUDIT → LEARN",
        "implemented_now": {
            "state_estimation": "antecedent spin-up + localized EnSRF belief ensemble",
            "world_model": "NumPy conservative ten-node graph state-space model",
            "planner": (
                "finite-horizon robust CEM constant-hold search; every API call replans "
                "from the latest belief state (not a within-call action-sequence MPC)"
            ),
            "action": "district drainage-control multiplier; pump efficiency is an environment/asset state, not an action",
            "reward": "flood depth + severe depth + ensemble uncertainty + energy + mobilization cost",
            "hard_constraints": "equipment bounds + first-step ramp + emergency-capacity budget + risk floor + no-regret guard",
            "safety": "deterministic action projection followed by paired ensemble verification",
            "service": "FastAPI + Pydantic strict request contract",
            "audit": "append-only JSONL with SHA-256 digest chaining (prototype; not a certified WORM store)",
        },
        "production_evolution_not_installed": {
            "streaming_data": "MQTT → Kafka/Redpanda → Flink; Debezium CDC",
            "storage": "TimescaleDB + PostGIS/PostgreSQL + MinIO + Redis",
            "hybrid_dynamics": "PyTorch/JAX learned residual around the conservative transition; Numba/Ray acceleration",
            "control_baselines": "CEM/MPC plus CasADi/CVXPY/OSQP constrained optimization",
            "learned_policy": "offline/residual SAC or PPO after independent event coverage; GNN + CTDE for multi-district control",
            "discrete_resources": "OR-Tools/MILP for mobile pumps, road closures and shelter assignment",
            "serving": "Kubernetes + gRPC + MLflow + BentoML/KServe",
            "observability": "Prometheus/Grafana/OpenTelemetry + certified WORM decision archive",
        },
        "policy_type": POLICY_TYPE,
        "execution_mode": EXECUTION_MODE,
        "rl_status": RL_STATUS,
        "truthfulness_note": (
            "当前运行的是可解释的模型式优化基线，不是已训练强化学习。"
            "只有取得独立暴雨事件、人工调度和 MPC 专家轨迹并通过离线/影子评估后，"
            "才允许把残差 RL 接到同一安全盾之前。"
        ),
        "rollout_path": [
            "Gymnasium 环境契约",
            "奖励与硬约束",
            "CEM/MPC 基线",
            "离线/残差 RL",
            "影子运行",
            "建议模式",
            "低风险有限闭环（高风险长期人工审批）",
        ],
    }


def architecture() -> dict[str, Any]:
    model = state_model.DEFAULT_MODEL
    return {
        "name": "自主优化行动 WAM（强化学习安全演进版）",
        "version": WAM_VERSION,
        "maturity": "stage_3_model_based_finite_horizon_control_baseline",
        "state": {
            "type": "belief_state",
            "variables": [
                "district surface-water storage/depth ensemble",
                "depth rate and uncertainty",
                "forecast district rainfall and tide boundary",
                "pump/asset efficiency",
                "available emergency drainage budget",
            ],
            "districts": list(model.district_ids),
        },
        "environment": {
            "transition": "same conservative state model as /api/predict and /api/simulate",
            "disturbances": ["rainfall", "tide/surge", "asset efficiency", "parameter uncertainty"],
            "mass_balance": "S[t+1]=S[t]+runoff+routed_in-routed_out-drainage-external_outflow",
        },
        "action": {
            "current": "continuous district drainage_control multiplier",
            "not_actions": ["rainfall multiplier", "tide phase", "storm surge", "pump efficiency/health"],
            "future_discrete_optimizer": "mobile pumps / roads / shelters through MILP, not unconstrained RL logits",
        },
        "reward": dict(DEFAULT_OBJECTIVE_WEIGHTS),
        "constraints": dict(DEFAULT_CONSTRAINTS),
        "technology_stack": technology_stack(),
    }


def _merge_config(defaults: Mapping[str, Any], values: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    result = dict(defaults)
    if values:
        unknown = set(values) - set(defaults)
        if unknown:
            raise ValueError(f"unknown configuration fields: {sorted(unknown)}")
        result.update(values)
    return result


def _validate_config(
    weights: Mapping[str, Any], constraints: Mapping[str, Any], planner: Mapping[str, Any]
) -> None:
    if any(not np.isfinite(float(value)) or float(value) < 0.0 for value in weights.values()):
        raise ValueError("objective weights must be finite and non-negative")
    lo = float(constraints["min_control"])
    hi = float(constraints["max_control"])
    ramp = float(constraints["max_first_step_change"])
    budget = float(constraints["emergency_budget_mm_h"])
    no_regret = float(constraints["no_regret_max_depth_increase_mm"])
    if not (0.0 <= lo <= 1.0 <= hi <= 2.0):
        raise ValueError("control bounds must satisfy 0 <= min_control <= 1 <= max_control <= 2")
    if not np.isfinite(ramp) or not 0.0 <= ramp <= 1.0:
        raise ValueError("max_first_step_change must be between 0 and 1")
    if not np.isfinite(budget) or budget < 0.0:
        raise ValueError("emergency_budget_mm_h must be finite and non-negative")
    if not np.isfinite(no_regret) or no_regret < 0.0:
        raise ValueError("no_regret_max_depth_increase_mm must be finite and non-negative")
    if planner["method"] not in {"robust_cem_constant_hold", "cem_mpc"}:
        raise ValueError("planner.method must be 'robust_cem_constant_hold'")
    population = int(planner["population"])
    iterations = int(planner["iterations"])
    elite_fraction = float(planner["elite_fraction"])
    if not 8 <= population <= 128 or not 1 <= iterations <= 8:
        raise ValueError("planner population/iterations are outside safe API bounds")
    if not 0.05 <= elite_fraction <= 0.50:
        raise ValueError("elite_fraction must be between 0.05 and 0.50")


def project_action(
    requested_control: Any,
    *,
    risk_floor_mask: Any,
    drainage_capacity_mm_h: Any,
    constraints: Optional[Mapping[str, Any]] = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Project a raw policy/MPC action onto all currently implemented hard limits."""

    cfg = _merge_config(DEFAULT_CONSTRAINTS, constraints)
    control = np.asarray(requested_control, dtype=float)
    risk_floor = np.asarray(risk_floor_mask, dtype=bool)
    capacity = np.asarray(drainage_capacity_mm_h, dtype=float)
    if control.shape != (state_model.DEFAULT_MODEL.n_districts,):
        raise ValueError("requested_control must contain one value per district")
    if risk_floor.shape != control.shape or capacity.shape != control.shape:
        raise ValueError("risk floor and capacity vectors must match requested_control")
    if np.any(~np.isfinite(control)) or np.any(~np.isfinite(capacity)) or np.any(capacity < 0.0):
        raise ValueError("action and capacity values must be finite; capacity must be non-negative")

    requested = control.copy()
    lo = max(float(cfg["min_control"]), 1.0 - float(cfg["max_first_step_change"]))
    hi = min(float(cfg["max_control"]), 1.0 + float(cfg["max_first_step_change"]))
    control = np.clip(control, lo, hi)
    # When forecast demand already exceeds design capacity or the baseline is
    # actionable, saving energy may not reduce the nominal operating level.
    control[risk_floor] = np.maximum(control[risk_floor], 1.0)

    extra_before = np.maximum(control - 1.0, 0.0) * capacity
    budget = float(cfg["emergency_budget_mm_h"])
    total_before = float(np.sum(extra_before))
    if total_before > budget and total_before > 0.0:
        scale = budget / total_before
        control = np.where(control > 1.0, 1.0 + (control - 1.0) * scale, control)

    extra_after = np.maximum(control - 1.0, 0.0) * capacity
    corrections = []
    for index, did in enumerate(state_model.DEFAULT_MODEL.district_ids):
        if abs(float(requested[index] - control[index])) > 1e-9:
            corrections.append({
                "district_id": did,
                "requested": round(float(requested[index]), 4),
                "projected": round(float(control[index]), 4),
            })
    satisfied = {
        "equipment_bounds": bool(np.all((control >= lo - 1e-12) & (control <= hi + 1e-12))),
        "first_step_ramp": bool(np.all(np.abs(control - 1.0) <= float(cfg["max_first_step_change"]) + 1e-12)),
        "risk_floor": bool(np.all(control[risk_floor] >= 1.0 - 1e-12)),
        "emergency_budget": bool(float(np.sum(extra_after)) <= budget + 1e-9),
    }
    return control, {
        "requested": [round(float(value), 4) for value in requested],
        "projected": [round(float(value), 4) for value in control],
        "corrections": corrections,
        "risk_floor_districts": [
            did for did, active in zip(state_model.DEFAULT_MODEL.district_ids, risk_floor) if active
        ],
        "effective_bounds": {"min": round(lo, 4), "max": round(hi, 4)},
        "emergency_budget_mm_h": round(budget, 4),
        "requested_emergency_use_mm_h": round(total_before, 4),
        "projected_emergency_use_mm_h": round(float(np.sum(extra_after)), 4),
        "constraints_satisfied": satisfied,
        "feasible": bool(all(satisfied.values())),
    }


def _rollout_members(context: Mapping[str, Any], control: np.ndarray, member_indices: np.ndarray) -> dict[str, Any]:
    model = state_model.DEFAULT_MODEL
    horizon = int(context["horizon_hours"])
    control_matrix = np.repeat(control[None, :], horizon, axis=0)
    depths = []
    audits = []
    sampled = context["sampled_parameters"]
    initial = context["initial_depth_members_mm"]
    for member in member_indices:
        overrides = {key: np.asarray(values[member], dtype=float) for key, values in sampled.items()}
        result = model.simulate(
            context["rainfall"],
            tide_m=context["tide_m"],
            pump_efficiency=float(context["pump_efficiency"]),
            drainage_control=control_matrix,
            initial_depth_mm=initial[member],
            parameter_overrides=overrides,
        )
        depths.append(result["depth_mm"])
        audits.append(result["audit"])
    return {"depth_mm": np.asarray(depths, dtype=float), "audits": audits}


def _score_rollout(
    rollout: Mapping[str, Any], control: np.ndarray, weights: Mapping[str, Any]
) -> dict[str, float]:
    depth = np.asarray(rollout["depth_mm"], dtype=float)
    # Penalise every positive depth continuously; otherwise an optimizer can
    # intentionally fill storage up to 149 mm merely because the alert
    # threshold is 150 mm.  A separate severe term adds curvature above 300 mm.
    flood_excess = np.maximum(depth, 0.0) / 150.0
    severe_excess = np.maximum(depth - 300.0, 0.0) / 300.0
    p50 = np.quantile(depth, 0.50, axis=0)
    p90 = np.quantile(depth, 0.90, axis=0)
    components = {
        "flood": float(np.mean(np.square(flood_excess))),
        "severe": float(np.mean(np.square(severe_excess))),
        "uncertainty": float(np.mean(np.maximum(p90 - p50, 0.0) / 150.0)),
        "energy": float(np.mean(np.square(control))),
        "mobilization": float(np.mean(np.abs(control - 1.0))),
    }
    weighted = {key: float(weights[key]) * value for key, value in components.items()}
    total_cost = float(sum(weighted.values()))
    return {
        **{f"{key}_cost": round(value, 8) for key, value in components.items()},
        **{f"weighted_{key}": round(value, 8) for key, value in weighted.items()},
        "total_cost": round(total_cost, 8),
        "total_reward": round(-total_cost, 8),
    }


def _rollout_summary(rollout: Mapping[str, Any], score: Mapping[str, float]) -> dict[str, Any]:
    depth = np.asarray(rollout["depth_mm"], dtype=float)
    p10, p50, p90 = np.quantile(depth, (0.10, 0.50, 0.90), axis=0)
    exceed = np.mean(depth >= 150.0, axis=0)
    districts = []
    for index, district in enumerate(shenzhen.DISTRICTS):
        districts.append({
            "district_id": district["id"],
            "name": district["name"],
            "peak_depth_p10_m": round(float(np.max(p10[:, index])) / 1000.0, 4),
            "peak_depth_p50_m": round(float(np.max(p50[:, index])) / 1000.0, 4),
            "peak_depth_p90_m": round(float(np.max(p90[:, index])) / 1000.0, 4),
            "peak_probability_gt_0_15m": round(float(np.max(exceed[:, index])), 4),
            "hours_p50_above_0_15m": int(np.sum(p50[:, index] >= 150.0)),
        })
    city_peak_p50_m = round(float(np.max(p50)) / 1000.0, 4)
    max_probability = round(float(np.max(exceed)), 4)
    return {
        "city_peak_depth_p50_m": city_peak_p50_m,
        "city_peak_depth_m": city_peak_p50_m,
        "city_peak_depth_p90_m": round(float(np.max(p90)) / 1000.0, 4),
        "max_probability_gt_0_15m": max_probability,
        "prob_depth_ge_15cm": max_probability,
        "objective_cost": float(score["total_cost"]),
        "districts": districts,
        "objective": dict(score),
        "mass_balance": {
            "all_members_conservative": all(item["conservative"] for item in rollout["audits"]),
            "max_abs_closure_error_m3": round(
                max(abs(float(item["closure_error_m3"])) for item in rollout["audits"]), 6
            ),
        },
    }


def _context(snapshot: Mapping[str, Any], horizon_hours: int, pump_efficiency: float) -> dict[str, Any]:
    times = list(snapshot.get("times") or [])
    horizon = min(int(horizon_hours), len(times))
    if horizon < 1:
        raise ValueError("forecast snapshot contains no future time steps")
    # Sixteen paired members are kept for final safety verification.  Four
    # evenly-spaced members are used inside CEM so interactive latency remains
    # bounded while still optimizing against parameter/state uncertainty.
    ensemble, boundary, observations = forecasting.ensemble_for_snapshot(snapshot, n_members=16)
    rainfall = {
        did: np.asarray(snapshot["districts"][did][:horizon], dtype=float)
        for did in state_model.DEFAULT_MODEL.district_ids
    }
    return {
        "forecast_run_id": snapshot.get("forecast_run_id"),
        "times": times[:horizon],
        "requested_horizon_hours": int(horizon_hours),
        "horizon_hours": horizon,
        "rainfall": rainfall,
        "tide_m": np.asarray(boundary["total_level_m"][:horizon], dtype=float),
        "pump_efficiency": float(pump_efficiency),
        "initial_depth_members_mm": np.asarray(ensemble["members_initial_depth_mm"], dtype=float),
        "sampled_parameters": ensemble["sampled_parameters"],
        "parameter_ensemble_id": ensemble["parameter_ensemble_id"],
        "initial_analysis": ensemble["initial_analysis"],
        "observations": observations,
        "all_member_indices": np.arange(int(ensemble["n_members"]), dtype=int),
        "planning_member_indices": np.unique(
            np.linspace(0, int(ensemble["n_members"]) - 1, 4, dtype=int)
        ),
    }


def _belief_state(context: Mapping[str, Any], baseline: Mapping[str, Any]) -> dict[str, Any]:
    initial = np.asarray(context["initial_depth_members_mm"], dtype=float)
    baseline_depth = np.asarray(baseline["depth_mm"], dtype=float)
    baseline_p50 = np.quantile(baseline_depth, 0.50, axis=0)
    baseline_p90 = np.quantile(baseline_depth, 0.90, axis=0)
    capacity = state_model.DEFAULT_MODEL.parameters["drainage_capacity_mm_h"]
    districts = []
    for index, district in enumerate(shenzhen.DISTRICTS):
        rain = np.asarray(context["rainfall"][district["id"]], dtype=float)
        districts.append({
            "district_id": district["id"],
            "name": district["name"],
            "initial_depth_mean_m": round(float(np.mean(initial[:, index])) / 1000.0, 4),
            "initial_depth_std_m": round(float(np.std(initial[:, index])) / 1000.0, 4),
            "baseline_peak_p50_m": round(float(np.max(baseline_p50[:, index])) / 1000.0, 4),
            "baseline_peak_p90_m": round(float(np.max(baseline_p90[:, index])) / 1000.0, 4),
            "max_rainfall_mm_h": round(float(np.max(rain)), 2),
            "design_drainage_mm_h": round(float(capacity[index]), 2),
            "pump_efficiency": round(float(context["pump_efficiency"]), 4),
        })
    return {
        "type": "ensemble_belief_state",
        "analysis": context["initial_analysis"],
        "fresh_observations": context["observations"],
        "districts": districts,
    }


def _last_persisted_audit_digest(path: str) -> str:
    """Recover the latest valid digest so a process restart continues the chain."""

    for candidate in (path, f"{path}.1"):
        last_digest = None
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except (TypeError, ValueError):
                        continue
                    digest = item.get("digest_sha256")
                    if isinstance(digest, str) and digest:
                        last_digest = digest
        except OSError:
            continue
        if last_digest:
            return last_digest
    return "GENESIS"


def _append_audit(record: dict[str, Any]) -> dict[str, Any]:
    global _LAST_AUDIT_DIGEST, _AUDIT_CHAIN_LOG
    with _AUDIT_LOCK:
        if _AUDIT_CHAIN_LOG != AUDIT_LOG:
            _LAST_AUDIT_DIGEST = _last_persisted_audit_digest(AUDIT_LOG)
            _AUDIT_CHAIN_LOG = AUDIT_LOG
        previous = _LAST_AUDIT_DIGEST
        payload = _jsonable({**record, "previous_digest": previous})
        digest = _digest(payload)
        stored = {**payload, "digest_sha256": digest}
        _LAST_AUDIT_DIGEST = digest
        _AUDIT_CACHE[stored["decision_run_id"]] = stored
        _AUDIT_CACHE.move_to_end(stored["decision_run_id"])
        while len(_AUDIT_CACHE) > _AUDIT_CACHE_MAX:
            _AUDIT_CACHE.popitem(last=False)
        try:
            current_size = os.path.getsize(AUDIT_LOG) if os.path.exists(AUDIT_LOG) else 0
            encoded = (json.dumps(stored, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            if current_size and current_size + len(encoded) > AUDIT_LOG_MAX_BYTES:
                os.replace(AUDIT_LOG, f"{AUDIT_LOG}.1")
            with open(AUDIT_LOG, "ab") as handle:
                handle.write(encoded)
        except OSError:
            stored["persistence_warning"] = "local audit log write failed; in-memory audit retained"
        return stored


def get_audit(decision_run_id: str) -> Optional[dict[str, Any]]:
    key = str(decision_run_id)
    with _AUDIT_LOCK:
        cached = _AUDIT_CACHE.get(key)
        if cached is not None:
            return dict(cached)
        for path in (AUDIT_LOG, f"{AUDIT_LOG}.1"):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            item = json.loads(line)
                        except (TypeError, ValueError):
                            continue
                        if item.get("decision_run_id") == key:
                            return item
            except OSError:
                continue
    return None


def optimize(snapshot: Mapping[str, Any], config: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Search one safe constant-hold action over a finite planning horizon.

    Calling the endpoint again with the next belief state provides rolling
    replanning.  This implementation does not claim to optimize a within-call
    sequence of future actions as a strict receding-horizon MPC would.
    """

    request = dict(config or {})
    weights = _merge_config(DEFAULT_OBJECTIVE_WEIGHTS, request.get("objective_weights"))
    constraints = _merge_config(DEFAULT_CONSTRAINTS, request.get("constraints"))
    planner = _merge_config(DEFAULT_PLANNER, request.get("planner"))
    _validate_config(weights, constraints, planner)
    horizon_requested = int(request.get("horizon_hours", 24))
    if not 6 <= horizon_requested <= 72:
        raise ValueError("horizon_hours must be between 6 and 72")
    pump_efficiency = float(request.get("pump_efficiency", 1.0))
    if not np.isfinite(pump_efficiency) or not 0.0 <= pump_efficiency <= 1.0:
        raise ValueError("pump_efficiency must be between 0 and 1")

    context = _context(snapshot, horizon_requested, pump_efficiency)
    model = state_model.DEFAULT_MODEL
    capacity = np.asarray(model.parameters["drainage_capacity_mm_h"], dtype=float)
    all_indices = context["all_member_indices"]
    planning_indices = context["planning_member_indices"]
    nominal = np.ones(model.n_districts, dtype=float)
    baseline_rollout = _rollout_members(context, nominal, all_indices)
    baseline_plan_rollout = {
        "depth_mm": np.asarray(baseline_rollout["depth_mm"])[planning_indices],
        "audits": [baseline_rollout["audits"][int(i)] for i in planning_indices],
    }
    baseline_plan_score = _score_rollout(baseline_plan_rollout, nominal, weights)

    baseline_p50 = np.quantile(baseline_rollout["depth_mm"], 0.50, axis=0)
    peak_rain = np.asarray([
        np.max(context["rainfall"][did]) for did in model.district_ids
    ])
    risk_floor = (np.max(baseline_p50, axis=0) >= 150.0) | (peak_rain >= capacity)

    seed = planner.get("seed")
    if seed is None:
        seed = forecasting.stable_seed(
            context["forecast_run_id"], WAM_VERSION, horizon_requested,
            planner["population"], planner["iterations"], pump_efficiency,
        )
    rng = np.random.default_rng(int(seed))
    population = int(planner["population"])
    elite_count = max(2, int(np.ceil(population * float(planner["elite_fraction"]))))
    mean = np.where(risk_floor, 1.10, 0.95).astype(float)
    std = np.full(model.n_districts, 0.14, dtype=float)
    best_raw = nominal.copy()
    best_control = nominal.copy()
    best_score = baseline_plan_score
    best_projection = project_action(
        nominal,
        risk_floor_mask=risk_floor,
        drainage_capacity_mm_h=capacity,
        constraints=constraints,
    )[1]
    convergence = []

    for iteration in range(int(planner["iterations"])):
        samples = rng.normal(mean, std, size=(population, model.n_districts))
        samples[0] = nominal
        samples[1] = mean
        evaluated = []
        for raw in samples:
            projected, projection = project_action(
                raw,
                risk_floor_mask=risk_floor,
                drainage_capacity_mm_h=capacity,
                constraints=constraints,
            )
            rollout = _rollout_members(context, projected, planning_indices)
            score = _score_rollout(rollout, projected, weights)
            evaluated.append((float(score["total_cost"]), raw.copy(), projected, score, projection))
        evaluated.sort(key=lambda item: item[0])
        elites = evaluated[:elite_count]
        elite_controls = np.asarray([item[2] for item in elites], dtype=float)
        mean = np.mean(elite_controls, axis=0)
        std = np.maximum(np.std(elite_controls, axis=0), 0.015)
        if elites[0][0] < float(best_score["total_cost"]):
            _, best_raw, best_control, best_score, best_projection = elites[0]
        convergence.append({
            "iteration": iteration + 1,
            "best_cost": round(float(elites[0][0]), 8),
            "elite_mean_cost": round(float(np.mean([item[0] for item in elites])), 8),
            "sampling_std_mean": round(float(np.mean(std)), 6),
        })

    optimized_rollout = _rollout_members(context, best_control, all_indices)
    baseline_final_score = _score_rollout(baseline_rollout, nominal, weights)
    optimized_final_score = _score_rollout(optimized_rollout, best_control, weights)

    # Paired-ensemble no-regret guard is independent of the optimizer reward.
    # If any district becomes materially deeper, the shield rejects the whole
    # candidate and falls back to nominal control.  This is intentionally
    # conservative for a research prototype without actuator feedback.
    baseline_p90 = np.quantile(baseline_rollout["depth_mm"], 0.90, axis=0)
    optimized_p90 = np.quantile(optimized_rollout["depth_mm"], 0.90, axis=0)
    allowed = float(constraints["no_regret_max_depth_increase_mm"])
    increases = np.max(optimized_p90 - baseline_p90, axis=0)
    rejected = [
        model.district_ids[index] for index in np.flatnonzero(increases > allowed + 1e-9)
    ]
    no_regret_fallback = bool(rejected)
    if no_regret_fallback:
        best_control = nominal.copy()
        optimized_rollout = baseline_rollout
        optimized_final_score = baseline_final_score
        best_projection = project_action(
            best_raw,
            risk_floor_mask=risk_floor,
            drainage_capacity_mm_h=capacity,
            constraints=constraints,
        )[1]
        best_projection["no_regret_override"] = {
            "applied": True,
            "rejected_districts": rejected,
            "fallback": "nominal_control_1.0",
        }
        best_projection["projected"] = [1.0] * model.n_districts
        best_projection["corrections"] = [
            {
                "district_id": did,
                "requested": round(float(best_raw[index]), 4),
                "projected": 1.0,
            }
            for index, did in enumerate(model.district_ids)
            if abs(float(best_raw[index]) - 1.0) > 1e-9
        ]
        best_projection["projected_emergency_use_mm_h"] = 0.0
    else:
        best_projection["no_regret_override"] = {"applied": False, "rejected_districts": []}
    best_projection["hard_violations"] = sum(
        not bool(value) for value in best_projection["constraints_satisfied"].values()
    )
    best_projection["feasible"] = best_projection["hard_violations"] == 0

    baseline_summary = _rollout_summary(baseline_rollout, baseline_final_score)
    optimized_summary = _rollout_summary(optimized_rollout, optimized_final_score)
    reward_components = {}
    for key in ("flood", "severe", "uncertainty", "energy", "mobilization"):
        before = float(baseline_final_score[f"weighted_{key}"])
        after = float(optimized_final_score[f"weighted_{key}"])
        reward_components[key] = {
            "baseline": round(before, 8),
            "optimized": round(after, 8),
            "delta": round(before - after, 8),
        }
    reward_components["total"] = {
        "baseline": float(baseline_final_score["total_cost"]),
        "optimized": float(optimized_final_score["total_cost"]),
        "delta": round(
            float(baseline_final_score["total_cost"] - optimized_final_score["total_cost"]), 8
        ),
    }
    action_plan = []
    for index, district in enumerate(shenzhen.DISTRICTS):
        value = float(best_control[index])
        if value > 1.02:
            reason = "提高排涝负荷，降低集合积水峰值"
        elif value < 0.98:
            reason = "低风险窗口节能运行；仍受成对集合无恶化护栏约束"
        else:
            reason = "保持标称排涝负荷"
        baseline_district = baseline_summary["districts"][index]
        action_plan.append({
            "district_id": district["id"],
            "name": district["name"],
            "requested_control": round(float(best_raw[index]), 4),
            "projected_control": round(value, 4),
            "nominal_capacity_mm_h": round(float(capacity[index]), 2),
            "effective_capacity_mm_h": round(float(capacity[index] * value), 2),
            "temporary_capacity_equivalent_mm_h": round(float(max(value - 1.0, 0.0) * capacity[index]), 2),
            "reason": reason,
            "approval_required": bool(
                value > 1.15 or baseline_district["peak_depth_p90_m"] >= 0.30
            ),
        })

    decision_payload = {
        "forecast_run_id": context["forecast_run_id"],
        "wam_version": WAM_VERSION,
        "horizon_hours": context["horizon_hours"],
        "requested_horizon_hours": context["requested_horizon_hours"],
        "planner": {**planner, "seed": int(seed)},
        "objective_weights": weights,
        "constraints": constraints,
        "pump_efficiency": pump_efficiency,
        "projected_control": best_control,
    }
    decision_fingerprint = _digest(decision_payload)[:20]
    created_at = datetime.now(timezone.utc).isoformat()
    decision_run_id = _digest({
        "decision_fingerprint": decision_fingerprint,
        "created_at": created_at,
        "nonce": uuid.uuid4().hex,
    })[:20]
    audit_record = _append_audit({
        "decision_run_id": decision_run_id,
        "decision_fingerprint": decision_fingerprint,
        "created_at": created_at,
        "forecast_run_id": context["forecast_run_id"],
        "parameter_ensemble_id": context["parameter_ensemble_id"],
        "world_model_version": forecasting.MODEL_VERSION,
        "wam_version": WAM_VERSION,
        "request": decision_payload,
        "state_digest_sha256": _digest(_belief_state(context, baseline_rollout)),
        "action_digest_sha256": _digest(action_plan),
        "baseline_digest_sha256": _digest(baseline_summary),
        "optimized_digest_sha256": _digest(optimized_summary),
        "safety_projection": best_projection,
        "execution_mode": EXECUTION_MODE,
        "approval": "not_requested",
        "execution_result": "not_executed",
    })

    return {
        "decision_run_id": decision_run_id,
        "decision_fingerprint": decision_fingerprint,
        "generated_at": created_at,
        "forecast_run_id": context["forecast_run_id"],
        "parameter_ensemble_id": context["parameter_ensemble_id"],
        "world_model_version": forecasting.MODEL_VERSION,
        "wam_version": WAM_VERSION,
        "policy_type": POLICY_TYPE,
        "execution_mode": EXECUTION_MODE,
        "rl_status": RL_STATUS,
        "requested_horizon_hours": context["requested_horizon_hours"],
        "horizon_hours": context["horizon_hours"],
        "horizon_truncated_to_snapshot": (
            context["horizon_hours"] < context["requested_horizon_hours"]
        ),
        "times": context["times"],
        "belief_state": _belief_state(context, baseline_rollout),
        "baseline": baseline_summary,
        "optimized": optimized_summary,
        "reward_breakdown": {
            "components": reward_components,
            "cost_reduction_total": reward_components["total"]["delta"],
            "semantics": "positive delta means lower cost than nominal control",
        },
        "action_plan": action_plan,
        "safety_projection": best_projection,
        "constraints": {
            **constraints,
            "risk_floor_districts": best_projection["risk_floor_districts"],
            "all_satisfied": bool(all(best_projection["constraints_satisfied"].values())),
            "no_regret_guard_passed": not no_regret_fallback,
        },
        "planner": {
            "method": "finite_horizon_robust_cem_constant_hold",
            "requested_method": planner["method"],
            "resolved_method": "robust_cem_constant_hold",
            "deprecated_alias_used": planner["method"] == "cem_mpc",
            "rolling_replan": "call again when a new belief state is available",
            "within_call_action_sequence_optimized": False,
            "population": population,
            "iterations": int(planner["iterations"]),
            "elite_count": elite_count,
            "planning_ensemble_members": len(planning_indices),
            "safety_verification_members": len(all_indices),
            "seed": int(seed),
            "convergence": convergence,
        },
        "audit": {
            "decision_run_id": decision_run_id,
            "decision_fingerprint": decision_fingerprint,
            "forecast_run_id": context["forecast_run_id"],
            "world_model_version": forecasting.MODEL_VERSION,
            "planner": "finite_horizon_robust_cem_constant_hold",
            "request_method": planner["method"],
            "seed": int(seed),
            "candidate_count": population * int(planner["iterations"]),
            "generated_at": created_at,
            "digest_sha256": audit_record["digest_sha256"],
            "previous_digest": audit_record["previous_digest"],
            "storage": "append_only_local_jsonl_prototype",
            "retrieval": f"/api/wam/audits/{decision_run_id}",
        },
        "candidate_count": population * int(planner["iterations"]),
        "hard_violations": sum(
            not bool(value) for value in best_projection["constraints_satisfied"].values()
        ),
        "technology_stack": technology_stack(),
        "quality_flags": [
            "uncalibrated_world_model_parameters",
            "district_scale_not_asset_level_control",
            "robust_cem_baseline_not_reinforcement_learning",
            "finite_horizon_constant_hold_not_action_sequence_mpc",
            "advisory_only_no_scada_write",
            "local_audit_not_certified_worm",
        ],
    }


__all__ = [
    "WAM_VERSION",
    "POLICY_TYPE",
    "EXECUTION_MODE",
    "RL_STATUS",
    "DEFAULT_OBJECTIVE_WEIGHTS",
    "DEFAULT_CONSTRAINTS",
    "DEFAULT_PLANNER",
    "architecture",
    "technology_stack",
    "project_action",
    "optimize",
    "get_audit",
]
