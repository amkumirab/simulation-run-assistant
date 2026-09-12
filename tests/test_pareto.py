import tempfile
import unittest
from pathlib import Path

from simulation_assistant.pareto import (
    ParetoObjective,
    analyze_pareto,
    write_pareto_csv,
    write_pareto_html,
)
from simulation_assistant.ranking import RankingConstraint
from simulation_assistant.types import Job, JobStatus


class ParetoTests(unittest.TestCase):
    @staticmethod
    def _job(
        job_id: int,
        coupling: float | None,
        resistance: float | None,
        *,
        status: JobStatus = JobStatus.SUCCEEDED,
        validation: str = "valid",
        gap: str = "100[mm]",
    ) -> Job:
        metrics = {}
        if coupling is not None:
            metrics["coupling"] = coupling
        if resistance is not None:
            metrics["resistance"] = resistance
        result = (
            {
                "metrics": metrics,
                "metadata": {"scientific_validation": {"status": validation}},
            }
            if status == JobStatus.SUCCEEDED
            else None
        )
        return Job(
            id=job_id,
            batch_name="baseline",
            adapter="comsol",
            status=status,
            parameters={"gap": gap},
            output_formulas={},
            result=result,
            error=None,
            artifact_dir=None,
            attempts=1,
            created_at="2026-09-12T00:00:00+00:00",
            started_at=None,
            finished_at="2026-09-12T00:01:00+00:00",
        )

    def test_finds_non_dominated_tradeoffs_and_front_numbers(self) -> None:
        result = analyze_pareto(
            [
                self._job(1, 0.90, 10.0),
                self._job(2, 0.80, 5.0),
                self._job(3, 0.70, 12.0),
                self._job(4, 0.75, 8.0),
            ],
            [
                ParetoObjective("coupling", "maximize"),
                ParetoObjective("resistance", "minimize"),
            ],
            batch_name="baseline",
        )

        self.assertEqual({row.job_id for row in result.pareto_front}, {1, 2})
        rows = {row.job_id: row for row in result.rows}
        self.assertEqual(rows[3].front, 3)
        self.assertEqual(rows[4].front, 2)
        self.assertIn(1, rows[3].dominated_by)
        self.assertIn(2, rows[4].dominated_by)

    def test_weights_change_compromise_order_but_not_the_front(self) -> None:
        jobs = [self._job(1, 0.9, 10), self._job(2, 0.8, 5)]
        coupling_priority = analyze_pareto(
            jobs,
            [
                ParetoObjective("coupling", "maximize", 4),
                ParetoObjective("resistance", "minimize", 1),
            ],
        )
        resistance_priority = analyze_pareto(
            jobs,
            [
                ParetoObjective("coupling", "maximize", 1),
                ParetoObjective("resistance", "minimize", 4),
            ],
        )

        self.assertEqual(coupling_priority.rows[0].job_id, 1)
        self.assertEqual(resistance_priority.rows[0].job_id, 2)
        self.assertEqual(len(coupling_priority.pareto_front), 2)
        self.assertEqual(len(resistance_priority.pareto_front), 2)

    def test_applies_unit_aware_constraints_and_quality_filters(self) -> None:
        jobs = [
            self._job(1, 0.9, 10, gap="100[mm]"),
            self._job(2, 0.8, 5, gap="200[mm]"),
            self._job(3, 0.7, 4, validation="rejected"),
            self._job(4, None, 3),
            self._job(5, 1.0, 2, status=JobStatus.FAILED),
            self._job(6, 0.95, 6, validation="not_recorded"),
        ]
        constraint = RankingConstraint.from_value("input", "gap", "<=", "0.15[m]")

        result = analyze_pareto(
            jobs,
            [
                ParetoObjective("coupling", "maximize"),
                ParetoObjective("resistance", "minimize"),
            ],
            constraints=[constraint],
        )

        self.assertEqual([row.job_id for row in result.rows], [1])
        self.assertEqual(result.considered_jobs, 5)
        self.assertEqual(result.constraint_rejected_jobs, 1)
        self.assertEqual(result.validation_rejected_jobs, 1)
        self.assertEqual(result.unvalidated_jobs, 1)
        self.assertEqual(result.missing_values, 1)

    def test_rejects_invalid_objective_definitions(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two"):
            analyze_pareto([], [ParetoObjective("coupling", "maximize")])
        with self.assertRaisesRegex(ValueError, "unique"):
            analyze_pareto(
                [],
                [
                    ParetoObjective("coupling", "maximize"),
                    ParetoObjective("coupling", "minimize"),
                ],
            )
        with self.assertRaisesRegex(ValueError, "weight"):
            ParetoObjective("coupling", "maximize", 0)

    def test_equal_points_share_the_same_front(self) -> None:
        result = analyze_pareto(
            [self._job(1, 0.8, 5), self._job(2, 0.8, 5)],
            [
                ParetoObjective("coupling", "maximize"),
                ParetoObjective("resistance", "minimize"),
            ],
        )
        self.assertEqual({row.front for row in result.rows}, {1})
        self.assertTrue(all(row.compromise_score == 1 for row in result.rows))

    def test_exports_csv_and_self_contained_html(self) -> None:
        result = analyze_pareto(
            [self._job(1, 0.8, 5)],
            [
                ParetoObjective("coupling", "maximize"),
                ParetoObjective("resistance", "minimize"),
            ],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = write_pareto_csv(Path(temp_dir) / "pareto.csv", result)
            html_path = write_pareto_html(Path(temp_dir) / "pareto.html", result)
            csv_text = csv_path.read_text(encoding="utf-8")
            html_text = html_path.read_text(encoding="utf-8")

        self.assertIn("objective:coupling", csv_text)
        self.assertIn("normalized:resistance", csv_text)
        self.assertIn("Pareto Analysis", html_text)
        self.assertNotIn("production.mph", html_text)


if __name__ == "__main__":
    unittest.main()
