import unittest
from collections import Counter
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from backend.app import observations


class ObservationIntegrationTest(unittest.TestCase):
    def test_all_station_features_are_mapped(self):
        catalog = observations.load_station_catalog()
        mapping = observations.load_station_district_map()
        self.assertEqual(len(catalog), 148)
        self.assertEqual(set(catalog), set(mapping))
        code_mapped = [
            row for row in mapping.values() if row["method"] == "station-code-district-segment"
        ]
        polygon_mapped = [
            row
            for row in mapping.values()
            if row["method"] == "district-polygon-repaired-segments"
        ]
        methods = Counter(row["method"] for row in mapping.values())
        self.assertEqual(
            methods,
            Counter({
                "station-code-district-segment": 102,
                "district-polygon-repaired-segments": 45,
                "nearest-labelled-floodpoint": 1,
            }),
        )
        self.assertEqual(len(code_mapped), 102)
        self.assertEqual(len(polygon_mapped), 45)
        self.assertTrue(all(row.get("coordinate_check") for row in mapping.values()))
        fallback_distances = [
            row["reference_distance_km"]
            for row in mapping.values()
            if row["reference_distance_km"] is not None
        ]
        self.assertLess(max(fallback_distances), 6.0)
        self.assertIn("dapeng", {row["district_id"] for row in mapping.values()})

    def test_cached_slice_is_not_claimed_as_training_ready(self):
        readiness = observations.data_readiness()
        self.assertEqual(readiness["duration_hours"], 44.0)
        self.assertEqual(readiness["stations"], 148)
        self.assertFalse(readiness["forecast_training_ready"])
        self.assertEqual(readiness["independent_flood_events"], 0)
        self.assertEqual(readiness["rows_with_available_at"], 0)
        self.assertFalse(readiness["availability_time_auditable"])

    def test_stale_cache_is_not_assimilated_as_live(self):
        future = datetime(2026, 8, 24, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(observations.latest_district_observations(now=future), {})

    def test_historical_rows_keep_observed_provenance_and_mapping(self):
        rows = observations.load_waterlevel_rows()
        self.assertEqual(len(rows), 6573)
        self.assertTrue(all(r["district_id"] for r in rows))
        self.assertTrue(all(r["depth_proxy_m"] >= 0 for r in rows))

    def test_forecast_cutoff_rejects_late_or_unaudited_observations(self):
        cutoff = datetime(2026, 8, 24, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        base = {
            "station_code": "s1",
            "timestamp": cutoff - timedelta(minutes=10),
            "depth_proxy_m": 0.2,
            "district_id": "baoan",
        }
        with patch(
            "backend.app.observations.load_waterlevel_rows",
            return_value=[{**base, "available_at": None}],
        ):
            self.assertEqual(
                observations.latest_district_observations(
                    now=cutoff, available_before=cutoff
                ),
                {},
            )
        with patch(
            "backend.app.observations.load_waterlevel_rows",
            return_value=[{**base, "available_at": cutoff + timedelta(minutes=1)}],
        ):
            self.assertEqual(
                observations.latest_district_observations(
                    now=cutoff, available_before=cutoff
                ),
                {},
            )
        with patch(
            "backend.app.observations.load_waterlevel_rows",
            return_value=[{**base, "available_at": cutoff - timedelta(minutes=1)}],
        ):
            result = observations.latest_district_observations(
                now=cutoff, available_before=cutoff
            )
        self.assertIn("baoan", result)


if __name__ == "__main__":
    unittest.main()
