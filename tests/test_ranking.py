import csv
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.ranking import (
    RankingConstraint,
    rank_sweep_results,
    write_ranking_csv,
)
from simulation_assistant.types import Job, JobStatus


def make_job(
    job_id: int,
    *,
    batch: str = "charger-sweep",
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
        artifact_dir=f"artifacts/job-{job_id:06d}",
        attempts=1,
        created_at="2026-09-02T10:00:00+00:00",
        started_at="2026-09-02T10:00:01+00:00",
        finished_at="2026-09-02T10:00:11+00:00",
    )


class RankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.jobs = [
            make_job(
                1,
                parameters={"gap": "10[cm]", "turns": 8},
                metrics={"coupling": 0.71, "losses": 8.0},
            ),
            make_job(
                2,
                parameters={"gap": "15[cm]", "turns": 10},
                metrics={"coupling": 0.82, "losses": 12.0},
            ),
            make_job(
                3,
                parameters={"gap": "12[cm]", "turns": 12},
                metrics={"coupling": 0.78, "losses": 9.0},
            ),
        ]

    def test_ranks_maximum_with_input_and_output_constraints(self) -> None:
        result = rank_sweep_results(
            self.jobs,
            "coupling",
            constraints=[
                RankingConstraint("input", "gap", "<=", 12),
                RankingConstraint("output", "losses", "<", 10),
            ],
            batch_name="charger-sweep",
        )

        self.assertEqual([row.job_id for row in result.rows], [3, 1])
        self.assertEqual([row.rank for row in result.rows], [1, 2])
        self.assertEqual(result.considered_jobs, 3)
        self.assertEqual(result.rejected_jobs, 1)
        self.assertEqual(result.missing_values, 0)

    def test_supports_minimum_limit_and_deterministic_ties(self) -> None:
        jobs = [
            *self.jobs,
            make_job(4, metrics={"coupling": 0.71, "losses": 7.0}),
        ]
        result = rank_sweep_results(jobs, "coupling", direction="minimize", limit=2)

        self.assertEqual([row.job_id for row in result.rows], [1, 4])
        self.assertEqual(result.qualifying_jobs, 4)

    def test_counts_missing_values_and_ignores_other_statuses(self) -> None:
        jobs = [
            *self.jobs,
            make_job(4, metrics={"losses": 1.0}),
            make_job(5, status=JobStatus.FAILED, metrics={"coupling": 1.0}),
            make_job(6, batch="other", metrics={"coupling": 1.0}),
        ]
        result = rank_sweep_results(
            jobs,
            "coupling",
            constraints=[RankingConstraint("input", "gap", ">", 0)],
            batch_name="charger-sweep",
        )

        self.assertEqual(result.considered_jobs, 4)
        self.assertEqual(result.missing_values, 1)
        self.assertEqual(result.qualifying_jobs, 3)

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "source"):
            RankingConstraint("metric", "losses", "<", 10)
        with self.assertRaisesRegex(ValueError, "operator"):
            RankingConstraint("output", "losses", "=", 10)
        with self.assertRaisesRegex(ValueError, "direction"):
            rank_sweep_results(self.jobs, "coupling", direction="largest")
        with self.assertRaisesRegex(ValueError, "positive"):
            rank_sweep_results(self.jobs, "coupling", limit=0)
        with self.assertRaisesRegex(ValueError, "finite"):
            RankingConstraint("output", "losses", "<", float("nan"))

    def test_exports_ranked_inputs_and_constraint_values(self) -> None:
        result = rank_sweep_results(
            self.jobs,
            "coupling",
            constraints=[RankingConstraint("output", "losses", "<", 10)],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_ranking_csv(Path(temp_dir) / "ranking.csv", result)
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(rows[0]["rank"], "1")
        self.assertEqual(rows[0]["job_id"], "3")
        self.assertEqual(rows[0]["input:gap"], "12[cm]")
        self.assertEqual(rows[0]["constraint:output:losses"], "9.0")
        self.assertNotIn("artifact_dir", rows[0])
        self.assertNotIn("artifacts", str(rows))


if __name__ == "__main__":
    unittest.main()
