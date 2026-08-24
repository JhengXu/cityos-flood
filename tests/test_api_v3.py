import base64
import json
import inspect
import os
import struct
import subprocess
import sys
import unittest
import zlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException, Request

from backend.app import (
    assimilation,
    forecasting,
    gridrisk,
    main,
    realdatav,
    shenzhen,
    simulate,
    streets,
    weather,
)


def fixture_snapshot(hours=18):
    start = datetime(2026, 8, 24, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    times = [(start + timedelta(hours=i)).isoformat() for i in range(hours)]
    event = np.asarray([0, 4, 14, 28, 45, 52, 38, 24, 12, 5, 1, 0], dtype=float)
    shape = np.zeros(hours, dtype=float)
    shape[: min(hours, len(event))] = event[:hours]
    districts = {}
    cum = {}
    for index, district in enumerate(shenzhen.DISTRICTS):
        values = np.maximum(0.0, shape * (0.90 + index * 0.02)).tolist()
        districts[district["id"]] = values
        cum[district["id"]] = [float(sum(values[max(0, i - 24) : i])) for i in range(hours)]
    city = np.mean(np.asarray(list(districts.values())), axis=0).tolist()
    return {
        "times": times,
        "city": city,
        "city_cum": [float(sum(city[max(0, i - 24) : i])) for i in range(hours)],
        "districts": districts,
        "cum": cum,
        "fallback": False,
        "forecast_run_id": f"fixture-{hours}",
        "issued_at": "2026-08-23T23:00:00+08:00",
    }


def with_antecedent(snapshot, rain_mm_h=0.0):
    result = deepcopy(snapshot)
    first = datetime.fromisoformat(result["times"][0])
    antecedent_times = [
        (first - timedelta(hours=24 - index)).isoformat() for index in range(24)
    ]
    values = [float(rain_mm_h)] * 24
    result.update({
        "antecedent_times": antecedent_times,
        "antecedent_city": values,
        "antecedent_districts": {
            district["id"]: list(values) for district in shenzhen.DISTRICTS
        },
        "antecedent_provenance": "estimated(test preceding-hour forcing)",
        "antecedent_complete": True,
        "antecedent_interval_semantics": (
            "timestamp is interval end; precipitation is the preceding-hour sum"
        ),
        "antecedent_cutoff": antecedent_times[-1],
    })
    return result


def png_alpha_values(png):
    """Decode alpha from the simple filter-0 RGBA PNG emitted by gridrisk."""
    position = 8
    width = height = None
    compressed = bytearray()
    while position < len(png):
        length = struct.unpack(">I", png[position : position + 4])[0]
        kind = png[position + 4 : position + 8]
        payload = png[position + 8 : position + 8 + length]
        position += length + 12
        if kind == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif kind == b"IDAT":
            compressed.extend(payload)
    if width is None or height is None:
        raise AssertionError("PNG is missing IHDR")
    raw = zlib.decompress(bytes(compressed))
    stride = width * 4 + 1
    values = []
    for row_index in range(height):
        row = raw[row_index * stride : (row_index + 1) * stride]
        if not row or row[0] != 0:
            raise AssertionError("test decoder expects filter-0 scanlines")
        values.extend(row[4::4])
    return values


class ForecastContractTests(unittest.TestCase):
    def test_antecedent_rainfall_physically_spins_up_initial_state(self):
        dry_snapshot = fixture_snapshot(12)
        wet_snapshot = with_antecedent(dry_snapshot, rain_mm_h=80.0)
        with patch(
            "backend.app.forecasting.observations.latest_district_observations",
            return_value={},
        ):
            dry, _, _, dry_meta = forecasting.initial_analysis_for_snapshot(
                dry_snapshot, n_members=12
            )
            wet, _, _, wet_meta = forecasting.initial_analysis_for_snapshot(
                wet_snapshot, n_members=12
            )
            wet_again, _, _, _ = forecasting.initial_analysis_for_snapshot(
                wet_snapshot, n_members=12
            )
        self.assertFalse(dry_meta["antecedent_spinup"]["applied"])
        self.assertTrue(wet_meta["antecedent_spinup"]["applied"])
        self.assertTrue(wet_meta["antecedent_spinup"]["mass_balance"]["all_members_conservative"])
        self.assertGreater(float(np.mean(wet)), float(np.mean(dry)))
        np.testing.assert_allclose(wet, wet_again)

    def test_observed_dry_prior_accounts_structural_and_ensrf_state_increments(self):
        snapshot = with_antecedent(fixture_snapshot(12), rain_mm_h=0.0)
        fresh = {
            "baoan": {
                "depth_m": 0.30,
                "station_count": 2,
                "observed_at": "2026-08-23T22:55:00+08:00",
                "available_at": "2026-08-23T22:56:00+08:00",
                "provenance": "observed(test)",
            }
        }
        with patch(
            "backend.app.forecasting.observations.latest_district_observations",
            return_value=fresh,
        ):
            _, _, _, analysis = forecasting.initial_analysis_for_snapshot(
                snapshot, n_members=16
            )
        structural = analysis["structural_prior_increment_mean_m3"]
        ensrf = analysis["assimilation_increment_mean_m3"]
        combined = analysis["total_nonphysical_initial_state_increment_mean_m3"]
        self.assertNotEqual(structural, 0.0)
        self.assertAlmostEqual(combined, structural + ensrf, delta=0.05)
        self.assertIn("separate non-physical state corrections", analysis["mass_accounting_note"])

    def test_predict_contract_and_quantiles(self):
        result = forecasting.build_predict(fixture_snapshot(), n_members=20)
        self.assertEqual(len(result["districts"]), 10)
        self.assertEqual(len(result["hours"]), len(result["rainfall"]))
        self.assertEqual(
            result["model"]["family"],
            "conservative graph state-space + parameter ensemble + localized EnSRF",
        )
        for district in result["districts"]:
            self.assertEqual(len(district["series"]), len(result["hours"]))
            self.assertEqual(district["current"], district["series"][0])
            self.assertEqual(
                district["peak"]["depth_p50_m"],
                max(item["depth_p50_m"] for item in district["series"]),
            )
            for item in district["series"]:
                self.assertLessEqual(item["depth_p10_m"], item["depth_p50_m"])
                self.assertLessEqual(item["depth_p50_m"], item["depth_p90_m"])
                self.assertGreaterEqual(item["prob"], 0.0)
                self.assertLessEqual(item["prob"], 1.0)
                self.assertIn(item["level"], range(5))
        json.dumps(result, allow_nan=False)

    def test_main_predict_uses_v3_serializer(self):
        snapshot = fixture_snapshot(12)
        with patch("backend.app.main.weather.resolve_snapshot", return_value=snapshot):
            result = main._build_predict(1)
        self.assertEqual(result["forecast_run_id"], "fixture-12")
        self.assertEqual(result["model"]["version"], forecasting.MODEL_VERSION)

    def test_predict_endpoint_replays_pinned_run_and_rejects_horizon_conflict(self):
        snapshot = fixture_snapshot(72)
        run_id = snapshot["forecast_run_id"]
        weather._FORECAST_ARCHIVE[run_id] = snapshot
        try:
            first = main.predict(forecast_days=3, forecast_run_id=run_id)
            replay = main.predict(forecast_days=3, forecast_run_id=run_id)
            with self.assertRaises(main.HTTPException) as conflict:
                main.predict(forecast_days=2, forecast_run_id=run_id)
        finally:
            weather._FORECAST_ARCHIVE.pop(run_id, None)
        self.assertEqual(first["model_run_id"], replay["model_run_id"])
        self.assertEqual(first, replay)
        self.assertEqual(conflict.exception.status_code, 409)

    def test_raw_forecast_endpoint_returns_pinned_snapshot_metadata(self):
        snapshot = fixture_snapshot(72)
        with patch(
            "backend.app.main.weather.resolve_snapshot", return_value=snapshot
        ) as resolve:
            result = main.forecast(3, snapshot["forecast_run_id"])
        resolve.assert_called_once_with(3, snapshot["forecast_run_id"])
        self.assertEqual(result["forecast_run_id"], snapshot["forecast_run_id"])
        self.assertEqual(result["issued_at"], snapshot["issued_at"])
        self.assertEqual(result["forecast_days"], 3)
        self.assertIn("provider_forecast_issued_at", result)
        self.assertIn("issued_at_semantics", result)

    def test_weather_cache_is_keyed_by_horizon(self):
        weather._SNAPSHOT_CACHE.clear()

        def fake(days, as_of=None):
            data = fixture_snapshot(int(days) * 24)
            start = weather._now() + timedelta(hours=1)
            data["times"] = [
                (start + timedelta(hours=index)).isoformat()
                for index in range(len(data["times"]))
            ]
            data["forecast_run_id"] = f"source-{days}"
            data.pop("issued_at", None)
            return data

        with patch("backend.app.weather.downscaled_forecast", side_effect=fake) as mocked, patch(
            "backend.app.weather._first_valid_is_future", return_value=True
        ):
            one = weather.forecast_snapshot(1)
            three = weather.forecast_snapshot(3)
            one_again = weather.forecast_snapshot(1)
        self.assertEqual(len(one["times"]), 24)
        self.assertEqual(len(three["times"]), 72)
        self.assertIs(one, one_again)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(mocked.call_args_list[0].args, (1,))
        self.assertEqual(mocked.call_args_list[1].args, (3,))

    def test_weather_cache_expires_when_first_valid_hour_is_no_longer_future(self):
        timezone_shanghai = timezone(timedelta(hours=8))
        now = datetime(2026, 8, 24, 13, 5, tzinfo=timezone_shanghai)
        stale = fixture_snapshot(72)
        stale["times"] = [
            (now.replace(minute=0) + timedelta(hours=index)).isoformat()
            for index in range(72)
        ]
        fresh = fixture_snapshot(72)
        fresh["times"] = [
            (now.replace(minute=0) + timedelta(hours=index + 1)).isoformat()
            for index in range(72)
        ]
        weather._SNAPSHOT_CACHE[3] = {
            "cached_at": weather.time.time(),
            "data": stale,
        }
        try:
            with patch("backend.app.weather._now", return_value=now), patch(
                "backend.app.weather.downscaled_forecast", return_value=fresh
            ) as refresh:
                result = weather.forecast_snapshot(3)
            refresh.assert_called_once_with(3)
            self.assertGreater(datetime.fromisoformat(result["times"][0]), now)
            self.assertIsNot(result, stale)
        finally:
            weather._SNAPSHOT_CACHE.clear()

    def test_fallback_is_a_rolling_full_hour_horizon(self):
        grid = weather._fallback_grid(2)
        _, times, precipitation = grid[0]
        future = weather.future_window(times, precipitation, 2)
        self.assertEqual(len(future), 48)

    def test_weather_snapshot_preserves_24_available_hours_for_spinup(self):
        timezone_shanghai = timezone(timedelta(hours=8))
        now = datetime(2026, 8, 24, 13, 5, tzinfo=timezone_shanghai)
        with patch("backend.app.weather._now", return_value=now):
            grid = weather._fallback_grid(3)
            with patch("backend.app.weather.fetch_grid", return_value=(grid, True)):
                result = weather.downscaled_forecast(2)
        self.assertEqual(len(result["times"]), 48)
        self.assertEqual(len(result["antecedent_times"]), 24)
        self.assertEqual(len(result["antecedent_city"]), 24)
        self.assertTrue(
            all(len(values) == 24 for values in result["antecedent_districts"].values())
        )
        self.assertLessEqual(
            datetime.fromisoformat(result["antecedent_times"][-1]), now
        )
        self.assertGreater(datetime.fromisoformat(result["times"][0]), now)
        self.assertTrue(result["antecedent_complete"])
        self.assertEqual(
            result["antecedent_interval_semantics"],
            "timestamp is interval end; precipitation is the preceding-hour sum",
        )

    def test_spinup_excludes_the_first_not_yet_complete_forecast_hour(self):
        timezone_shanghai = timezone(timedelta(hours=8))
        now = datetime(2026, 8, 24, 13, 5, tzinfo=timezone_shanghai)
        anchor = now.replace(minute=0, second=0, microsecond=0)
        times = [
            (anchor + timedelta(hours=index - 29)).strftime("%Y-%m-%dT%H:%M")
            for index in range(60)
        ]
        precipitation = [0.0] * 60
        precipitation[30] = 999.0  # 14:00 label: sum for 13:00–14:00, not complete at 13:05.
        grid = [
            (point, list(times), list(precipitation))
            for point in weather.SUBDISTRICT_POINTS
        ]
        with patch("backend.app.weather.fetch_grid", return_value=(grid, False)):
            result = weather.downscaled_forecast(1, as_of=now)
        self.assertEqual(max(result["antecedent_city"]), 0.0)
        self.assertEqual(result["city"][0], 999.0)

    def test_incomplete_future_weather_horizon_is_rejected(self):
        timezone_shanghai = timezone(timedelta(hours=8))
        now = datetime(2026, 8, 24, 13, 5, tzinfo=timezone_shanghai)
        anchor = now.replace(minute=0, second=0, microsecond=0)
        times = [
            (anchor + timedelta(hours=index - 24)).strftime("%Y-%m-%dT%H:%M")
            for index in range(28)
        ]
        grid = [
            (point, list(times), [0.0] * len(times))
            for point in weather.SUBDISTRICT_POINTS
        ]
        with patch("backend.app.weather.fetch_grid", return_value=(grid, False)):
            with self.assertRaisesRegex(ValueError, "expected 24"):
                weather.downscaled_forecast(1, as_of=now)

    def test_forecast_run_id_hashes_antecedent_forcing(self):
        timezone_shanghai = timezone(timedelta(hours=8))
        now = datetime(2026, 8, 23, 23, 5, tzinfo=timezone_shanghai)
        dry = with_antecedent(fixture_snapshot(24), rain_mm_h=0.0)
        wet = with_antecedent(fixture_snapshot(24), rain_mm_h=40.0)
        weather._SNAPSHOT_CACHE.clear()
        weather._FORECAST_ARCHIVE.clear()
        try:
            with patch("backend.app.weather._now", return_value=now), patch(
                "backend.app.weather.downscaled_forecast", side_effect=[dry, wet]
            ):
                first = weather.forecast_snapshot(1, force=True)
                second = weather.forecast_snapshot(1, force=True)
            self.assertNotEqual(first["forecast_run_id"], second["forecast_run_id"])
        finally:
            weather._SNAPSHOT_CACHE.clear()
            weather._FORECAST_ARCHIVE.clear()

    def test_snapshot_crossing_hour_boundary_is_refetched_and_not_backdated(self):
        timezone_shanghai = timezone(timedelta(hours=8))
        request_start = datetime(2026, 8, 24, 12, 59, 55, tzinfo=timezone_shanghai)
        first_created = datetime(2026, 8, 24, 13, 0, 10, tzinfo=timezone_shanghai)
        second_created = datetime(2026, 8, 24, 13, 0, 11, tzinfo=timezone_shanghai)
        stale = fixture_snapshot(24)
        stale["times"] = [
            (datetime(2026, 8, 24, 13, 0, tzinfo=timezone_shanghai) + timedelta(hours=i)).isoformat()
            for i in range(24)
        ]
        stale["forcing_selection_as_of"] = request_start.isoformat()
        fresh = fixture_snapshot(24)
        fresh["times"] = [
            (datetime(2026, 8, 24, 14, 0, tzinfo=timezone_shanghai) + timedelta(hours=i)).isoformat()
            for i in range(24)
        ]
        fresh["forcing_selection_as_of"] = first_created.isoformat()
        weather._SNAPSHOT_CACHE.clear()
        weather._FORECAST_ARCHIVE.clear()
        try:
            with patch(
                "backend.app.weather._now",
                side_effect=[request_start, first_created, second_created],
            ), patch(
                "backend.app.weather.downscaled_forecast", side_effect=[stale, fresh]
            ) as fetched:
                result = weather.forecast_snapshot(1, force=True)
            self.assertEqual(fetched.call_count, 2)
            self.assertEqual(result["snapshot_created_at"], second_created.isoformat())
            self.assertEqual(result["issued_at"], second_created.isoformat())
            self.assertEqual(result["available_at"], second_created.isoformat())
            self.assertGreater(
                datetime.fromisoformat(result["times"][0]), second_created
            )
        finally:
            weather._SNAPSHOT_CACHE.clear()
            weather._FORECAST_ARCHIVE.clear()

    def test_fallback_overlap_does_not_change_with_requested_horizon(self):
        one = weather._fallback_grid(1)[0]
        three = weather._fallback_grid(3)[0]
        self.assertEqual(one[1][:48], three[1][:48])
        self.assertEqual(one[2][:48], three[2][:48])

    def test_pinned_snapshot_reuse_enforces_its_horizon(self):
        snapshot = fixture_snapshot(72)
        run_id = snapshot["forecast_run_id"]
        weather._FORECAST_ARCHIVE[run_id] = snapshot
        try:
            self.assertIs(weather.resolve_snapshot(3, run_id), snapshot)
            with self.assertRaisesRegex(ValueError, "pinned snapshot horizon"):
                weather.resolve_snapshot(2, run_id)
        finally:
            weather._FORECAST_ARCHIVE.pop(run_id, None)

    def test_missing_snapshot_issuance_disables_initial_assimilation(self):
        snapshot = fixture_snapshot(24)
        snapshot.pop("issued_at")
        with patch(
            "backend.app.observations.latest_district_observations"
        ) as latest:
            prior, live, _, analysis = forecasting.initial_analysis_for_snapshot(
                snapshot, n_members=8
            )
        latest.assert_not_called()
        self.assertEqual(live, {})
        self.assertTrue(np.all(prior == 0.0))
        self.assertFalse(analysis["applied"])
        self.assertIsNone(analysis["analysis_cutoff"])
        self.assertIn("no issued_at", analysis["reason"])

    def test_importing_main_does_not_require_legacy_lstm(self):
        # This process may have imported the legacy module through unrelated
        # tests, so verify the production import graph rather than global state.
        imports = main.__dict__
        self.assertNotIn("model", imports)
        self.assertNotIn("hazard", imports)

    def test_spatial_route_does_not_lazy_load_legacy_model_in_fresh_process(self):
        code = """
import sys
from backend.app import main
main.get_spatial()
blocked = ['backend.app.model','app.model','backend.app.hazard','app.hazard','ml.realdata']
assert not [name for name in blocked if name in sys.modules], [name for name in blocked if name in sys.modules]
"""
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class ScenarioContractTests(unittest.TestCase):
    def test_preset_rejects_explicit_overrides_but_accepts_bare_get_query(self):
        values = {
            "rainfall_multiplier": 1.0,
            "add_peak_mm": 0.0,
            "peak_offset_h": 18,
            "drainage_factor": 1.0,
            "pump_efficiency": 1.0,
            "mean_sea_level_m": 0.0,
            "tide_raise": None,
            "tide_amplitude_m": 0.75,
            "tide_phase_h": 0.0,
            "surge_peak_m": 0.0,
            "surge_peak_offset_h": 20.0,
            "surge_duration_h": 12.0,
            "rain_tide_peak_offset_h": None,
        }
        bare_request = Request({"type": "http", "query_string": b"preset=baseline"})
        bare = main._scenario_request_from_query(
            bare_request,
            preset="baseline",
            forecast_run_id=None,
            forecast_days=3,
            scenario_values=values,
        )
        self.assertFalse(main._SCENARIO_OVERRIDE_FIELDS & bare.model_fields_set)
        self.assertEqual(
            main._scenario_from_request(bare),
            {
                key: value
                for key, value in simulate.SCENARIOS["baseline"].items()
                if key != "label"
            },
        )

        mixed_get_request = Request({
            "type": "http",
            "query_string": b"preset=baseline&rainfall_multiplier=1.0",
        })
        mixed_get = main._scenario_request_from_query(
            mixed_get_request,
            preset="baseline",
            forecast_run_id=None,
            forecast_days=3,
            scenario_values=values,
        )
        with self.assertRaises(HTTPException) as get_error:
            main._scenario_from_request(mixed_get)
        self.assertEqual(get_error.exception.status_code, 422)

        with self.assertRaises(HTTPException) as post_error:
            main._scenario_from_request(main.ScenarioRequest(
                preset="baseline", rainfall_multiplier=1.0
            ))
        self.assertEqual(post_error.exception.status_code, 422)

    def test_ocean_preview_has_bounded_query_contract_and_maps_builder_errors(self):
        parameters = {
            item["name"]: item["schema"]
            for item in main.app.openapi()["paths"]["/api/ocean/boundary"]["get"]["parameters"]
        }
        self.assertEqual(parameters["tide_amplitude_m"]["minimum"], 0.0)
        self.assertEqual(parameters["tide_amplitude_m"]["maximum"], 3.0)
        self.assertEqual(parameters["tide_phase_h"]["minimum"], -48.0)
        self.assertEqual(parameters["tide_phase_h"]["maximum"], 48.0)
        self.assertEqual(parameters["surge_peak_m"]["minimum"], 0.0)
        self.assertEqual(parameters["surge_peak_m"]["maximum"], 5.0)
        self.assertEqual(parameters["surge_peak_offset_h"]["minimum"], 0.0)
        self.assertEqual(parameters["surge_peak_offset_h"]["maximum"], 167.0)
        self.assertEqual(parameters["surge_duration_h"]["exclusiveMinimum"], 0.0)
        self.assertEqual(parameters["surge_duration_h"]["maximum"], 168.0)

        with patch("backend.app.main.weather.resolve_snapshot", return_value={
            "times": ["2026-08-24T01:00:00+08:00"], "city": [0.0]
        }), patch(
            "backend.app.main.ocean.build_boundary",
            side_effect=ValueError("invalid ocean boundary"),
        ):
            with self.assertRaises(HTTPException) as error:
                main.get_ocean_boundary(1, 0.75, 0.0, 0.0, 20.0, 12.0)
        self.assertEqual(error.exception.status_code, 422)
        self.assertIn("invalid ocean boundary", error.exception.detail)

    def test_scenario_is_reproducible_and_physically_monotone(self):
        snapshot = fixture_snapshot()
        baseline = simulate.simulate(
            {"rainfall_multiplier": 1.0, "drainage_factor": 1.0},
            snapshot=snapshot,
            n_members=20,
        )
        severe = simulate.simulate(
            {"rainfall_multiplier": 1.5, "add_peak_mm": 18, "drainage_factor": 0.70},
            snapshot=snapshot,
            n_members=20,
        )
        replay = simulate.simulate(
            {"rainfall_multiplier": 1.5, "add_peak_mm": 18, "drainage_factor": 0.70},
            snapshot=snapshot,
            n_members=20,
        )
        self.assertEqual(severe["simulation_run_id"], replay["simulation_run_id"])
        self.assertEqual(severe, replay)
        self.assertIs(simulate.get_cached(severe["simulation_run_id"]), replay)
        self.assertTrue(severe["mass_balance"]["scenario"]["all_members_conservative"])
        for base_d, severe_d in zip(baseline["districts"], severe["districts"]):
            self.assertGreaterEqual(
                severe_d["scenario_peak"]["depth_p50_m"],
                base_d["scenario_peak"]["depth_p50_m"] - 1e-9,
            )
            self.assertEqual(len(severe_d["scenario_prob"]), len(severe["times"]))
        json.dumps(severe, allow_nan=False)

    def test_baseline_products_share_canonical_members_and_model_run(self):
        snapshot = fixture_snapshot(24)
        prediction = forecasting.build_predict(snapshot, n_members=20)
        scenario = simulate.simulate(
            simulate.SCENARIOS["baseline"], snapshot=snapshot, n_members=20
        )
        with patch("backend.app.weather.forecast_snapshot", return_value=snapshot):
            street = streets.build_street_risk(1, n_members=20, snapshot=snapshot)
            grid = gridrisk.build_grid_risk(1, res=0.1, n_members=20, snapshot=snapshot)
        self.assertEqual(prediction["model_run_id"], scenario["baseline_model_run_id"])
        self.assertEqual(prediction["model_run_id"], street["model_run_id"])
        self.assertEqual(prediction["model_run_id"], grid["model_run_id"])

    def test_snapshot_freezes_initial_analysis_for_all_consumers(self):
        snapshot = fixture_snapshot(10)
        later = {
            "baoan": {
                "depth_m": 0.4,
                "station_count": 1,
                "observed_at": "2026-08-24T00:00:00+08:00",
            }
        }
        with patch(
            "backend.app.observations.latest_district_observations",
            side_effect=[{}, later],
        ) as observed:
            first = forecasting.ensemble_for_snapshot(snapshot, n_members=8)
            second = forecasting.ensemble_for_snapshot(snapshot, n_members=8)
        self.assertIs(first, second)
        self.assertEqual(observed.call_count, 1)
        self.assertEqual(first[2], {})

    def test_canonical_ensemble_cache_is_external_and_bounded(self):
        forecasting._CANONICAL_ENSEMBLE_CACHE.clear()
        try:
            snapshots = []
            for index in range(forecasting.MAX_CANONICAL_ENSEMBLE_CACHE + 2):
                snapshot = fixture_snapshot(3)
                snapshot["forecast_run_id"] = f"cache-bound-{index}"
                forecasting.ensemble_for_snapshot(snapshot, n_members=2)
                snapshots.append(snapshot)
            self.assertLessEqual(
                len(forecasting._CANONICAL_ENSEMBLE_CACHE),
                forecasting.MAX_CANONICAL_ENSEMBLE_CACHE,
            )
            self.assertTrue(
                all("_canonical_ensemble_cache" not in item for item in snapshots)
            )
            self.assertTrue(
                all(isinstance(item.get("_canonical_cache_token"), int) for item in snapshots)
            )
        finally:
            forecasting._CANONICAL_ENSEMBLE_CACHE.clear()

    def test_simulation_identity_includes_ensemble_size(self):
        snapshot = fixture_snapshot(24)
        small = simulate.simulate({}, snapshot=snapshot, n_members=8)
        large = simulate.simulate({}, snapshot=snapshot, n_members=12)
        self.assertNotEqual(small["simulation_run_id"], large["simulation_run_id"])

    def test_default_typhoon_sanity_is_finite_and_conservative(self):
        result = simulate.simulate(
            simulate.SCENARIOS["typhoon_tide"],
            snapshot=fixture_snapshot(72),
            n_members=20,
        )
        peak = max(d["scenario_peak"]["depth_p50_m"] for d in result["districts"])
        self.assertLess(peak, 2.0)
        self.assertTrue(result["mass_balance"]["scenario"]["all_members_conservative"])


class AssimilationContractTests(unittest.TestCase):
    def test_enkf_moves_toward_observation_and_preserves_history(self):
        result = assimilation.assimilate_snapshot(
            fixture_snapshot(), "baoan", 0.70, at_hour=6, n_members=32
        )
        self.assertLess(
            abs(result["posterior_depth_m"] - 0.70),
            abs(result["prior_depth_m"] - 0.70),
        )
        self.assertLess(result["posterior_std_m"], result["prior_std_m"])
        self.assertEqual(result["observation"]["unit"], "m")
        self.assertEqual(result["raw_depth_p50_m"][:6], result["corrected_depth_p50_m"][:6])
        self.assertEqual(len(result["raw_risk"]), len(result["corrected_risk"]))
        json.dumps(result, allow_nan=False)

    def test_invalid_assimilation_inputs_are_rejected(self):
        snapshot = fixture_snapshot()
        with self.assertRaises(ValueError):
            assimilation.assimilate_snapshot(snapshot, "unknown", 0.2, 3, n_members=8)
        with self.assertRaises(ValueError):
            assimilation.assimilate_snapshot(snapshot, "baoan", -0.1, 3, n_members=8)
        with self.assertRaises(ValueError):
            assimilation.assimilate_snapshot(snapshot, "baoan", 0.2, 999, n_members=8)

    def test_stale_cache_never_becomes_a_fabricated_observation(self):
        with patch("backend.app.weather.resolve_snapshot", return_value=fixture_snapshot()):
            result = realdatav.assimilate_realtime("baoan", observed_h=None, at_hour=5)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["assimilation"]["raw_risk"], [])
        self.assertIn("no fresh", result["assimilation"]["provenance"])

    def test_fresh_but_unaudited_observation_fails_closed(self):
        unaudited = {
            "baoan": {
                "depth_m": 0.30,
                "station_count": 1,
                "observed_at": "2026-08-23T22:55:00+08:00",
                "available_at": None,
                "provenance": "observed(test-without-availability-audit)",
            }
        }
        snapshot = fixture_snapshot(72)
        with patch("backend.app.weather.resolve_snapshot", return_value=snapshot), patch(
            "backend.app.observations.latest_district_observations", return_value=unaudited
        ) as latest, patch(
            "backend.app.forecasting.ensemble_for_snapshot"
        ) as build_ensemble:
            result = realdatav.assimilate_realtime("baoan", observed_h=None, at_hour=None)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["forecast_run_id"], snapshot["forecast_run_id"])
        self.assertEqual(result["forecast_days"], 3)
        self.assertIn("audit-safe", result["assimilation"]["provenance"])
        self.assertEqual(latest.call_args.kwargs["available_before"].isoformat(), snapshot["issued_at"])
        build_ensemble.assert_not_called()

    def test_fresh_realtime_observation_is_used_once_at_initial_analysis(self):
        fresh = {
            "baoan": {
                "depth_m": 0.30,
                "max_depth_m": 0.32,
                "station_count": 2,
                "observed_at": "2026-08-23T22:55:00+08:00",
                "available_at": "2026-08-23T22:56:00+08:00",
                "provenance": "observed(test)",
            }
        }
        snapshot = fixture_snapshot(12)
        with patch("backend.app.observations.latest_district_observations", return_value=fresh), patch(
            "backend.app.weather.resolve_snapshot", return_value=snapshot
        ):
            result = realdatav.assimilate_realtime("baoan", observed_h=None, at_hour=None)
        self.assertEqual(result["assimilation"]["status"], "initial_analysis_applied")
        self.assertEqual(result["assimilation"]["at_hour"], -1)
        self.assertIn("未重复注入", result["assimilation"]["note"])
        self.assertLess(
            abs(result["assimilation"]["posterior_mean_depth_m"] - 0.30),
            abs(result["assimilation"]["prior_mean_depth_m"] - 0.30),
        )

    def test_realtime_assimilation_reuses_and_returns_pinned_run(self):
        snapshot = fixture_snapshot(72)
        nested = {"forecast_run_id": snapshot["forecast_run_id"], "status": "applied"}
        with patch(
            "backend.app.weather.resolve_snapshot", return_value=snapshot
        ) as resolve, patch(
            "backend.app.assimilation.assimilate_snapshot", return_value=nested
        ) as assimilate:
            result = realdatav.assimilate_realtime(
                "baoan",
                observed_h=0.3,
                at_hour=8,
                forecast_days=3,
                forecast_run_id=snapshot["forecast_run_id"],
            )
        resolve.assert_called_once_with(3, snapshot["forecast_run_id"])
        self.assertIs(assimilate.call_args.args[0], snapshot)
        self.assertEqual(result["forecast_run_id"], snapshot["forecast_run_id"])
        self.assertEqual(result["forecast_days"], 3)

    def test_realtime_api_propagates_run_identity_and_conflicts(self):
        run_id = "fixture-72"
        response = {
            "status": "unavailable",
            "forecast_run_id": run_id,
            "forecast_days": 3,
        }
        with patch(
            "backend.app.main.realdatav.assimilate_realtime", return_value=response
        ) as realtime:
            result = main.api_assimilate_realtime(
                district="baoan",
                observed_h=None,
                at_hour=None,
                forecast_days=3,
                forecast_run_id=run_id,
            )
        realtime.assert_called_once_with(
            "baoan", None, None, forecast_days=3, forecast_run_id=run_id
        )
        self.assertEqual(result["forecast_run_id"], run_id)

        with patch(
            "backend.app.main.realdatav.assimilate_realtime",
            side_effect=ValueError("forecast_days=2 conflicts with pinned snapshot horizon 3"),
        ):
            with self.assertRaises(main.HTTPException) as conflict:
                main.api_assimilate_realtime(
                    district="baoan",
                    observed_h=None,
                    at_hour=None,
                    forecast_days=2,
                    forecast_run_id=run_id,
                )
        self.assertEqual(conflict.exception.status_code, 409)


