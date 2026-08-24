import unittest
from unittest.mock import patch
import tempfile
from pathlib import Path

import numpy as np

from backend.app import ocean
from backend.app import ocean_data
from backend.app import shenzhen, simulate


class OceanBoundaryTest(unittest.TestCase):
    def test_surge_peak_occurs_near_requested_hour(self):
        hours = np.arange(72, dtype=float)
        surge = ocean.storm_surge(hours, peak_m=0.8, peak_offset_h=20, duration_h=12)
        self.assertEqual(int(np.argmax(surge)), 20)
        self.assertAlmostEqual(float(np.max(surge)), 0.8, places=6)

    def test_higher_sea_level_never_improves_gravity_drainage(self):
        levels = np.linspace(-0.5, 1.8, 40)
        factor = ocean.drainage_factor(levels, coastal_exposure=1.0)
        self.assertTrue(np.all(np.diff(factor) <= 1e-12))

    def test_coastal_area_is_more_sensitive_than_inland(self):
        levels = np.array([0.0, 1.2])
        coastal = ocean.drainage_factor(levels, coastal_exposure=1.0)
        inland = ocean.drainage_factor(levels, coastal_exposure=0.1)
        self.assertLess(coastal[-1], inland[-1])

    def test_boundary_reports_peak_offset_and_provenance(self):
        times = [f"2026-08-{23 + h // 24:02d}T{h % 24:02d}:00:00+08:00" for h in range(48)]
        rain = np.zeros(48)
        rain[20] = 80
        result = ocean.build_boundary(times, {
            "surge_peak_m": 0.6,
            "surge_peak_offset_h": 20,
        }, rain)
        self.assertIsInstance(result["rain_tide_peak_offset_h"], int)
        self.assertIn("astronomical_tide", result["provenance"])
        self.assertGreater(result["peak"]["total_level_m"], 0)
        self.assertEqual(len(result["tide_phase"]), len(times))
        self.assertEqual(len(result["time_to_next_high_tide_h"]), len(times))

    def test_surge_is_continuous_without_unphysical_jumps(self):
        surge = ocean.storm_surge(np.arange(72), peak_m=1.0, peak_offset_h=20, duration_h=12)
        self.assertLess(float(np.max(np.abs(np.diff(surge)))), 0.25)

    def test_risk_guard_sensitivity_is_monotonic(self):
        levels = np.array([0.0, 0.2, 0.4, 0.6])
        factor = ocean.district_drainage_factor(levels, "yantian", 1.0)
        self.assertTrue(np.all(np.diff(factor) <= 1e-12))

    def test_mixed_datums_are_rejected(self):
        rows = [{"datum": "1985国家高程基准"}, {"datum": "香港海图基准"}]
        with self.assertRaises(ocean_data.TideDataError):
            ocean_data.assert_comparable_datums(rows)

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ocean_data.TideDataError):
            ocean_data.parse_timestamp("2023-09-07T12:00:00")

    def test_hourly_aggregation_marks_missing_hours(self):
        raw = "timestamp,station_id,longitude,latitude,observed_level_m,datum,quality_flag,source\n" \
              "2023-09-07T00:10:00+08:00,yantian,114.2,22.5,1.2,D85,good,test\n" \
              "2023-09-07T02:10:00+08:00,yantian,114.2,22.5,1.4,D85,good,test\n"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tide.csv"
            path.write_text(raw, encoding="utf-8")
            hourly = ocean_data.aggregate_hourly(ocean_data.read_observations(path))
        self.assertEqual(len(hourly), 3)
        self.assertEqual(hourly[1]["quality_flag"], "missing")
        self.assertIsNone(hourly[1]["observed_level_m"])

    def test_simulation_couples_high_sea_level_to_drainage(self):
        times = [f"2026-08-{23 + h // 24:02d}T{h % 24:02d}:00:00+08:00" for h in range(24)]
        rain = [8.0] * 24
        fake = {
            "times": times,
            "city": rain,
            "city_cum": [0.0] * 24,
            "districts": {d["id"]: rain for d in shenzhen.DISTRICTS},
            "cum": {d["id"]: [0.0] * 24 for d in shenzhen.DISTRICTS},
            "fallback": True,
        }
        with patch.object(simulate.weather, "downscaled_forecast", return_value=fake):
            result = simulate.simulate({
                "surge_peak_m": 1.2,
                "surge_peak_offset_h": 12,
                "rainfall_multiplier": 1.0,
                "drainage_factor": 1.0,
            }, forecast_days=1)
        factors = {d["id"]: d["min_drainage_factor"] for d in result["districts"]}
        most_coastal = max(shenzhen.DISTRICTS, key=lambda d: d["coastal"])["id"]
        least_coastal = min(shenzhen.DISTRICTS, key=lambda d: d["coastal"])["id"]
        self.assertLess(factors[most_coastal], factors[least_coastal])
        self.assertIn("ocean", result)


if __name__ == "__main__":
    unittest.main()
