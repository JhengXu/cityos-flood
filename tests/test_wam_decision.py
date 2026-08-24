import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from pydantic import ValidationError

from backend.app import main, shenzhen, state_model, wam


def fixture_snapshot(hours=8):
    start = datetime(2026, 8, 24, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    times = [(start + timedelta(hours=index)).isoformat() for index in range(hours)]
    event = np.asarray([0, 10, 35, 60, 40, 15, 3, 0], dtype=float)[:hours]
    districts = {}
    cumulative = {}
    for index, district in enumerate(shenzhen.DISTRICTS):
        values = (event * (0.90 + 0.02 * index)).tolist()
        districts[district["id"]] = values
        cumulative[district["id"]] = np.cumsum(values).tolist()
    return {
        "times": times,
        "city": np.mean(np.asarray(list(districts.values())), axis=0).tolist(),
        "districts": districts,
        "cum": cumulative,
        "fallback": False,
        "forecast_run_id": f"wam-fixture-{hours}",
        "issued_at": "2026-08-23T23:00:00+08:00",
    }


class SafetyProjectionTest(unittest.TestCase):
    def test_projection_enforces_bounds_risk_floor_ramp_and_budget(self):
        model = state_model.DEFAULT_MODEL
        requested = np.full(model.n_districts, 2.0)
        risk_floor = np.ones(model.n_districts, dtype=bool)
        capacity = model.parameters["drainage_capacity_mm_h"]
        projected, audit = wam.project_action(
            requested,
            risk_floor_mask=risk_floor,
            drainage_capacity_mm_h=capacity,
            constraints={
                **wam.DEFAULT_CONSTRAINTS,
                "max_control": 1.20,
                "max_first_step_change": 0.10,
                "emergency_budget_mm_h": 2.0,
            },
        )
        self.assertTrue(np.all(projected >= 1.0))
        self.assertTrue(np.all(projected <= 1.10 + 1e-12))
        self.assertLessEqual(audit["projected_emergency_use_mm_h"], 2.0)
        self.assertTrue(audit["feasible"])
        self.assertTrue(all(audit["constraints_satisfied"].values()))
        self.assertEqual(len(audit["risk_floor_districts"]), 10)

    def test_continuous_flood_cost_penalizes_subthreshold_depth(self):
        depth = np.full((2, 3, 10), 100.0)
        rollout = {"depth_mm": depth, "audits": []}
        score = wam._score_rollout(
            rollout, np.ones(10), wam.DEFAULT_OBJECTIVE_WEIGHTS
        )
        self.assertGreater(score["flood_cost"], 0.0)
        self.assertEqual(score["severe_cost"], 0.0)


class WAMOptimizationTest(unittest.TestCase):
    def test_optimizer_is_safe_auditable_and_truthful_about_rl(self):
        snapshot = fixture_snapshot()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            wam, "AUDIT_LOG", str(Path(directory) / "wam-audit.jsonl")
        ), patch(
            "backend.app.forecasting.observations.latest_district_observations",
            return_value={},
        ):
            result = wam.optimize(
                snapshot,
                {
                    "horizon_hours": 6,
                    "planner": {
                        "method": "cem_mpc",
                        "population": 8,
                        "iterations": 1,
                        "elite_fraction": 0.25,
                        "seed": 7,
                    },
                },
            )
            stored = wam.get_audit(result["decision_run_id"])

        self.assertEqual(result["forecast_run_id"], "wam-fixture-8")
        self.assertEqual(result["execution_mode"], "advisory_only")
        self.assertEqual(result["rl_status"], "not_trained_not_deployed")
        self.assertEqual(
            result["policy_type"], "model_based_robust_cem_constant_hold_baseline"
        )
        self.assertFalse(result["planner"]["within_call_action_sequence_optimized"])
        self.assertEqual(result["candidate_count"], 8)
        self.assertEqual(result["safety_projection"]["hard_violations"], 0)
        self.assertEqual(len(result["action_plan"]), 10)
        self.assertTrue(result["baseline"]["mass_balance"]["all_members_conservative"])
        self.assertTrue(result["optimized"]["mass_balance"]["all_members_conservative"])
        self.assertIn("flood", result["reward_breakdown"]["components"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["decision_run_id"], result["decision_run_id"])
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_architecture_separates_implemented_baseline_from_future_stack(self):
        spec = wam.architecture()
        stack = spec["technology_stack"]
        self.assertEqual(stack["rl_status"], "not_trained_not_deployed")
        self.assertIn("implemented_now", stack)
        self.assertIn("production_evolution_not_installed", stack)
        self.assertIn("constant-hold", stack["implemented_now"]["planner"])

    def test_repeated_equivalent_decisions_have_unique_audit_ids_and_shared_fingerprint(self):
        snapshot = fixture_snapshot()
        config = {
            "horizon_hours": 6,
            "planner": {
                "method": "robust_cem_constant_hold",
                "population": 8,
                "iterations": 1,
                "elite_fraction": 0.25,
                "seed": 11,
            },
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            wam, "AUDIT_LOG", str(Path(directory) / "wam-audit.jsonl")
        ), patch(
            "backend.app.forecasting.observations.latest_district_observations",
            return_value={},
        ):
            first = wam.optimize(snapshot, config)
            second = wam.optimize(snapshot, config)
            first_record = wam.get_audit(first["decision_run_id"])
            second_record = wam.get_audit(second["decision_run_id"])

        self.assertNotEqual(first["decision_run_id"], second["decision_run_id"])
        self.assertEqual(first["decision_fingerprint"], second["decision_fingerprint"])
        self.assertEqual(
            second_record["previous_digest"], first_record["digest_sha256"]
        )


class WAMApiContractTest(unittest.TestCase):
    def test_request_is_strict_and_bounded(self):
        schema = main.WAMOptimizeRequest.model_json_schema()
        self.assertFalse(schema["additionalProperties"])
        with self.assertRaises(ValidationError):
            main.WAMOptimizeRequest(unknown=True)
        with self.assertRaises(ValidationError):
            main.WAMOptimizeRequest(horizon_hours=5)
        with self.assertRaises(ValidationError):
            main.WAMOptimizeRequest(planner={"method": "ppo"})

    def test_route_resolves_pinned_snapshot_and_forwards_safe_config(self):
        snapshot = fixture_snapshot()
        expected = {
            "forecast_run_id": snapshot["forecast_run_id"],
            "execution_mode": "advisory_only",
        }
        payload = main.WAMOptimizeRequest(
            forecast_run_id=snapshot["forecast_run_id"], forecast_days=1
        )
        with patch(
            "backend.app.main.weather.resolve_snapshot", return_value=snapshot
        ) as resolve, patch("backend.app.main.wam.optimize", return_value=expected) as optimize:
            result = main.optimize_wam_action(payload)
        resolve.assert_called_once_with(1, snapshot["forecast_run_id"])
        forwarded = optimize.call_args.args[1]
        self.assertNotIn("forecast_run_id", forwarded)
        self.assertNotIn("forecast_days", forwarded)
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()
