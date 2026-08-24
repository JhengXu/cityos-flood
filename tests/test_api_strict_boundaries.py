import json
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from backend.app import accessibility, dispatch, main, shenzhen, userdata


def _snapshot():
    return {"forecast_run_id": "strict-fixture", "times": ["2026-08-24T01:00:00+08:00"]}


class StrictQueryContractTest(unittest.TestCase):
    def test_simulate_get_rejects_unknown_and_repeated_query_keys(self):
        unknown = Request({
            "type": "http",
            "query_string": b"preset=baseline&rainfall_multipler=2",
        })
        with self.assertRaises(HTTPException) as unknown_error:
            main._scenario_request_from_query(
                unknown,
                preset="baseline",
                forecast_run_id=None,
                forecast_days=3,
                scenario_values={},
            )
        self.assertEqual(unknown_error.exception.status_code, 422)
        self.assertIn("rainfall_multipler", unknown_error.exception.detail)

        repeated = Request({
            "type": "http",
            "query_string": b"preset=baseline&preset=extreme",
        })
        with self.assertRaises(HTTPException) as repeated_error:
            main._scenario_request_from_query(
                repeated,
                preset="extreme",
                forecast_run_id=None,
                forecast_days=3,
                scenario_values={},
            )
        self.assertEqual(repeated_error.exception.status_code, 422)
        self.assertIn("preset", repeated_error.exception.detail)

        with self.assertRaises(HTTPException) as empty_preset:
            main._scenario_from_request(main.ScenarioRequest(preset=""))
        self.assertEqual(empty_preset.exception.status_code, 422)

    def test_accessibility_rejects_nonfinite_negative_and_empty_depths(self):
        for value in ("baoan:nan", "baoan:inf", "baoan:-1", "unknown:1", ""):
            with self.subTest(value=value), self.assertRaises(HTTPException) as raised:
                main.get_accessibility(
                    forecast_days=3,
                    forecast_run_id=None,
                    depth_mm=value,
                    damage=None,
                )
            self.assertEqual(raised.exception.status_code, 422)

        for value in ("baoan:nan", "baoan:-0.1", "baoan:0.951"):
            with self.subTest(damage=value), self.assertRaises(HTTPException) as raised:
                main.get_accessibility(
                    forecast_days=3,
                    forecast_run_id=None,
                    depth_mm=None,
                    damage=value,
                )
            self.assertEqual(raised.exception.status_code, 422)

        with self.assertRaises(HTTPException) as mutually_exclusive:
            main.get_accessibility(
                forecast_days=3,
                forecast_run_id=None,
                depth_mm="baoan:1",
                damage="baoan:0.1",
            )
        self.assertEqual(mutually_exclusive.exception.status_code, 422)

    def test_counterfactual_validates_district_format_and_pump_fraction(self):
        depth = {district["id"]: 100.0 for district in shenzhen.DISTRICTS}
        invalid = (
            {"close": "unknown", "pump": None},
            {"close": "baoan,,luohu", "pump": None},
            {"close": None, "pump": "baoan"},
            {"close": None, "pump": "unknown:0.5"},
            {"close": None, "pump": "baoan:-0.1"},
            {"close": None, "pump": "baoan:1.1"},
            {"close": None, "pump": "baoan:nan"},
        )
        for params in invalid:
            with self.subTest(params=params), self.assertRaises(ValueError):
                accessibility.counterfactual(depth, **params)

        with patch(
            "backend.app.main.weather.resolve_snapshot", return_value=_snapshot()
        ), patch(
            "backend.app.main.forecasting.peak_depth_by_district", return_value=depth
        ):
            with self.assertRaises(HTTPException) as raised:
                main.get_counterfactual(
                    forecast_days=3,
                    forecast_run_id="strict-fixture",
                    close=None,
                    pump="baoan:2",
                )
        self.assertEqual(raised.exception.status_code, 422)

    def test_closed_district_is_removed_from_accessibility_graph(self):
        depth = {district["id"]: 0.0 for district in shenzhen.DISTRICTS}
        result = accessibility.counterfactual(depth, close="futian")
        self.assertEqual(result["intervention"]["closed_districts"], ["futian"])
        self.assertTrue(all(
            "futian" not in facility["reachable_districts"]
            for facility in result["intervention"]["facilities"].values()
        ))
        self.assertLessEqual(
            result["intervention"]["city_reachable_pop_share"],
            result["baseline"]["city_reachable_pop_share"],
        )

    def test_realtime_assimilation_contract_fails_invalid_inputs_with_422(self):
        with self.assertRaises(HTTPException) as unknown:
            main.api_assimilate_realtime("unknown", None, None)
        self.assertEqual(unknown.exception.status_code, 422)

        with self.assertRaises(HTTPException) as missing_hour:
            main.api_assimilate_realtime("baoan", 0.3, None)
        self.assertEqual(missing_hour.exception.status_code, 422)

    def test_alert_limit_is_bounded_in_openapi(self):
        parameters = {
            item["name"]: item["schema"]
            for item in main.app.openapi()["paths"]["/api/alerts"]["get"]["parameters"]
        }
        self.assertEqual(parameters["limit"]["minimum"], 1)
        self.assertEqual(parameters["limit"]["maximum"], 200)


