import json
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.preflight import (
    build_comsol_run_context,
    build_preflight_plan,
    build_run_signature,
)
from simulation_assistant.storage import JobStore
from simulation_assistant.types import Job, JobStatus


class RunPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.model = self.root / "private" / "wireless.mph"
        self.model.parent.mkdir()
        self.model.write_bytes(b"model-v1")
        self.context = build_comsol_run_context(
            self.model,
            study_tag="std1",
            job_tag=None,
            plot_tags=["pg2", "pg1", "pg1"],
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_model_context_is_path_free_and_changes_with_the_model(self) -> None:
        serialized = json.dumps(self.context, sort_keys=True)
        first = build_run_signature(
            "comsol", {"frequency": "85[kHz]"}, {}, self.context
        )

        self.model.write_bytes(b"model-version-two")
        changed_context = build_comsol_run_context(
            self.model,
            study_tag="std1",
            job_tag=None,
            plot_tags=["pg1", "pg2"],
        )
        second = build_run_signature(
            "comsol", {"frequency": "85[kHz]"}, {}, changed_context
        )

        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(self.context["model"]["name"], "wireless.mph")
        self.assertEqual(self.context["plot_tags"], ["pg1", "pg2"])
        self.assertNotEqual(first, second)

    def test_contract_revision_is_part_of_the_safe_run_identity(self) -> None:
        contract = self.root / "model-contract.json"
        contract.write_text('{"version":"1.0.0"}', encoding="utf-8")
        first = build_comsol_run_context(
            self.model,
            study_tag="std1",
            job_tag=None,
            contract_path=contract,
        )
        contract.write_text('{"version":"2.0.0","changed":true}', encoding="utf-8")
        second = build_comsol_run_context(
            self.model,
            study_tag="std1",
            job_tag=None,
            contract_path=contract,
        )

        self.assertNotEqual(first["contract"], second["contract"])
        self.assertNotIn(str(self.root), json.dumps(second))

    def test_signature_is_stable_for_mapping_order(self) -> None:
        first = build_run_signature(
            "comsol",
            {"gap": "15[cm]", "frequency": "85[kHz]"},
            {"efficiency": "power_out / power_in", "ratio": "a / b"},
            self.context,
        )
        second = build_run_signature(
            "comsol",
            {"frequency": "85[kHz]", "gap": "15[cm]"},
            {"ratio": "a / b", "efficiency": "power_out / power_in"},
            self.context,
        )

        self.assertEqual(first, second)

    def test_classifies_existing_and_in_request_duplicates(self) -> None:
        formulas = {"score": "field_max / duration"}
        succeeded_parameters = {"frequency": "80[kHz]"}
        scheduled_parameters = {"frequency": "85[kHz]"}
        failed_parameters = {"frequency": "90[kHz]"}
        new_parameters = {"frequency": "95[kHz]"}
        existing = [
            self._job(1, JobStatus.SUCCEEDED, succeeded_parameters, formulas),
            self._job(2, JobStatus.SUCCEEDED, scheduled_parameters, formulas),
            self._job(3, JobStatus.QUEUED, scheduled_parameters, formulas),
            self._job(4, JobStatus.FAILED, failed_parameters, formulas),
        ]

        plan = build_preflight_plan(
            [
                succeeded_parameters,
                scheduled_parameters,
                failed_parameters,
                new_parameters,
                new_parameters,
            ],
            adapter="comsol",
            output_formulas=formulas,
            run_context=self.context,
            existing_jobs=existing,
        )

        self.assertEqual(len(plan.requested), 5)
        self.assertEqual(
            [item.parameters for item in plan.new],
            [failed_parameters, new_parameters],
        )
        self.assertEqual(plan.successful_job_ids, (1,))
        self.assertEqual(plan.scheduled_job_ids, (3,))
        self.assertEqual(len(plan.repeated), 1)
        self.assertEqual(plan.duplicate_count, 3)

    def test_store_persists_and_finds_safe_run_identity(self) -> None:
        store = JobStore(self.root / "jobs.db")
        store.initialize()
        job_id = store.enqueue_batch(
            "preflight",
            "comsol",
            [{"frequency": "85[kHz]"}],
            run_context=self.context,
        )[0]

        job = store.get(job_id)
        matches = store.list_by_run_signatures([job.run_signature or ""])

        self.assertEqual([match.id for match in matches], [job_id])
        self.assertEqual(job.run_context, self.context)
        self.assertEqual(len(job.run_signature or ""), 64)
        self.assertNotIn(str(self.root), json.dumps(job.to_dict(), sort_keys=True))

    def _job(
        self,
        job_id: int,
        status: JobStatus,
        parameters: dict[str, str],
        formulas: dict[str, str],
    ) -> Job:
        return Job(
            id=job_id,
            batch_name="preflight",
            adapter="comsol",
            status=status,
            parameters=parameters,
            output_formulas=formulas,
            result={} if status == JobStatus.SUCCEEDED else None,
            error=None,
            artifact_dir=None,
            attempts=1,
            created_at="2026-08-26T08:00:00+00:00",
            started_at=None,
            finished_at=None,
            run_signature=build_run_signature(
                "comsol", parameters, formulas, self.context
            ),
            run_context=self.context,
        )


if __name__ == "__main__":
    unittest.main()
