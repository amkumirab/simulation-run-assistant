import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.storage import JobStore
from simulation_assistant.wpt_circuit import (
    SeriesSeriesSettings,
    TwoPortData,
    tune_series_series,
)


ROOT = Path(__file__).resolve().parents[1]


class WptExampleTests(unittest.TestCase):
    def test_real_nominal_result_matches_reference_operating_point(self) -> None:
        dataset = json.loads(
            (ROOT / "examples/wpt_circuit_results.json").read_text(encoding="utf-8")
        )
        nominal = next(case for case in dataset["cases"] if case["name"] == "Nominal")
        metrics = nominal["metrics"]
        two_port = TwoPortData(
            metrics["frequency_Hz"], metrics["L1_H"], metrics["L2_H"],
            metrics["M12_H"], metrics["M21_H"], metrics["R1_ohm"],
            metrics["R2_ohm"], metrics["R12_ohm"], metrics["R21_ohm"],
        )
        controls, point = tune_series_series(two_port, SeriesSeriesSettings())
        self.assertAlmostEqual(controls.source_rms_v, 49.543127581324676, places=8)
        self.assertAlmostEqual(point.primary_current_rms_a, 78.93151599360579, places=8)
        self.assertAlmostEqual(point.primary_capacitor_rms_v, 864.0042591564486, places=8)
        self.assertAlmostEqual(point.ac_efficiency, 0.9461999192674364, places=10)

    def test_replay_is_repeatable_and_uses_an_isolated_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "example"
            command = [
                sys.executable,
                str(ROOT / "examples/replay_wpt_circuit.py"),
                "--workspace", str(workspace),
            ]
            for _attempt in range(2):
                subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
            jobs = JobStore(workspace / "jobs.db").list(limit=20)
            self.assertEqual(len(jobs), 5)
            self.assertTrue(all("replay only" in job.result["metadata"]["origin"] for job in jobs))
            with (workspace / "circuit-study.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(sum(row["status"] == "passed" for row in rows), 3)
            self.assertEqual(sum(row["status"] == "failed" for row in rows), 2)
            self.assertTrue((workspace / "circuit-study.html").is_file())


if __name__ == "__main__":
    unittest.main()
