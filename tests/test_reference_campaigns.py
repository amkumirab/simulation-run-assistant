import tempfile
import unittest
from pathlib import Path

from simulation_assistant.preflight import build_run_signature
from simulation_assistant.reference_campaigns import (
    build_reference_campaign_plan,
    write_reference_campaign_csv,
    write_reference_campaign_html,
)
from simulation_assistant.reference_validation import InputMapping
from simulation_assistant.types import Job, JobStatus


class ReferenceCampaignTests(unittest.TestCase):
    @staticmethod
    def _job(
        job_id: int,
        parameters: dict,
        *,
        batch: str = "primary",
        status: JobStatus = JobStatus.SUCCEEDED,
        validation: str = "valid",
        signature: str | None = None,
    ) -> Job:
        result = (
            {
                "metrics": {"coupling": 0.8},
                "metadata": {"scientific_validation": {"status": validation}},
            }
            if status == JobStatus.SUCCEEDED
            else None
        )
        return Job(
            id=job_id,
            batch_name=batch,
            adapter="comsol",
            status=status,
            parameters=parameters,
            output_formulas={},
            result=result,
            error=None,
            artifact_dir=None,
            attempts=1,
            created_at="2026-09-23T00:00:00+00:00",
            started_at=None,
            finished_at="2026-09-23T00:01:00+00:00",
            run_signature=signature,
        )

    def _plan(self, primary, existing=()):
        return build_reference_campaign_plan(
            primary,
            [InputMapping("gap", "air_gap"), InputMapping("xoff", "offset")],
            {"air_gap": "150[mm]", "offset": "0[mm]", "mesh_size": "2[mm]"},
            output_formulas={"quality": "coupling"},
            run_context={"model": {"name": "reference.mph"}},
            existing_jobs=existing,
        )

    def test_builds_reference_inputs_and_preserves_defaults(self) -> None:
        plan = self._plan(
            [self._job(10, {"gap": "100[mm]", "xoff": "25[mm]"})]
        )
        state = plan.states[0]
        self.assertEqual(state.primary_job_id, 10)
        self.assertEqual(state.parameters["air_gap"], "100[mm]")
        self.assertEqual(state.parameters["offset"], "25[mm]")
        self.assertEqual(state.parameters["mesh_size"], "2[mm]")
        self.assertEqual(state.status, "missing")
        self.assertEqual(len(plan.pending), 1)

    def test_excludes_invalid_primary_jobs_and_deduplicates_states(self) -> None:
        plan = self._plan(
            [
                self._job(1, {"gap": "100[mm]", "xoff": "0[mm]"}),
                self._job(2, {"gap": "100[mm]", "xoff": "0[mm]"}),
                self._job(3, {"gap": "200[mm]", "xoff": "0[mm]"}, validation="rejected"),
                self._job(4, {"gap": "300[mm]"}),
            ]
        )
        self.assertEqual(len(plan.states), 1)
        self.assertEqual(plan.states[0].primary_job_id, 2)
        self.assertEqual(plan.excluded_primary_job_ids, (1, 3, 4))

    def test_resumes_failed_or_rejected_but_reuses_accepted_and_active(self) -> None:
        primary = [
            self._job(1, {"gap": "100[mm]", "xoff": "0[mm]"}),
            self._job(2, {"gap": "200[mm]", "xoff": "0[mm]"}),
            self._job(3, {"gap": "300[mm]", "xoff": "0[mm]"}),
        ]
        initial = self._plan(primary)
        signatures = [state.signature for state in initial.states]
        existing = [
            self._job(11, initial.states[0].parameters, batch="reference", signature=signatures[0]),
            self._job(12, initial.states[1].parameters, batch="reference", status=JobStatus.RUNNING, signature=signatures[1]),
            self._job(13, initial.states[2].parameters, batch="reference", status=JobStatus.FAILED, signature=signatures[2]),
        ]
        plan = self._plan(primary, existing)
        self.assertEqual([state.status for state in plan.states], ["valid", "running", "failed"])
        self.assertEqual(plan.pending_primary_job_ids(), (3,))

    def test_signature_matches_safe_preflight_identity(self) -> None:
        plan = self._plan([self._job(1, {"gap": "100[mm]", "xoff": "0[mm]"})])
        state = plan.states[0]
        expected = build_run_signature(
            "comsol",
            state.parameters,
            plan.output_formulas,
            plan.run_context,
        )
        self.assertEqual(state.signature, expected)

    def test_exports_portable_campaign_reports(self) -> None:
        plan = self._plan([self._job(1, {"gap": "100[mm]", "xoff": "0[mm]"})])
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = write_reference_campaign_csv(Path(temp_dir) / "plan.csv", plan)
            html_path = write_reference_campaign_html(Path(temp_dir) / "plan.html", plan)
            csv_text = csv_path.read_text(encoding="utf-8")
            html_text = html_path.read_text(encoding="utf-8")
        self.assertIn("primary_job_id", csv_text)
        self.assertIn("Reference Validation Campaign", html_text)
        self.assertNotIn("C:\\", html_text)

    def test_rejects_missing_mapping_and_reference_inputs(self) -> None:
        primary = [self._job(1, {"gap": "100[mm]", "xoff": "0[mm]"})]
        with self.assertRaisesRegex(ValueError, "input mapping"):
            build_reference_campaign_plan(
                primary,
                [],
                {},
                output_formulas={},
                run_context={},
                existing_jobs=[],
            )
        with self.assertRaisesRegex(ValueError, "missing mapped"):
            build_reference_campaign_plan(
                primary,
                [InputMapping("gap", "air_gap")],
                {"other": 1},
                output_formulas={},
                run_context={},
                existing_jobs=[],
            )


if __name__ == "__main__":
    unittest.main()
