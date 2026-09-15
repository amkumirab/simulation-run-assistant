import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from simulation_assistant.reference_validation import (
    InputMapping,
    MetricTolerance,
    compare_reference_models,
    write_reference_csv,
    write_reference_html,
)
from simulation_assistant.types import Job, JobStatus


class ReferenceValidationTests(unittest.TestCase):
    @staticmethod
    def _job(
        job_id: int,
        batch: str,
        gap: str,
        coupling: float | None,
        *,
        parameter_name: str = "gap",
        metric_name: str = "coupling",
        validation: str = "valid",
        status: JobStatus = JobStatus.SUCCEEDED,
    ) -> Job:
        result = None
        if status == JobStatus.SUCCEEDED:
            metrics = {metric_name: coupling} if coupling is not None else {}
            result = {
                "metrics": metrics,
                "metadata": {"scientific_validation": {"status": validation}},
            }
        return Job(
            id=job_id,
            batch_name=batch,
            adapter="comsol",
            status=status,
            parameters={parameter_name: gap, "design": "A"},
            output_formulas={},
            result=result,
            error=None,
            artifact_dir=None,
            attempts=1,
            created_at="2026-09-14T00:00:00+00:00",
            started_at=None,
            finished_at="2026-09-14T00:01:00+00:00",
        )

    @staticmethod
    def _compare(primary, reference, tolerance=10.0):
        return compare_reference_models(
            primary,
            reference,
            [InputMapping("gap", "air_gap")],
            [MetricTolerance("coupling", "k_ref", tolerance)],
            primary_batch="primary",
            reference_batch="reference",
        )

    def test_pairs_unit_equivalent_inputs_and_passes_metric(self) -> None:
        result = self._compare(
            [self._job(1, "primary", "100[mm]", 0.81)],
            [self._job(2, "reference", "10[cm]", 0.80, parameter_name="air_gap", metric_name="k_ref")],
        )
        pair = result.pairs[0]
        self.assertEqual(pair.status, "passed")
        self.assertAlmostEqual(pair.comparisons[0].relative_error_percent, 1.25)
        self.assertEqual(result.unmatched_primary_job_ids, ())

    def test_reports_warning_and_failure_near_tolerance(self) -> None:
        warning = self._compare(
            [self._job(1, "primary", "100[mm]", 0.89)],
            [self._job(2, "reference", "100[mm]", 1.0, parameter_name="air_gap", metric_name="k_ref")],
            tolerance=12,
        )
        failed = self._compare(
            [self._job(3, "primary", "100[mm]", 0.8)],
            [self._job(4, "reference", "100[mm]", 1.0, parameter_name="air_gap", metric_name="k_ref")],
            tolerance=12,
        )
        self.assertEqual(warning.pairs[0].status, "warning")
        self.assertEqual(failed.pairs[0].status, "failed")

    def test_absolute_tolerance_handles_zero_reference(self) -> None:
        result = compare_reference_models(
            [self._job(1, "primary", "100[mm]", 0.001)],
            [self._job(2, "reference", "100[mm]", 0.0, parameter_name="air_gap", metric_name="k_ref")],
            [InputMapping("gap", "air_gap")],
            [MetricTolerance("coupling", "k_ref", 5, 0.01)],
        )
        comparison = result.pairs[0].comparisons[0]
        self.assertEqual(comparison.status, "passed")
        self.assertIsNone(comparison.relative_error_percent)

    def test_latest_attempt_wins_and_unmatched_jobs_are_visible(self) -> None:
        result = self._compare(
            [
                self._job(1, "primary", "100[mm]", 0.1),
                self._job(3, "primary", "100[mm]", 0.8),
                self._job(5, "primary", "200[mm]", 0.7),
            ],
            [self._job(4, "reference", "100[mm]", 0.8, parameter_name="air_gap", metric_name="k_ref")],
        )
        self.assertEqual(result.pairs[0].primary_job_id, 3)
        self.assertEqual(result.unmatched_primary_job_ids, (5,))

    def test_quality_gate_rejects_unvalidated_or_rejected_pairs(self) -> None:
        rejected = self._compare(
            [self._job(1, "primary", "100[mm]", 0.8, validation="rejected")],
            [self._job(2, "reference", "100[mm]", 0.8, parameter_name="air_gap", metric_name="k_ref")],
        )
        unvalidated = self._compare(
            [self._job(3, "primary", "100[mm]", 0.8, validation="not_recorded")],
            [self._job(4, "reference", "100[mm]", 0.8, parameter_name="air_gap", metric_name="k_ref")],
        )
        self.assertEqual(rejected.pairs[0].status, "rejected")
        self.assertEqual(unvalidated.pairs[0].status, "unvalidated")

    def test_filters_primary_selection_and_records_invalid_inputs(self) -> None:
        primary = [
            self._job(1, "primary", "100[mm]", 0.8),
            replace(
                self._job(2, "primary", "200[mm]", 0.8),
                parameters={"design": "A"},
            ),
        ]
        reference = [
            self._job(3, "reference", "100[mm]", 0.8, parameter_name="air_gap", metric_name="k_ref")
        ]
        result = compare_reference_models(
            primary,
            reference,
            [InputMapping("gap", "air_gap")],
            [MetricTolerance("coupling", "k_ref", 10)],
            primary_job_ids=[1, 2],
        )
        self.assertEqual(result.invalid_input_job_ids, (2,))
        self.assertEqual(len(result.pairs), 1)

    def test_exports_portable_reports(self) -> None:
        result = self._compare(
            [self._job(1, "primary", "100[mm]", 0.81)],
            [self._job(2, "reference", "100[mm]", 0.80, parameter_name="air_gap", metric_name="k_ref")],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = write_reference_csv(Path(temp_dir) / "reference.csv", result)
            html_path = write_reference_html(Path(temp_dir) / "reference.html", result)
            csv_text = csv_path.read_text(encoding="utf-8")
            html_text = html_path.read_text(encoding="utf-8")
        self.assertIn("relative_error_percent:coupling__k_ref", csv_text)
        self.assertIn("Reference Model Validation", html_text)
        self.assertNotIn(".mph", html_text)

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "input mapping"):
            compare_reference_models([], [], [], [MetricTolerance("a", "b", 10)])
        with self.assertRaisesRegex(ValueError, "metric tolerance"):
            compare_reference_models([], [], [InputMapping("a", "b")], [])
        with self.assertRaisesRegex(ValueError, "requires"):
            MetricTolerance("a", "b")
        with self.assertRaisesRegex(ValueError, "positive"):
            MetricTolerance("a", "b", 0)


if __name__ == "__main__":
    unittest.main()
