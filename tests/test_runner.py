import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from simulation_assistant.adapters.base import SimulationCancelled
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
            run_context={"model": {"name": "demo.mph"}},
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
        self.assertEqual(payload["run_signature"], job.run_signature)
        self.assertEqual(payload["run_context"], {"model": {"name": "demo.mph"}})

    def test_failed_job_can_be_retried(self) -> None:
        job_id = self.store.enqueue_batch(
            "failure-demo", "mock-em", [{"force_failure": True}]
        )[0]
        runner = SimulationRunner(self.store, self.root / "artifacts")

        summary = runner.run_pending()

        self.assertEqual(summary.failed, 1)
        failed = self.store.get(job_id)
        self.assertEqual(failed.status, JobStatus.FAILED)
        self.assertEqual(Path(failed.artifact_dir or ""), self.root / "artifacts" / "job-000001")
        self.assertTrue(Path(failed.artifact_dir or "").is_dir())
        self.store.retry(job_id)
        retried = self.store.get(job_id)
        self.assertEqual(retried.status, JobStatus.QUEUED)
        self.assertEqual(retried.attempts, 1)
        self.assertIsNone(retried.artifact_dir)

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

    def test_paused_queue_does_not_claim_waiting_jobs(self) -> None:
        job_id = self.store.enqueue_batch(
            "paused", "mock-em", [{"frequency_ghz": 10}]
        )[0]
        self.store.set_queue_paused(True)

        summary = SimulationRunner(self.store, self.root / "artifacts").run_pending()

        self.assertEqual(summary.processed, 0)
        self.assertEqual(self.store.get(job_id).status, JobStatus.QUEUED)
        self.assertTrue(JobStore(self.store.path).is_queue_paused())

        self.store.set_queue_paused(False)
        resumed = SimulationRunner(self.store, self.root / "artifacts").run_pending()
        self.assertEqual(resumed.succeeded, 1)

    def test_cancelled_job_keeps_history_and_can_be_requeued(self) -> None:
        job_id = self.store.enqueue_batch(
            "cancel-demo", "mock-em", [{"frequency_ghz": 10}]
        )[0]

        self.store.cancel(job_id)

        cancelled = self.store.get(job_id)
        self.assertEqual(cancelled.status, JobStatus.CANCELLED)
        self.assertEqual(cancelled.error, "Cancelled before execution")
        self.assertIsNotNone(cancelled.finished_at)
        self.store.retry(job_id)
        retried = self.store.get(job_id)
        self.assertEqual(retried.status, JobStatus.QUEUED)
        self.assertIsNone(retried.stop_requested_at)

    def test_stop_request_cancels_an_active_adapter_run(self) -> None:
        job_id = self.store.enqueue_batch("active", "stop-test", [{"x": 1}])[0]

        class StopAdapter:
            name = "stop-test"

            def run(self, parameters, *, work_dir=None, cancel_requested=None):
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if cancel_requested and cancel_requested():
                        raise SimulationCancelled("Stop requested by user")
                    time.sleep(0.01)
                raise AssertionError("The external stop request was not observed")

        runner = SimulationRunner(
            self.store,
            self.root / "artifacts",
            adapters=[StopAdapter()],
        )
        summaries = []
        worker = threading.Thread(
            target=lambda: summaries.append(runner.run_job(job_id)),
            daemon=True,
        )
        worker.start()
        deadline = time.monotonic() + 2
        while self.store.get(job_id).status != JobStatus.RUNNING:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

        self.store.request_stop(job_id)
        worker.join(timeout=2)

        job = self.store.get(job_id)
        self.assertFalse(worker.is_alive())
        self.assertEqual(summaries[0].cancelled, 1)
        self.assertEqual(summaries[0].failed, 0)
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertIsNotNone(job.stop_requested_at)
        self.assertEqual(job.error, "Stop requested by user")
        self.store.retry(job_id)
        self.assertIsNone(self.store.get(job_id).stop_requested_at)

    def test_recovers_interrupted_jobs_to_queue_or_failure(self) -> None:
        first_id, second_id = self.store.enqueue_batch(
            "interrupted",
            "mock-em",
            [{"frequency_ghz": 8}, {"frequency_ghz": 10}],
        )
        self.store.claim(first_id)
        self.store.claim(second_id)
        self.store.request_stop(first_id)

        recovered = self.store.recover_interrupted(requeue=True)

        self.assertEqual(recovered, [first_id, second_id])
        self.assertEqual(self.store.get(first_id).status, JobStatus.QUEUED)
        self.assertIsNone(self.store.get(first_id).stop_requested_at)
        self.assertEqual(self.store.get(first_id).attempts, 1)
        self.store.claim(first_id)
        failed = self.store.recover_interrupted(requeue=False)
        self.assertEqual(failed, [first_id])
        self.assertEqual(self.store.get(first_id).status, JobStatus.FAILED)
        self.assertIn("Interrupted run", self.store.get(first_id).error or "")

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
