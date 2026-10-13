import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from test_field_samples import metadata
from simulation_assistant.field_samples import Sensor
from simulation_assistant.field_sample_files import (
    FIELD_COLUMNS, load_field_csv, save_field_workspace, load_field_workspace,
    write_field_readings_csv, write_sensor_layout_csv,
)


class FieldSampleFileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.path = self.base / "field.csv"
        self.text = ",".join(FIELD_COLUMNS) + "\nAligned,S1,10,20,30,-1,2,3,4,5,6\nOffset,S1,10,20,30,1,-2,3,4,5,6\n"
        self.path.write_text(self.text, encoding="utf-8")
        self.sensors = (Sensor("S1", (.01, .02, .03), (1., 0., 0.)),)

    def test_csv_units_complex_phase_and_digest(self):
        data = load_field_csv(self.path, metadata())
        self.assertEqual(data.samples[0].position_m, (.01, .02, .03))
        for actual, expected in zip(data.samples[0].field, (-1e-6+2e-6j, 3e-6+4e-6j, 5e-6+6e-6j)):
            self.assertAlmostEqual(actual.real, expected.real, places=15)
            self.assertAlmostEqual(actual.imag, expected.imag, places=15)
        self.assertEqual(data.source_sha256, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_bad_csv_is_rejected_not_partially_imported(self):
        for value in [self.text.replace("-1,2", "nan,2"), self.text + self.text.splitlines()[1] + "\n",
                      self.text.replace("bx_imag", "bx_real"), self.text.replace("bz_imag", "unknown"),
                      self.text.replace("-1,2", "-1,"), self.text.replace("-1,2", "os.run(),2"),
                      self.text.replace("Aligned,S1", "=cmd,S1"), self.text.replace("-1,2", "-1,2,7")]:
            self.path.write_text(value, encoding="utf-8")
            with self.subTest(csv=value), self.assertRaises(ValueError):
                load_field_csv(self.path, metadata())
        self.path.write_bytes(b"x" * 5_000_001)
        with self.assertRaises(ValueError):
            load_field_csv(self.path, metadata())

    def test_exact_workspace_round_trip_without_source_file(self):
        data = load_field_csv(self.path, metadata())
        saved = save_field_workspace(self.base / "review.json", data, self.sensors)
        self.path.unlink()
        loaded, sensors = load_field_workspace(saved)
        self.assertEqual(loaded, data)
        self.assertEqual(sensors, self.sensors)
        self.assertNotIn(str(self.base), saved.read_text())

    def test_tampered_malformed_and_oversized_json(self):
        path = save_field_workspace(self.base / "review.json", load_field_csv(self.path, metadata()), self.sensors)
        original = json.loads(path.read_text())
        tampered = {**original, "metadata": {**original["metadata"], "frequency_hz": 1}}
        for value in [None, [], {**original, "samples": []}, tampered,
                      {**original, "sensors": [{"point_id": "bad"}]}, {**original, "extra": True}]:
            path.write_text(json.dumps(value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                load_field_workspace(path)
        path.write_bytes(b"x" * 8_000_001)
        with self.assertRaises(ValueError):
            load_field_workspace(path)

    def test_report_keeps_missing_rows_conventions_and_provenance(self):
        data = load_field_csv(self.path, metadata())
        layout = self.sensors + (Sensor("Missing", (0., 0., 0.), (0., 0., 1.)),)
        path = write_field_readings_csv(self.base / "comparison.csv", data, layout, "Offset", "Aligned")
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["status"], "missing point")
        self.assertEqual(rows[1]["amplitude_t"], "")
        self.assertEqual(rows[0]["source_kind"], "synthetic")
        self.assertEqual(rows[0]["phasor_convention"], "peak")
        self.assertEqual(rows[0]["source_csv_sha256"], data.source_sha256)
        self.assertEqual(rows[0]["nx"], "1.0")
        self.assertAlmostEqual(float(rows[0]["reference_real_t"]), -1e-6)
        self.assertNotIn(str(self.base), path.read_text())
        points = write_sensor_layout_csv(self.base / "points.csv", self.sensors)
        with points.open(newline="") as stream:
            self.assertEqual(next(csv.DictReader(stream))["x_m"], "0.01")

    def test_empty_headers_wrong_suffix_and_row_limit(self):
        for value in ["", ",".join(FIELD_COLUMNS)+"\n", self.text.splitlines()[0]+"\n"+
                      "\n".join(f"State,S{i},0,0,0,1,0,0,0,0,0" for i in range(257))]:
            self.path.write_text(value)
            with self.assertRaises(ValueError):
                load_field_csv(self.path, metadata())
        with self.assertRaises(ValueError):
            load_field_csv(self.base / "field.txt", metadata())

    def test_failed_atomic_save_preserves_existing_workspace(self):
        from unittest.mock import patch
        data = load_field_csv(self.path, metadata())
        path = save_field_workspace(self.base / "existing.json", data, self.sensors)
        prior = path.read_bytes()
        with patch("simulation_assistant.field_sample_files.os.replace", side_effect=OSError("fixture replace failure")):
            with self.assertRaises(OSError):
                save_field_workspace(path, data, self.sensors)
        self.assertEqual(path.read_bytes(), prior)
        self.assertFalse(list(self.base.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
