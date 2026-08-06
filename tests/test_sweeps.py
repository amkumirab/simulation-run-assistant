import csv
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.sweeps import (
    build_parameter_sets,
    comparison_rows,
    estimate_sequential_seconds,
    numeric_parameter_value,
    parse_sweep_values,
    write_comparison_csv,
)
from simulation_assistant.types import Job, JobStatus


def make_job(
    job_id: int,
    *,
    batch: str = "sweep-a",
    status: JobStatus = JobStatus.SUCCEEDED,
    parameters: dict | None = None,
    metrics: dict | None = None,
) -> Job:
    return Job(
        id=job_id,
        batch_name=batch,
        adapter="comsol",
        status=status,
        parameters=parameters or {},
        output_formulas={},
        result={"metrics": metrics or {}},
        error=None,
        artifact_dir=None,
        attempts=1,
        created_at="2026-08-06T10:00:00+00:00",
        started_at="2026-08-06T10:00:01+00:00",
        finished_at="2026-08-06T10:00:11+00:00",
    )


class SweepTests(unittest.TestCase):
    def test_parses_lists_and_inclusive_unit_ranges(self) -> None:
        self.assertEqual(
            parse_sweep_values("70[kHz], 80[kHz], 90[kHz]"),
            ["70[kHz]", "80[kHz]", "90[kHz]"],
        )
        self.assertEqual(
            parse_sweep_values("70:100:10[kHz]"),
            ["70[kHz]", "80[kHz]", "90[kHz]", "100[kHz]"],
        )
        self.assertEqual(
            parse_sweep_values("3:1:-1"),
            ["3", "2", "1"],
        )

    def test_rejects_invalid_range_direction_and_empty_list_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive"):
            parse_sweep_values("1:3:-1")
        with self.assertRaisesRegex(ValueError, "empty"):
            parse_sweep_values("1,,3")
        with self.assertRaisesRegex(ValueError, "distinct"):
            parse_sweep_values("1, 1")

    def test_builds_cartesian_parameter_sets_and_enforces_limit(self) -> None:
        parameter_sets = build_parameter_sets(
            {"turns": "10"},
            {"frequency": ["80[kHz]", "90[kHz]"], "gap": ["10[cm]", "15[cm]"]},
        )
        self.assertEqual(len(parameter_sets), 4)
        self.assertEqual(parameter_sets[0]["turns"], "10")
        with self.assertRaisesRegex(ValueError, "limit is 3"):
            build_parameter_sets({}, {"x": [1, 2], "y": [1, 2]}, max_jobs=3)

    def test_estimates_sequential_runtime_from_recent_successes(self) -> None:
        jobs = [
            make_job(1, metrics={"comsol_duration_seconds": 10.0}),
            make_job(2, metrics={"comsol_duration_seconds": 20.0}),
        ]
        self.assertEqual(estimate_sequential_seconds(4, jobs), 60.0)

    def test_extracts_numeric_parameter_values_with_units(self) -> None:
        self.assertEqual(numeric_parameter_value("85[kHz]"), 85.0)
        self.assertEqual(numeric_parameter_value(" -1.5e-3 [m]"), -1.5e-3)
        self.assertIsNone(numeric_parameter_value("automatic"))
        self.assertIsNone(numeric_parameter_value("1e999"))

    def test_filters_comparison_and_exports_dynamic_parameter_columns(self) -> None:
        jobs = [
            make_job(1, parameters={"f0": "80[kHz]"}, metrics={"efficiency": 0.8}),
            make_job(2, parameters={"f0": "90[kHz]"}, metrics={"efficiency": 0.9}),
            make_job(3, batch="other", metrics={"efficiency": 0.1}),
        ]
        rows = comparison_rows(jobs, "efficiency", batch_name="sweep-a")
        self.assertEqual([row["job_id"] for row in rows], [1, 2])

        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_comparison_csv(Path(temp_dir) / "comparison.csv", rows)
            with path.open(encoding="utf-8", newline="") as handle:
                exported = list(csv.DictReader(handle))
        self.assertEqual(exported[1]["f0"], "90[kHz]")
        self.assertEqual(exported[1]["value"], "0.9")


if __name__ == "__main__":
    unittest.main()
