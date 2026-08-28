import unittest
import numpy as np
from pydantic import ValidationError

from backend.app import coastal, geohazard, main, river, shenzhen, typhoon


def district_rain(values):
    return {d["id"]: list(values) for d in shenzhen.DISTRICTS}


class CoastalCompoundTest(unittest.TestCase):
    def test_real_boundary_requires_provenance_and_preserves_components(self):
        times = ["2026-08-28T00:00:00+08:00", "2026-08-28T01:00:00+08:00"]
        boundary = coastal.boundary_from_levels(
            times, [1.0, 1.5], predicted_tide_m=[0.8, 0.9],
            station_id="yantian", datum="D85", source="test-gauge",
            available_at="2026-08-28T01:05:00+08:00",
        )
        np.testing.assert_allclose(boundary["storm_surge_m"], [0.2, 0.6])
        self.assertEqual(boundary["station"]["datum"], "D85")

    def test_marine_state_closes_and_high_water_increases_invasion(self):
        times = [f"2026-08-28T{h:02d}:00:00+08:00" for h in range(8)]
        def run(level):
            boundary = coastal.boundary_from_levels(
                times, [level] * len(times), station_id="chiwan", datum="D85",
                source="test", available_at="2026-08-28T00:00:00+08:00",
            )
            return coastal.DEFAULT_MODEL.simulate(district_rain([0.0] * len(times)), boundary)
        low, high = run(0.5), run(2.2)
        self.assertTrue(low["audit"]["marine_conservative"])
        self.assertTrue(high["audit"]["marine_conservative"])
        self.assertEqual(float(low["marine_storage_m3"].sum()), 0.0)
        self.assertGreater(float(high["marine_storage_m3"].sum()), 0.0)


class RiverBasinTest(unittest.TestCase):
    def test_river_topology_routes_and_floodplain_is_conservative(self):
        rain = {rid: [0.0, 180.0, 180.0, 0.0] for rid in river.DEFAULT_MODEL.ids}
        result = river.DEFAULT_MODEL.simulate(rain, upstream_inflow_m3_s=80.0)
        self.assertTrue(result["audit"]["floodplain_conservative"])
        self.assertTrue(np.all(result["channel_flow_m3_s"] >= 0))
        self.assertGreater(float(result["routed_in_m3_s"].sum()), 0.0)

    def test_river_ensrf_moves_flow_toward_observation(self):
        rng = np.random.default_rng(4)
        prior = np.maximum(0, rng.normal(80, 12, size=(32, len(river.DEFAULT_MODEL.ids))))
        j = river.DEFAULT_MODEL.index["pingshan"]
        analysis = river.DEFAULT_MODEL.assimilate_ensrf(prior, {"pingshan": 160.0})
        self.assertLess(abs(analysis["analysis_flow_m3_s"][:, j].mean() - 160),
                        abs(prior[:, j].mean() - 160))


class GeoHazardTest(unittest.TestCase):
    def test_wet_steep_vulnerable_slope_has_higher_trigger_belief(self):
        rain = [5.0] * 12 + [80.0] * 3
        low = geohazard.DEFAULT_MODEL.simulate(
            rain, slope_deg=5, soil_saturation=0.1, geology_vulnerability=0.1
        )
        high = geohazard.DEFAULT_MODEL.simulate(
            rain, slope_deg=35, soil_saturation=0.8, geology_vulnerability=0.9
        )
        self.assertGreater(high["trigger_probability"][-1], low["trigger_probability"][-1])
        self.assertTrue(np.all(np.diff(high["trigger_probability"]) >= -1e-12))
        self.assertTrue(np.all((high["runoff_coefficient"] >= 0) & (high["runoff_coefficient"] <= 1)))


class TyphoonCouplingTest(unittest.TestCase):
    def test_one_track_drives_all_hazard_domains(self):
        times = [f"2026-08-28T{h:02d}:00:00+08:00" for h in range(6)]
        track = [{"latitude": 22.3 + 0.05*h, "longitude": 114.4 - 0.05*h,
                  "max_wind_m_s": 42.0, "central_pressure_hpa": 955.0,
                  "rain_rate_mm_h": 45.0} for h in range(6)]
        result = typhoon.simulate(times, track)
        self.assertIn("marine_storage_m3", result["coastal_pluvial"])
        self.assertIn("channel_flow_m3_s", result["river"])
        self.assertIn("dapeng", result["geohazard"])
        self.assertIn("facade_damage_probability", result["wind_damage"]["futian"])

    def test_api_contracts_are_strict(self):
        with self.assertRaises(ValidationError):
            main.GeoHazardRequest(rainfall_mm_h=[10], slope_deg=100)
        with self.assertRaises(ValidationError):
            main.TyphoonMultiHazardRequest(
                times=["x"], track=[{"latitude": 22.5, "longitude": 114.0,
                "max_wind_m_s": -1, "central_pressure_hpa": 950, "rain_rate_mm_h": 10}]
            )


if __name__ == "__main__":
    unittest.main()
