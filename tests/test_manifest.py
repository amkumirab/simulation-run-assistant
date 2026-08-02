import json
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.manifest import load_manifest


class ManifestTests(unittest.TestCase):
    def test_expands_cartesian_sweep_and_keeps_fixed_values(self) -> None:
        manifest_data = {
            "name": "sweep",
            "adapter": "mock-em",
            "fixed": {"length_mm": 50},
            "sweep": {"frequency_ghz": [8, 10], "width_mm": [18, 22]},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text(json.dumps(manifest_data), encoding="utf-8")
            manifest = load_manifest(path)

        self.assertEqual(len(manifest.jobs), 4)
        self.assertEqual(manifest.jobs[0]["length_mm"], 50)
        self.assertEqual(
            {(job["frequency_ghz"], job["width_mm"]) for job in manifest.jobs},
            {(8, 18), (8, 22), (10, 18), (10, 22)},
        )

    def test_rejects_manifest_with_jobs_and_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "manifest.json"
            path.write_text(
                json.dumps({"name": "invalid", "jobs": [{}], "sweep": {"x": [1]}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "exactly one"):
                load_manifest(path)


if __name__ == "__main__":
    unittest.main()
