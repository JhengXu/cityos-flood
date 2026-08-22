import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_supervision_data import validate_event


class SupervisionValidatorTest(unittest.TestCase):
    def test_valid_minimal_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "2023-09-07_extreme-rain"
            event.mkdir()
            (event / "meta.json").write_text(json.dumps({
                "event_id": event.name,
                "start_time": "2023-09-07T00:00:00+08:00",
                "end_time": "2023-09-08T00:00:00+08:00",
                "dataset_version": "p0.1",
                "label_type": "observed",
                "sources": [{"publisher": "test"}],
            }), encoding="utf-8")
            self._write(event / "waterlogging.csv", {
                "label_id": "L1", "timestamp": "2023-09-07T23:00:00+08:00",
                "longitude": "114.05", "latitude": "22.54", "depth_cm": "25",
                "flooded": "1", "source_id": "S1", "quality_flag": "verified",
                "label_type": "observed",
            })
            self._write(event / "rainfall_hourly.csv", {
                "station_id": "R1", "timestamp": "2023-09-07T22:00:00+08:00",
                "longitude": "114.05", "latitude": "22.54", "rainfall_mm": "85",
                "source_id": "S2", "quality_flag": "verified",
            })
            result = validate_event(event)
            self.assertTrue(result["ok"], result["errors"])

    def test_rejects_incomplete_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "bad"
            event.mkdir()
            (event / "meta.json").write_text("{}", encoding="utf-8")
            result = validate_event(event)
            self.assertFalse(result["ok"])
            self.assertIn("missing waterlogging.csv", result["errors"])

    @staticmethod
    def _write(path, row):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=row.keys())
            writer.writeheader()
            writer.writerow(row)


if __name__ == "__main__":
    unittest.main()
