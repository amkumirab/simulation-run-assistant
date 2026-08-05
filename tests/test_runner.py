import json
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.runner import SimulationRunner
from simulation_assistant.storage import JobStore
from simulation_assistant.types import JobStatus


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = JobStore(self.root / "jobs.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_successful_job_writes_artifacts(self) -> None:
        job_id = self.store.enqueue_batch(
            "test-batch",
            "mock-em",
            [{"frequency_ghz": 10, "width_mm": 20}],
        )[0]

        summary = SimulationRunner(self.store, self.root / "artifacts").run_pending()

        self.assertEqual(summary.succeeded, 1)
        job = self.store.get(job_id)
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        output_dir = Path(job.artifact_dir or "")
        self.assertTrue((output_dir / "result.json").exists())
        self.assertTrue((output_dir / "response.svg").exists())
        payload = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["job_id"], job_id)

    def test_failed_job_can_be_retried(self) -> None:
        job_id = self.store.enqueue_batch(
            "failure-demo", "mock-em", [{"force_failure": True}]
        )[0]
        runner = SimulationRunner(self.store, self.root / "artifacts")

        summary = runner.run_pending()

        self.assertEqual(summary.failed, 1)
        self.assertEqual(self.store.get(job_id).status, JobStatus.FAILED)
        self.store.retry(job_id)
        retried = self.store.get(job_id)
        self.assertEqual(retried.status, JobStatus.QUEUED)
        self.assertEqual(retried.attempts, 1)

    def test_unknown_adapter_only_fails_its_own_job(self) -> None:
        self.store.enqueue_batch("unknown", "not-installed", [{"x": 1}])
        self.store.enqueue_batch("valid", "mock-em", [{"frequency_ghz": 10}])

        summary = SimulationRunner(self.store, self.root / "artifacts").run_pending()

        self.assertEqual(summary.processed, 2)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.succeeded, 1)

    def test_runs_one_selected_job_without_consuming_the_queue(self) -> None:
        first_id = self.store.enqueue_batch(
            "first", "mock-em", [{"frequency_ghz": 8}]
        )[0]
        selected_id = self.store.enqueue_batch(
            "selected", "mock-em", [{"frequency_ghz": 12}]
        )[0]

        summary = SimulationRunner(self.store, self.root / "artifacts").run_job(
            selected_id
        )

        self.assertEqual(summary.succeeded, 1)
        self.assertEqual(self.store.get(first_id).status, JobStatus.QUEUED)
        self.assertEqual(self.store.get(selected_id).status, JobStatus.SUCCEEDED)

    def test_computed_outputs_are_saved_with_the_result(self) -> None:
        job_id = self.store.enqueue_batch(
            "formula-demo",
            "mock-em",
            [{"frequency_ghz": 10, "width_mm": 20}],
            output_formulas={"transmission_percent": "10 ** (s21_db / 10) * 100"},
        )[0]

        summary = SimulationRunner(self.store, self.root / "artifacts").run_job(job_id)

        job = self.store.get(job_id)
        self.assertEqual(summary.succeeded, 1)
        self.assertIn("transmission_percent", job.result["metrics"])
        self.assertEqual(job.result["metadata"]["formula_errors"], {})

    def test_formula_error_does_not_discard_a_successful_simulation(self) -> None:
        job_id = self.store.enqueue_batch(
            "formula-error",
            "mock-em",
            [{"frequency_ghz": 10}],
            output_formulas={"coupling": "mutual_inductance / primary_inductance"},
        )[0]

        summary = SimulationRunner(self.store, self.root / "artifacts").run_job(job_id)

        job = self.store.get(job_id)
        self.assertEqual(summary.succeeded, 1)
        self.assertEqual(job.status, JobStatus.SUCCEEDED)
        self.assertIn("not available", job.result["metadata"]["formula_errors"]["coupling"])


if __name__ == "__main__":
    unittest.main()