class ManualForecastContractTest(unittest.TestCase):
    def test_manual_request_is_strict_and_forbids_extra_fields(self):
        schema = main.ManualForecastRequest.model_json_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), {"district_id", "rainfall"})

        invalid_payloads = (
            {"district_id": "baoan", "rainfall": [1], "unknown": True},
            {"district_id": "baoan", "rainfall": []},
            {"district_id": "baoan", "rainfall": [-1]},
            {"district_id": "baoan", "rainfall": [501]},
            {"district_id": "baoan", "rainfall": [float("nan")]},
            {"district_id": "baoan", "rainfall": [1], "tide_raise": 6},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                main.ManualForecastRequest(**payload)

    def test_manual_unknown_district_is_http_422(self):
        payload = main.ManualForecastRequest(district_id="unknown", rainfall=[0.0])
        with self.assertRaises(HTTPException) as raised:
            main.api_forecast_manual(payload)
        self.assertEqual(raised.exception.status_code, 422)


def _fake_upload(content, filename="events.csv"):
    return UploadFile(io.BytesIO(bytes(content)), filename=filename)


class _FakeRequest:
    def __init__(self, *, content_type="multipart/form-data; boundary=test", form=None, error=None):
        self.headers = {"content-type": content_type}
        self._form = {} if form is None else form
        self._error = error

    async def form(self):
        if self._error:
            raise self._error
        return self._form


class UploadContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_upload_requires_multipart_and_file(self):
        with self.assertRaises(HTTPException) as wrong_type:
            await main.api_data_upload(_FakeRequest(content_type="application/json"))
        self.assertEqual(wrong_type.exception.status_code, 422)

        with self.assertRaises(HTTPException) as missing_file:
            await main.api_data_upload(_FakeRequest(form={}))
        self.assertEqual(missing_file.exception.status_code, 422)

    async def test_upload_stops_at_limit_plus_one_and_returns_413(self):
        upload = _fake_upload(b"12345")
        with patch.object(userdata, "MAX_UPLOAD_BYTES", 4):
            with self.assertRaises(HTTPException) as raised:
                await main.api_data_upload(_FakeRequest(form={"file": upload}))
        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(upload.file.tell(), 5)

    async def test_upload_maps_schema_failure_to_422(self):
        upload = _fake_upload(b"not,a,valid,schema\n")
        with patch(
            "backend.app.main.userdata.upload_data",
            return_value={"status": "error", "hint": "Schema/QC 未通过"},
        ):
            with self.assertRaises(HTTPException) as raised:
                await main.api_data_upload(_FakeRequest(form={"file": upload}))
        self.assertEqual(raised.exception.status_code, 422)


class AlertLogContractTest(unittest.TestCase):
    def test_alert_log_is_rotated_and_read_with_a_bounded_deque(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "alerts.log")
            with patch.object(dispatch, "ALERT_LOG", path), patch.object(
                dispatch, "ALERT_LOG_MAX_BYTES", 1
            ), patch.dict(os.environ, {}, clear=True):
                dispatch.push_alert({"sequence": 1})
                dispatch.push_alert({"sequence": 2})
                self.assertEqual(
                    [item["sequence"] for item in dispatch.get_pushed_alerts(2)],
                    [1, 2],
                )
                with self.assertRaises(ValueError):
                    dispatch.get_pushed_alerts(0)
                with self.assertRaises(ValueError):
                    dispatch.get_pushed_alerts(201)

                with open(path, "a", encoding="utf-8") as handle:
                    for index in range(3, 30):
                        handle.write(json.dumps({"sequence": index}) + "\n")
                self.assertEqual(
                    [item["sequence"] for item in dispatch.get_pushed_alerts(3)],
                    [27, 28, 29],
                )


if __name__ == "__main__":
    unittest.main()
