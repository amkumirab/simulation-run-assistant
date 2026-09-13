import tempfile
import unittest
from pathlib import Path

from simulation_assistant.robustness import (
    RobustObjective,
    analyze_robust_designs,
    heatmap_values,
    write_robust_csv,
    write_robust_html,
)
from simulation_assistant.types import Job, JobStatus


class RobustnessTests(unittest.TestCase):
    @staticmethod
    def _job(
        job_id: int,
        design: str,
        xoff: str,
        tilt: str,
        coupling: float | None,
        resistance: float | None = 5.0,
        *,
        validation: str = "valid",
        status: JobStatus = JobStatus.SUCCEEDED,
    ) -> Job:
        metrics = {}
        if coupling is not None:
            metrics["coupling"] = coupling
        if resistance is not None:
            metrics["resistance"] = resistance
        return Job(
            id=job_id,
            batch_name="alignment",
            adapter="comsol",
            status=status,
            parameters={
                "design": design,
                "gap": "100[mm]",
                "xoff": xoff,
                "yoff": "0[mm]",
                "tilt": tilt,
            },
            output_formulas={},
            result={
                "metrics": metrics,
                "metadata": {"scientific_validation": {"status": validation}},
            } if status == JobStatus.SUCCEEDED else None,
            error=None,
            artifact_dir=None,
            attempts=1,
            created_at="2026-09-13T00:00:00+00:00",
            started_at=None,
            finished_at="2026-09-13T00:01:00+00:00",
        )

    @staticmethod
    def _objectives() -> list[RobustObjective]:
        return [
            RobustObjective("coupling", "maximize", 2),
            RobustObjective("resistance", "minimize"),
        ]

    def test_groups_conditions_and_ranks_complete_designs(self) -> None:
        jobs = [
            self._job(1, "A", "0[mm]", "0[deg]", 0.90, 5),
            self._job(2, "A", "50[mm]", "0[deg]", 0.70, 7),
            self._job(3, "B", "0[mm]", "0[deg]", 0.85, 4),
            self._job(4, "B", "50[mm]", "0[deg]", 0.80, 5),
        ]
        result = analyze_robust_designs(jobs, self._objectives())

        self.assertEqual(len(result.groups), 2)
        self.assertTrue(all(group.complete for group in result.groups))
        self.assertEqual({group.rank for group in result.groups}, {1, 2})
        group_b = next(group for group in result.groups if group.design_parameters["design"] == "B")
        self.assertEqual(group_b.rank, 1)
        self.assertAlmostEqual(group_b.metric_summaries["coupling"].worst, 0.80)
        self.assertAlmostEqual(group_b.metric_summaries["coupling"].mean, 0.825)
        self.assertAlmostEqual(group_b.metric_summaries["coupling"].worst_case_change_percent, 100 * (0.85 - 0.80) / 0.85)

    def test_incomplete_and_rejected_groups_are_not_ranked(self) -> None:
        expected = [
            {"xoff": "0[mm]", "yoff": "0[mm]", "tilt": "0[deg]"},
            {"xoff": "50[mm]", "yoff": "0[mm]", "tilt": "0[deg]"},
        ]
        jobs = [
            self._job(1, "incomplete", "0[mm]", "0[deg]", 0.9),
            self._job(2, "rejected", "0[mm]", "0[deg]", 0.9),
            self._job(3, "rejected", "50[mm]", "0[deg]", 0.7, validation="rejected"),
        ]
        result = analyze_robust_designs(jobs, self._objectives(), expected_conditions=expected)

        self.assertFalse(any(group.eligible for group in result.groups))
        self.assertTrue(all(group.rank is None for group in result.groups))
        reasons = {group.design_parameters["design"]: group.exclusion_reason for group in result.groups}
        self.assertIn("missing", reasons["incomplete"])
        self.assertIn("rejected", reasons["rejected"])

    def test_latest_run_supersedes_previous_state(self) -> None:
        jobs = [
            self._job(1, "A", "0[mm]", "0[deg]", 0.2, validation="rejected"),
            self._job(2, "A", "0[mm]", "0[deg]", 0.9),
        ]
        result = analyze_robust_designs(jobs, self._objectives())
        group = result.groups[0]

        self.assertTrue(group.eligible)
        self.assertEqual(group.job_ids, (2,))
        self.assertEqual(group.metric_summaries["coupling"].worst, 0.9)

    def test_unit_equivalent_conditions_share_one_state(self) -> None:
        jobs = [
            self._job(1, "A", "50[mm]", "0[deg]", 0.6),
            self._job(2, "A", "5[cm]", "0[rad]", 0.7),
        ]
        result = analyze_robust_designs(jobs, self._objectives())
        self.assertEqual(result.groups[0].expected_states, 1)
        self.assertEqual(result.groups[0].job_ids, (2,))

    def test_modes_can_change_ranking(self) -> None:
        jobs = [
            self._job(1, "steady", "0[mm]", "0[deg]", 0.75),
            self._job(2, "steady", "50[mm]", "0[deg]", 0.75),
            self._job(3, "peaky", "0[mm]", "0[deg]", 1.00),
            self._job(4, "peaky", "50[mm]", "0[deg]", 0.70),
        ]
        objective = [RobustObjective("coupling", "maximize")]
        worst = analyze_robust_designs(jobs, objective, ranking_mode="worst_case")
        average = analyze_robust_designs(jobs, objective, ranking_mode="average")

        self.assertEqual(worst.ranked_groups[0].design_parameters["design"], "steady")
        self.assertEqual(average.ranked_groups[0].design_parameters["design"], "peaky")

    def test_heatmap_and_portable_exports(self) -> None:
        jobs = [
            self._job(1, "A", "0[mm]", "0[deg]", 0.9),
            self._job(2, "A", "50[mm]", "0[deg]", 0.7),
        ]
        result = analyze_robust_designs(jobs, self._objectives())
        x_values, y_values, cells = heatmap_values(result.groups[0], "coupling")
        self.assertEqual(len(x_values), 2)
        self.assertEqual(len(y_values), 1)
        self.assertEqual(sorted(cells.values()), [0.7, 0.9])

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = write_robust_csv(Path(temp_dir) / "robust.csv", result)
            html_path = write_robust_html(Path(temp_dir) / "robust.html", result)
            csv_text = csv_path.read_text(encoding="utf-8")
            html_text = html_path.read_text(encoding="utf-8")
        self.assertIn("worst:coupling", csv_text)
        self.assertIn("Robust Misalignment Analysis", html_text)
        self.assertNotIn(".mph", html_text)

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            analyze_robust_designs([], [])
        with self.assertRaisesRegex(ValueError, "unique"):
            analyze_robust_designs([], [RobustObjective("k", "maximize")], condition_fields=("xoff", "xoff"))
        with self.assertRaisesRegex(ValueError, "Ranking mode"):
            analyze_robust_designs([], [RobustObjective("k", "maximize")], ranking_mode="fast")


if __name__ == "__main__":
    unittest.main()
