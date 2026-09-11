import tempfile
import unittest
from pathlib import Path

from simulation_assistant.campaigns import (
    build_campaign_plan,
    build_wpt_baseline_parameters,
    estimate_campaign_storage_bytes,
    write_campaign_csv,
    write_campaign_html,
)
from simulation_assistant.preflight import build_run_signature
from simulation_assistant.types import Job, JobStatus


class CampaignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = {
            "gap": "150[mm]",
            "xoff": "0[mm]",
            "tilt": "0[deg]",
            "yoff": "0[mm]",
            "f0": "85[kHz]",
        }
        self.context = {"model": {"name": "production.mph"}}

    def _job(
        self,
        job_id: int,
        parameters: dict,
        status: JobStatus,
        validation: str | None = None,
        *,
        metrics: dict | None = None,
    ) -> Job:
        result = None
        if status == JobStatus.SUCCEEDED:
            metadata = {}
            if validation is not None:
                metadata["scientific_validation"] = {"status": validation}
            result = {"metrics": metrics or {}, "metadata": metadata}
        return Job(
            id=job_id,
            batch_name="baseline",
            adapter="comsol",
            status=status,
            parameters=parameters,
            output_formulas={},
            result=result,
            error=None,
            artifact_dir=None,
            attempts=1,
            created_at="2026-09-10T00:00:00+00:00",
            started_at=None,
            finished_at=None,
            run_signature=build_run_signature(
                "comsol", parameters, {}, self.context
            ),
        )

    def test_builds_the_documented_36_unique_states(self) -> None:
        states = build_wpt_baseline_parameters(self.base)

        self.assertEqual(len(states), 36)
        self.assertEqual(len({tuple(sorted(state.items())) for state in states}), 36)
        self.assertEqual({state["gap"] for state in states}, {"100[mm]", "150[mm]", "200[mm]"})
        self.assertEqual(
            {state["xoff"] for state in states},
            {"0[mm]", "25[mm]", "50[mm]", "75[mm]"},
        )
        self.assertEqual({state["tilt"] for state in states}, {"0[deg]", "5[deg]", "10[deg]"})
        self.assertEqual({state["yoff"] for state in states}, {"0[mm]"})
        self.assertTrue(all(state["f0"] == "85[kHz]" for state in states))

    def test_requires_every_alignment_input(self) -> None:
        base = dict(self.base)
        del base["tilt"]
        with self.assertRaisesRegex(ValueError, "tilt"):
            build_wpt_baseline_parameters(base)

    def test_plan_resumes_only_missing_failed_rejected_and_unvalidated(self) -> None:
        states = build_wpt_baseline_parameters(self.base)
        jobs = [
            self._job(1, states[0], JobStatus.SUCCEEDED, "valid"),
            self._job(2, states[1], JobStatus.SUCCEEDED, "warning"),
            self._job(3, states[2], JobStatus.RUNNING),
            self._job(4, states[3], JobStatus.FAILED),
            self._job(5, states[4], JobStatus.SUCCEEDED, "rejected"),
            self._job(6, states[5], JobStatus.SUCCEEDED),
        ]

        plan = build_campaign_plan(
            states,
            adapter="comsol",
            output_formulas={},
            run_context=self.context,
            existing_jobs=jobs,
        )

        self.assertEqual(
            [state.status for state in plan.states[:7]],
            ["valid", "warning", "running", "failed", "rejected", "unvalidated", "missing"],
        )
        pending_indexes = {state.index for state in plan.pending}
        self.assertNotIn(1, pending_indexes)
        self.assertNotIn(2, pending_indexes)
        self.assertNotIn(3, pending_indexes)
        self.assertTrue({4, 5, 6, 7}.issubset(pending_indexes))

    def test_accepted_result_wins_over_a_later_failed_attempt(self) -> None:
        state = build_wpt_baseline_parameters(self.base)[0]
        jobs = [
            self._job(2, state, JobStatus.FAILED),
            self._job(1, state, JobStatus.SUCCEEDED, "valid"),
        ]

        plan = build_campaign_plan(
            [state],
            adapter="comsol",
            output_formulas={},
            run_context=self.context,
            existing_jobs=jobs,
        )

        self.assertEqual(plan.states[0].status, "valid")
        self.assertEqual(plan.states[0].job_id, 1)
        self.assertFalse(plan.pending)

    def test_latest_retryable_attempt_controls_the_displayed_state(self) -> None:
        state = build_wpt_baseline_parameters(self.base)[0]
        jobs = [
            self._job(2, state, JobStatus.FAILED),
            self._job(1, state, JobStatus.SUCCEEDED, "rejected"),
        ]

        plan = build_campaign_plan(
            [state],
            adapter="comsol",
            output_formulas={},
            run_context=self.context,
            existing_jobs=jobs,
        )

        self.assertEqual(plan.states[0].status, "failed")
        self.assertEqual(plan.states[0].job_id, 2)

    def test_estimates_storage_from_recent_comsol_results(self) -> None:
        state = build_wpt_baseline_parameters(self.base)[0]
        jobs = [
            self._job(
                1,
                state,
                JobStatus.SUCCEEDED,
                "valid",
                metrics={"output_model_bytes": 1000},
            ),
            self._job(
                2,
                state,
                JobStatus.SUCCEEDED,
                "valid",
                metrics={"output_model_bytes": 2000},
            ),
        ]
        self.assertEqual(estimate_campaign_storage_bytes(4, jobs), 6000)

    def test_exports_portable_csv_and_html_reports(self) -> None:
        state = build_wpt_baseline_parameters(self.base)[0]
        job = self._job(
            1,
            state,
            JobStatus.SUCCEEDED,
            "valid",
            metrics={"coupling": 0.25, "label": "<unsafe>"},
        )
        plan = build_campaign_plan(
            [state],
            adapter="comsol",
            output_formulas={},
            run_context=self.context,
            existing_jobs=[job],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = write_campaign_csv(Path(temp_dir) / "campaign.csv", plan)
            html_path = write_campaign_html(Path(temp_dir) / "campaign.html", plan)
            csv_text = csv_path.read_text(encoding="utf-8")
            html_text = html_path.read_text(encoding="utf-8")

        self.assertIn("output_coupling", csv_text)
        self.assertIn("0.25", csv_text)
        self.assertIn("&lt;unsafe&gt;", html_text)
        self.assertNotIn("<unsafe>", html_text)
        self.assertNotIn("production.mph", html_text)


if __name__ == "__main__":
    unittest.main()
