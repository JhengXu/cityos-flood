import json
import io
from contextlib import redirect_stderr
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from backend.app import demo, userdata


class ValidationTruthfulnessTest(unittest.TestCase):
    def test_legacy_ml_dataset_is_fail_closed_by_default(self):
        from ml import dataset

        with self.assertRaises(dataset.InsufficientIndependentLabels):
            dataset.load()

    def test_legacy_ml_split_rejects_a_single_event(self):
        from ml import dataset

        X = np.zeros((3, 2, 5), dtype=np.float32)
        Y = np.zeros((3, 4), dtype=np.float32)
        metas = [{"event": "same-event"} for _ in range(3)]
        with self.assertRaises(dataset.InsufficientIndependentLabels):
            dataset.split(X, Y, metas)

    def test_legacy_ml_split_keeps_two_events_out_of_both_train_and_test(self):
        from ml import dataset

        X = np.zeros((4, 2, 5), dtype=np.float32)
        Y = np.zeros((4, 4), dtype=np.float32)
        metas = [
            {"event": "event-a"},
            {"event": "event-a"},
            {"event": "event-b"},
            {"event": "event-b"},
        ]
        result = dataset.split(X, Y, metas)
        train_events = {item["event"] for item in result["train_meta"]}
        test_events = {item["event"] for item in result["test_meta"]}
        self.assertTrue(train_events)
        self.assertTrue(test_events)
        self.assertTrue(train_events.isdisjoint(test_events))

    def test_realdata_proxy_labels_require_explicit_opt_in(self):
        from ml import realdata

        with self.assertRaises(realdata.ProxyLabelOptInRequired):
            realdata.build_real_event_samples()
        with self.assertRaises(realdata.ProxyLabelOptInRequired):
            realdata.build_real_event_series()
        with patch.object(realdata, "REAL_DATA_ENABLED", False):
            self.assertEqual(
                realdata.build_real_event_samples(allow_proxy_labels=True), []
            )
            self.assertEqual(
                realdata.build_real_event_series(allow_proxy_labels=True), {}
            )

    def test_realdata_cli_requires_explicit_proxy_label_flag(self):
        from ml import realdata

        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            realdata.main([])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--allow-proxy-labels", stderr.getvalue())

    def test_verify_never_promotes_legacy_report_when_events_are_missing(self):
        readiness = {
            "status": "insufficient-event-coverage",
            "forecast_training_ready": False,
            "independent_flood_events": 0,
        }
        with patch("backend.app.demo.observations.data_readiness", return_value=readiness), patch(
            "backend.app.demo._read_json", return_value={"auc": 0.99}
        ):
            result = demo.get_verify()
        self.assertEqual(result["status"], "insufficient_data")
        self.assertFalse(result["skill_claim_allowed"])
        self.assertTrue(result["legacy_report"]["invalid_for_skill_claim"])
        self.assertEqual(result["legacy_report"]["artifact"]["auc"], 0.99)

    def test_benchmark_is_a_plan_and_does_not_trigger_training(self):
        readiness = {"status": "insufficient-event-coverage", "forecast_training_ready": False}
        with patch("backend.app.demo.observations.data_readiness", return_value=readiness), patch(
            "backend.app.demo._read_json", return_value=None
        ):
            result = demo.get_benchmark()
        self.assertEqual(result["status"], "insufficient_data")
        self.assertFalse(result["training_triggered"])
        self.assertGreaterEqual(len(result["candidates"]), 4)


class UserDataContractTest(unittest.TestCase):
    def test_manual_forecast_uses_reproducible_depth_ensemble(self):
        first = userdata.manual_forecast("baoan", [0, 20, 60, 35, 5], tide_raise=0.2)
        second = userdata.manual_forecast("baoan", [0, 20, 60, 35, 5], tide_raise=0.2)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["trajectory"], second["trajectory"])
        self.assertEqual(first["model"]["family"], "conservative graph state-space parameter ensemble")
        self.assertIn("depth_p50_m", first["trajectory"][0])
        self.assertIn("not calibrated", first["peak_prob_semantics"])
        self.assertTrue(first["audit"]["all_members_conservative"])

    def test_upload_qc_lands_content_without_training(self):
        content = (
            "timestamp,event_id,district_id,rainfall_mm,water_depth_m,available_at\n"
            "2023-09-07T20:00:00+08:00,e1,futian,60,0.20,2023-09-07T20:05:00+08:00\n"
            "2024-04-23T20:00:00+08:00,e2,baoan,40,0.00,2024-04-23T20:05:00+08:00\n"
            "2024-08-19T20:00:00+08:00,e3,yantian,50,0.18,2024-08-19T20:05:00+08:00\n"
        ).encode()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            userdata, "USER_DIR", Path(directory)
        ), patch("backend.app.observations.data_readiness", return_value={"status": "test"}):
            result = userdata.upload_data("events.csv", content)
            csv_path = Path(directory) / result["saved"]
            qc_path = Path(directory) / result["qc_saved"]
            self.assertTrue(csv_path.exists())
            self.assertTrue(qc_path.exists())
            qc = json.loads(qc_path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "saved_not_trained")
        self.assertFalse(result["training_triggered"])
        self.assertTrue(result["readiness"]["eligible_for_model_development"])
        self.assertFalse(result["readiness"]["forecast_skill_claim_ready"])
        self.assertEqual(qc["content_sha256"], result["sha256"])

    def test_binary_only_upload_is_explicitly_not_depth_ready(self):
        content = (
            "timestamp,event_id,district_id,rainfall_mm,flooded\n"
            "2023-09-07T20:00:00+08:00,e1,futian,60,1\n"
        ).encode()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            userdata, "USER_DIR", Path(directory)
        ), patch("backend.app.observations.data_readiness", return_value={"status": "test"}):
            result = userdata.upload_data("binary.csv", content)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["readiness"]["label_mode"], "binary_only_compatibility")
        self.assertFalse(result["readiness"]["depth_supervision_available"])
        self.assertFalse(result["readiness"]["eligible_for_model_development"])

    def test_upload_rejects_naive_time_before_writing(self):
        content = (
            "timestamp,event_id,district_id,rainfall_mm,water_depth_m\n"
            "2023-09-07T20:00:00,e1,futian,60,0.2\n"
        ).encode()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            userdata, "USER_DIR", Path(directory)
        ):
            result = userdata.upload_data("bad.csv", content)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(result["status"], "error")
        self.assertIn("时区", result["hint"])

    def test_upload_rejects_rows_wider_than_header(self):
        content = (
            "timestamp,event_id,district_id,rainfall_mm,water_depth_m\n"
            "2023-09-07T20:00:00+08:00,e1,futian,60,0.2,unexpected\n"
        ).encode()
        with tempfile.TemporaryDirectory() as directory, patch.object(
            userdata, "USER_DIR", Path(directory)
        ):
            result = userdata.upload_data("bad.csv", content)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(result["status"], "error")
        self.assertIn("多于表头", result["hint"])


if __name__ == "__main__":
    unittest.main()
