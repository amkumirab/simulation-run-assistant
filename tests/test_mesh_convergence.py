import tempfile
import unittest
from pathlib import Path

from simulation_assistant.mesh_convergence import (
    ConvergenceMetric,
    MeshLevel,
    build_mesh_convergence_plan,
    parse_mesh_levels,
    write_mesh_convergence_csv,
    write_mesh_convergence_html,
)
from simulation_assistant.types import Job, JobStatus


class MeshConvergenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {"model": {"name": "production.mph"}, "target": {"job": "job1"}}
        self.base = self._job(
            1,
            {"gap": "150[mm]", "mesh_scale": "1"},
            metrics={"coupling": 0.8, "inductance": 24.0},
        )
        self.levels = parse_mesh_levels("Coarse=1.5, Normal=1.0, Fine=0.7, Extra fine=0.5")
        self.metrics = (
            ConvergenceMetric("coupling", 0.5),
            ConvergenceMetric("inductance", 1.0),
        )

    @staticmethod
    def _job(
        job_id: int,
        parameters: dict,
        *,
        metrics: dict | None = None,
        status: JobStatus = JobStatus.SUCCEEDED,
        validation: str = "valid",
        signature: str | None = None,
    ) -> Job:
        result = None
        if status == JobStatus.SUCCEEDED:
            result = {
                "metrics": metrics or {},
                "metadata": {"scientific_validation": {"status": validation}},
            }
        return Job(
            id=job_id,
            batch_name="mesh-study",
            adapter="comsol",
            status=status,
            parameters=parameters,
            output_formulas={},
            result=result,
            error=None,
            artifact_dir=None,
            attempts=1,
            created_at="2026-09-25T00:00:00+00:00",
            started_at=None,
            finished_at="2026-09-25T00:01:00+00:00",
            run_signature=signature,
        )

    def _plan(self, existing=()):
        return build_mesh_convergence_plan(
            self.base,
            "mesh_scale",
            self.levels,
            self.metrics,
            output_formulas={},
            run_context=self.context,
            existing_jobs=existing,
        )

    def _completed_jobs(self, values: list[tuple[float, float]]) -> list[Job]:
        initial = self._plan()
        return [
            self._job(
                index + 10,
                state.parameters,
                metrics={
                    "coupling": coupling,
                    "inductance": inductance,
                    "degrees_of_freedom": 1000 * (index + 1),
                    "comsol_duration_seconds": 20 * (index + 1),
                },
                signature=state.signature,
            )
            for index, (state, (coupling, inductance)) in enumerate(
                zip(initial.states, values)
            )
        ]

    def test_parses_ordered_mesh_levels(self) -> None:
        self.assertEqual([level.label for level in self.levels], ["Coarse", "Normal", "Fine", "Extra fine"])
        self.assertEqual(self.levels[-1].value, "0.5")
        with self.assertRaisesRegex(ValueError, "label=value"):
            parse_mesh_levels("Coarse, Fine=0.5")
        with self.assertRaisesRegex(ValueError, "unique"):
            parse_mesh_levels("Coarse=1, Coarse=0.5")

    def test_builds_unique_resumable_mesh_states(self) -> None:
        initial = self._plan()
        existing = [
            self._job(
                10,
                initial.states[0].parameters,
                metrics={"coupling": 0.8, "inductance": 24.0},
                signature=initial.states[0].signature,
            ),
            self._job(
                11,
                initial.states[1].parameters,
                status=JobStatus.RUNNING,
                signature=initial.states[1].signature,
            ),
            self._job(
                12,
                initial.states[2].parameters,
                status=JobStatus.FAILED,
                signature=initial.states[2].signature,
            ),
        ]
        plan = self._plan(existing)

        self.assertEqual(
            [state.run_status for state in plan.states],
            ["valid", "running", "failed", "missing"],
        )
        self.assertEqual([state.mesh_value for state in plan.pending], ["0.7", "0.5"])
        self.assertTrue(all(state.parameters["gap"] == "150[mm]" for state in plan.states))

    def test_recommends_lightest_level_with_stable_remaining_refinements(self) -> None:
        jobs = self._completed_jobs(
            [
                (0.7800, 23.00),
                (0.7970, 23.85),
                (0.7995, 23.98),
                (0.8000, 24.00),
            ]
        )
        plan = self._plan(jobs)

        self.assertEqual(plan.status, "converged")
        self.assertEqual(plan.recommended_level, "Fine")
        self.assertEqual(plan.recommended_job_id, 12)
        self.assertEqual(plan.states[1].convergence_status, "not_converged")
        self.assertEqual(plan.states[2].convergence_status, "converged")
        self.assertAlmostEqual(
            plan.states[3].relative_changes_percent["coupling"],
            0.0625,
        )
        self.assertEqual(plan.states[2].degrees_of_freedom, 3000)
        self.assertEqual(plan.states[2].duration_seconds, 60)

    def test_marks_completed_unstable_study_not_converged(self) -> None:
        jobs = self._completed_jobs(
            [(0.70, 20.0), (0.74, 21.0), (0.77, 22.0), (0.80, 23.0)]
        )
        plan = self._plan(jobs)

        self.assertEqual(plan.status, "not_converged")
        self.assertIsNone(plan.recommended_level)
        self.assertEqual(plan.states[-1].convergence_status, "not_converged")

    def test_missing_metric_keeps_transition_incomplete(self) -> None:
        jobs = self._completed_jobs(
            [(0.8, 24.0), (0.8, 24.0), (0.8, 24.0), (0.8, 24.0)]
        )
        jobs[-1] = self._job(
            jobs[-1].id,
            jobs[-1].parameters,
            metrics={"coupling": 0.8},
            signature=jobs[-1].run_signature,
        )
        plan = self._plan(jobs)

        self.assertEqual(plan.status, "incomplete")
        self.assertEqual(plan.states[-1].run_status, "missing_outputs")
        self.assertEqual(plan.states[-1].convergence_status, "waiting")
        self.assertEqual([state.mesh_value for state in plan.pending], ["0.5"])

    def test_older_complete_result_wins_over_newer_missing_output(self) -> None:
        initial = self._plan()
        complete = self._job(
            10,
            initial.states[0].parameters,
            metrics={"coupling": 0.8, "inductance": 24.0},
            signature=initial.states[0].signature,
        )
        incomplete = self._job(
            11,
            initial.states[0].parameters,
            metrics={"coupling": 0.8},
            signature=initial.states[0].signature,
        )
        plan = self._plan([complete, incomplete])

        self.assertEqual(plan.states[0].run_status, "valid")
        self.assertEqual(plan.states[0].job_id, 10)

    def test_requires_an_accepted_base_job_and_metric(self) -> None:
        rejected = self._job(
            2,
            self.base.parameters,
            validation="rejected",
        )
        with self.assertRaisesRegex(ValueError, "accepted"):
            build_mesh_convergence_plan(
                rejected,
                "mesh_scale",
                self.levels,
                self.metrics,
                output_formulas={},
                run_context=self.context,
                existing_jobs=[],
            )
        with self.assertRaisesRegex(ValueError, "at least one"):
            build_mesh_convergence_plan(
                self.base,
                "mesh_scale",
                self.levels,
                [],
                output_formulas={},
                run_context=self.context,
                existing_jobs=[],
            )

    def test_exports_portable_reports(self) -> None:
        plan = self._plan(
            self._completed_jobs(
                [(0.8, 24.0), (0.8, 24.0), (0.8, 24.0), (0.8, 24.0)]
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = write_mesh_convergence_csv(Path(temp_dir) / "mesh.csv", plan)
            html_path = write_mesh_convergence_html(Path(temp_dir) / "mesh.html", plan)
            csv_text = csv_path.read_text(encoding="utf-8")
            html_text = html_path.read_text(encoding="utf-8")

        self.assertIn("relative_change_percent:coupling", csv_text)
        self.assertIn("Mesh Convergence Study", html_text)
        self.assertIn("Fine", html_text)
        self.assertNotIn("production.mph", html_text)


if __name__ == "__main__":
    unittest.main()
