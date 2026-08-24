import csv
import json
import unittest
from pathlib import Path

from backend.app import gisreal, platform_fetch, realdatav
from backend.app.data_paths import REAL_GIS


class RealDataIntegrationTest(unittest.TestCase):
    def test_required_gis_assets_are_project_local(self):
        for name in ("shenzhen_dem.csv", "shenzhen_builtup_density.csv",
                     "shenzhen_roads_summary.csv", "shenzhen_water.geojson",
                     "shenzhen_districts.geojson"):
            self.assertTrue((REAL_GIS / name).exists(), name)

    def test_spatial_assets_have_expected_counts(self):
        summary = realdatav.asset_summary()
        self.assertEqual(summary["dem_points"], 480)
        self.assertEqual(summary["impervious_cells"], 19968)
        self.assertEqual(summary["road_segments"], 28625)

    def test_floodpoints_and_station_features_are_complete(self):
        self.assertEqual(len(realdatav.load_floodpoints()), 206)
        stations = realdatav.load_station_features()
        self.assertEqual(len(stations), 148)
        self.assertTrue(all(r.get("lat") and r.get("lon") for r in stations))

    def test_hourly_waterlevel_is_timezone_aware_and_deduplicated(self):
        path = REAL_GIS / "shenzhen_waterlevel_hourly.csv"
        with path.open(encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        keys = {(r["station_code"], r["timestamp_bjt"]) for r in rows}
        self.assertEqual(len(keys), len(rows))
        self.assertTrue(all(r["timestamp_bjt"].endswith("+08:00") for r in rows))
        self.assertTrue(all(r["quality_flag"] in {"good", "review", "invalid"} for r in rows))

    def test_quality_report_records_transform_assumption(self):
        report = json.loads((REAL_GIS / "shenzhen_waterlevel_quality_report.json").read_text())
        self.assertEqual(report["input_rows"], 100000)
        self.assertEqual(report["duplicate_rows_removed"], 14507)
        self.assertEqual(report["hourly_rows"], 6573)
        self.assertIn("timezone_assumption", report)

    def test_cached_waterlevel_exposes_148_stations(self):
        platform_fetch._SZ_WL_CACHE = None
        snapshot = platform_fetch.fetch_waterlevel()
        self.assertEqual(snapshot["count"], 148)


if __name__ == "__main__":
    unittest.main()