class SpatialDownscaleContractTests(unittest.TestCase):
    def test_street_grid_and_image_default_to_three_days(self):
        self.assertEqual(inspect.signature(streets.build_street_risk).parameters["forecast_days"].default, 3)
        self.assertEqual(inspect.signature(gridrisk.build_grid_risk).parameters["forecast_days"].default, 3)
        self.assertEqual(inspect.signature(gridrisk.build_grid_image).parameters["forecast_days"].default, 3)

    def test_world_model_endpoints_reuse_the_pinned_snapshot(self):
        snapshot = fixture_snapshot(72)
        depths = {district["id"]: 0.0 for district in shenzhen.DISTRICTS}
        assimilation_result = {"forecast_run_id": snapshot["forecast_run_id"]}
        with patch(
            "backend.app.main.weather.resolve_snapshot", return_value=snapshot
        ) as resolve, patch(
            "backend.app.main.forecasting.peak_depth_by_district", return_value=depths
        ), patch(
            "backend.app.main.assimilation.assimilate_snapshot",
            return_value=assimilation_result,
        ) as assimilate:
            acc = main.get_accessibility(
                forecast_days=3,
                forecast_run_id=snapshot["forecast_run_id"],
                depth_mm=None,
                damage=None,
            )
            cf = main.get_counterfactual(
                forecast_days=3,
                forecast_run_id=snapshot["forecast_run_id"],
                close=None,
                pump=None,
            )
            ast = main.get_assimilate(
                district="baoan",
                observed_h=0.3,
                at_hour=6,
                forecast_days=3,
                forecast_run_id=snapshot["forecast_run_id"],
                k=0.3,
            )
        self.assertEqual(resolve.call_count, 3)
        self.assertTrue(all(call.args == (3, snapshot["forecast_run_id"]) for call in resolve.call_args_list))
        self.assertIs(assimilate.call_args.args[0], snapshot)
        self.assertEqual(acc["forecast_run_id"], snapshot["forecast_run_id"])
        self.assertEqual(cf["forecast_run_id"], snapshot["forecast_run_id"])
        self.assertEqual(ast["forecast_run_id"], snapshot["forecast_run_id"])

    def test_accessibility_rejects_ambiguous_depth_inputs(self):
        with self.assertRaises(main.HTTPException) as raised:
            main.get_accessibility(
                forecast_days=3,
                forecast_run_id=None,
                depth_mm="baoan:300",
                damage="baoan:0.5",
            )
        self.assertEqual(raised.exception.status_code, 422)

    def test_ocean_products_share_one_pinned_snapshot(self):
        snapshot = fixture_snapshot(72)
        simulation = {
            "districts": [{
                "name": "宝安",
                "scenario_peak": {"depth_p50_m": 0.2, "prob": 0.25},
            }],
            "ocean": {"compound_index": 0.4},
        }
        with patch(
            "backend.app.main.weather.resolve_snapshot", return_value=snapshot
        ) as resolve, patch(
            "backend.app.main.simulate.simulate", return_value=simulation
        ) as run_simulation:
            boundary = main.get_ocean_boundary(
                forecast_days=3,
                forecast_run_id=snapshot["forecast_run_id"],
                tide_amplitude_m=0.75,
                tide_phase_h=0.0,
                surge_peak_m=0.0,
                surge_peak_offset_h=20.0,
                surge_duration_h=12.0,
            )
            experiment = main.get_ocean_offset_experiment(
                forecast_days=3,
                forecast_run_id=snapshot["forecast_run_id"],
            )
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(boundary["forecast_run_id"], snapshot["forecast_run_id"])
        self.assertEqual(experiment["forecast_run_id"], snapshot["forecast_run_id"])
        self.assertEqual(run_simulation.call_count, 3)
        for call in run_simulation.call_args_list:
            self.assertIs(call.kwargs["snapshot"], snapshot)
            self.assertEqual(call.kwargs["forecast_run_id"], snapshot["forecast_run_id"])

    def test_ocean_products_reject_pinned_horizon_conflicts(self):
        snapshot = fixture_snapshot(72)
        run_id = snapshot["forecast_run_id"]
        weather._FORECAST_ARCHIVE[run_id] = snapshot
        try:
            with self.assertRaises(main.HTTPException) as boundary_error:
                main.get_ocean_boundary(
                    forecast_days=2,
                    forecast_run_id=run_id,
                    tide_amplitude_m=0.75,
                    tide_phase_h=0.0,
                    surge_peak_m=0.0,
                    surge_peak_offset_h=20.0,
                    surge_duration_h=12.0,
                )
            with self.assertRaises(main.HTTPException) as experiment_error:
                main.get_ocean_offset_experiment(
                    forecast_days=2,
                    forecast_run_id=run_id,
                )
        finally:
            weather._FORECAST_ARCHIVE.pop(run_id, None)
        self.assertEqual(boundary_error.exception.status_code, 409)
        self.assertEqual(experiment_error.exception.status_code, 409)

    def test_street_and_grid_use_depth_ensemble(self):
        snapshot = fixture_snapshot(12)
        with patch("backend.app.weather.forecast_snapshot", return_value=snapshot):
            street = streets.build_street_risk(1, n_members=8)
        grid = gridrisk.build_grid_risk(1, res=0.10, n_members=8)
        self.assertEqual(street["n_streets"], 30)
        self.assertIn("depth >= 0.15 m", street["probability_definition"])
        self.assertGreater(grid["n_cells"], 0)
        encoded_risk = base64.b64decode(grid["risk_u8_b64"])
        encoded_depth = base64.b64decode(grid["depth_mm_u16le_b64"])
        expected_values = grid["n_cells"] * len(grid["times"])
        self.assertEqual(len(encoded_risk), expected_values)
        self.assertEqual(len(encoded_depth), expected_values * 2)
        self.assertEqual(
            grid["timeseries_encoding"]["shape"],
            [grid["n_cells"], len(grid["times"])],
        )
        self.assertNotIn("risk", grid["cells"][0])
        self.assertNotIn("depth_p50_m", grid["cells"][0])
        for item in (street["streets"][0], grid["cells"][0]):
            self.assertLessEqual(item["peak_depth_p10_m"], item["peak_depth_p50_m"])
            self.assertLessEqual(item["peak_depth_p50_m"], item["peak_depth_p90_m"])
            self.assertGreaterEqual(item["peak"], 0.0)
            self.assertLessEqual(item["peak"], 1.0)

    def test_grid_cache_has_entry_and_byte_budgets(self):
        gridrisk._GRID_CACHE.clear()
        gridrisk._GRID_CACHE_BYTES = 0
        try:
            for index in range(gridrisk.MAX_GRID_CACHE_ENTRIES + 3):
                # The repeated dict references keep the test light while the
                # cache estimator treats this like a realistic large response.
                payload = {
                    "risk_u8_b64": "AA==",
                    "depth_mm_u16le_b64": "AAA=",
                    "cells": [{}] * 20_000,
                    "times": ["t"] * 168,
                }
                gridrisk._cache_grid_result((index,), payload, cached_at=index)
            self.assertLessEqual(
                len(gridrisk._GRID_CACHE), gridrisk.MAX_GRID_CACHE_ENTRIES
            )
            self.assertLessEqual(
                gridrisk._GRID_CACHE_BYTES, gridrisk.MAX_GRID_CACHE_BYTES
            )
        finally:
            gridrisk._GRID_CACHE.clear()
            gridrisk._GRID_CACHE_BYTES = 0

    def test_grid_image_has_valid_png_signature_without_optional_pillow(self):
        snapshot = fixture_snapshot(8)
        with patch("backend.app.weather.forecast_snapshot", return_value=snapshot):
            png, bbox, shape = gridrisk.build_grid_image(
                res=0.08, forecast_days=1, hour_index=3
            )
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertGreater(len(png), 64)
        self.assertGreater(shape[0] * shape[1], 0)
        self.assertLess(bbox["south"], bbox["north"])

    def test_grid_image_keeps_subthreshold_median_depth_visible(self):
        snapshot = fixture_snapshot(2)
        district_ids = [district["id"] for district in shenzhen.DISTRICTS]
        # All local values remain below 150 mm even at the maximum bounded
        # downscale factor.  The old probability-only alpha returned a fully
        # transparent PNG for this valid shallow-water state.
        ensemble = {
            "members_depth_mm": np.full((8, 2, len(district_ids)), 20.0),
            "district_ids": district_ids,
        }
        with patch("backend.app.gridrisk._ensemble", return_value=(snapshot, ensemble)):
            png, _, shape, metadata = gridrisk.build_grid_image(
                res=0.08,
                forecast_days=1,
                snapshot=snapshot,
                hour_index=0,
                include_metadata=True,
            )
        alpha = png_alpha_values(png)
        self.assertEqual(len(alpha), shape[0] * shape[1])
        self.assertGreater(max(alpha), 0)
        self.assertEqual(metadata["visible_cell_count"], sum(value > 0 for value in alpha))
        self.assertEqual(metadata["max_probability"], 0.0)
        self.assertGreater(metadata["max_depth_mm"], 0.0)
        self.assertFalse(metadata["empty"])

    def test_grid_image_marks_a_truly_dry_raster_empty(self):
        snapshot = fixture_snapshot(2)
        district_ids = [district["id"] for district in shenzhen.DISTRICTS]
        ensemble = {
            "members_depth_mm": np.zeros((8, 2, len(district_ids))),
            "district_ids": district_ids,
        }
        with patch("backend.app.gridrisk._ensemble", return_value=(snapshot, ensemble)):
            png, _, shape, metadata = gridrisk.build_grid_image(
                res=0.08,
                forecast_days=1,
                snapshot=snapshot,
                hour_index=0,
                include_metadata=True,
            )
        alpha = png_alpha_values(png)
        self.assertEqual(len(alpha), shape[0] * shape[1])
        self.assertEqual(max(alpha), 0)
        self.assertEqual(metadata["visible_cell_count"], 0)
        self.assertTrue(metadata["empty"])

    def test_grid_image_get_and_head_share_diagnostic_headers(self):
        snapshot = fixture_snapshot(2)
        bbox = {"south": 22.44, "west": 113.72, "north": 22.88, "east": 114.66}
        metadata = {
            "visible_cell_count": 12,
            "total_cell_count": 30,
            "max_depth_mm": 42.5,
            "max_probability": 0.375,
            "empty": False,
        }
        with (
            patch("backend.app.weather.resolve_snapshot", return_value=snapshot),
            patch(
                "backend.app.gridrisk.get_grid_image",
                return_value=(b"\x89PNG\r\n\x1a\n", bbox, metadata),
            ) as image,
        ):
            response = main.api_risk_grid_image(
                res=0.0045,
                forecast_days=1,
                forecast_run_id=snapshot["forecast_run_id"],
                hour_index=0,
            )
        image.assert_called_once_with(
            0.0045,
            1,
            snapshot=snapshot,
            hour_index=0,
            include_metadata=True,
        )
        self.assertEqual(response.headers["x-visible-cell-count"], "12")
        self.assertEqual(response.headers["x-total-cell-count"], "30")
        self.assertEqual(response.headers["x-max-depth-mm"], "42.5")
        self.assertEqual(response.headers["x-max-probability"], "0.375")
        self.assertEqual(response.headers["x-raster-empty"], "false")
        route_methods = {
            method
            for route in main.app.routes
            if getattr(route, "path", None) == "/api/risk/grid/image"
            for method in getattr(route, "methods", set())
        }
        self.assertTrue({"GET", "HEAD"}.issubset(route_methods))

    def test_leaflet_raster_rows_are_north_first(self):
        south_first = np.asarray([[[1]], [[2]], [[3]]], dtype=np.uint8)
        oriented = gridrisk._leaflet_oriented_rgba(south_first)
        self.assertEqual(oriented[:, 0, 0].tolist(), [3, 2, 1])

    def test_grid_resolution_budget_is_enforced(self):
        with self.assertRaises(ValueError):
            gridrisk.build_grid_risk(1, res=0.001, n_members=8, snapshot=fixture_snapshot(8))
        with self.assertRaises(ValueError):
            gridrisk.build_grid_image(res=0.001, forecast_days=1, snapshot=fixture_snapshot(8))
        with self.assertRaises(ValueError):
            gridrisk.build_grid_image(
                res=0.08,
                forecast_days=1,
                snapshot=fixture_snapshot(8),
                hour_index=99,
            )


if __name__ == "__main__":
    unittest.main()
