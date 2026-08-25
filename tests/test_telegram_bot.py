import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from simulation_assistant.notifications import NullNotifier
from simulation_assistant.storage import JobStore
from simulation_assistant.telegram_bot import (
    TelegramBotController,
    discover_chat_ids,
)
from simulation_assistant.types import JobStatus


class FakeTelegramApi:
    token = "test-token"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.updates: list[dict] = []

    def send_message(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))

    def get_updates(self, offset=None, timeout_seconds=25):
        return self.updates


class TelegramBotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = JobStore(self.root / "jobs.db")
        self.store.initialize()
        self.api = FakeTelegramApi()
        self.controller = TelegramBotController(
            api=self.api,
            store=self.store,
            artifact_root=self.root / "artifacts",
            allowed_chat_id="12345",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def send(self, text: str, chat_id: str = "12345") -> str | None:
        self.controller.handle_update(
            {"message": {"chat": {"id": int(chat_id)}, "text": text}}
        )
        return self.api.sent[-1][1] if self.api.sent else None

    def test_ignores_unauthorized_chat(self) -> None:
        self.send("/status", chat_id="99999")

        self.assertEqual(self.api.sent, [])

    def test_status_reports_all_queue_counts(self) -> None:
        self.store.enqueue_batch("demo", "mock-em", [{"frequency_ghz": 10}])

        response = self.send("/status")

        self.assertIn("Queued: 1", response or "")
        self.assertIn("Succeeded: 0", response or "")
        self.assertIn("Cancelled: 0", response or "")
        self.assertIn("Control: ready", response or "")

    def test_controls_waiting_jobs_remotely(self) -> None:
        job_id = self.store.enqueue_batch(
            "remote-control", "mock-em", [{"frequency_ghz": 10}]
        )[0]

        paused = self.send("/pause")
        blocked = self.send("/run 1")
        cancelled = self.send(f"/cancel {job_id}")

        self.assertIn("Queue paused", paused or "")
        self.assertIn("Queue is paused", blocked or "")
        self.assertIn("was cancelled", cancelled or "")
        self.assertEqual(self.store.get(job_id).status, JobStatus.CANCELLED)
        self.assertIn("Queue resumed", self.send("/resume") or "")
        self.assertIn("returned to the queue", self.send(f"/retry {job_id}") or "")
        self.assertEqual(self.store.get(job_id).status, JobStatus.QUEUED)

    def test_run_processes_a_bounded_number_of_jobs(self) -> None:
        first, second = self.store.enqueue_batch(
            "demo",
            "mock-em",
            [{"frequency_ghz": 8}, {"frequency_ghz": 10}],
        )

        with patch(
            "simulation_assistant.telegram_bot.TelegramNotifier",
            return_value=NullNotifier(),
        ):
            response = self.send("/run 1")

        self.assertIn("Processed 1: 1 succeeded", response or "")
        self.assertEqual(self.store.get(first).status, JobStatus.SUCCEEDED)
        self.assertEqual(self.store.get(second).status, JobStatus.QUEUED)

    def test_retry_requeues_failed_job(self) -> None:
        job_id = self.store.enqueue_batch("demo", "mock-em", [{"x": 1}])[0]
        self.store.claim_next()
        self.store.mark_failed(job_id, "demo failure")

        response = self.send(f"/retry {job_id}")

        self.assertIn("returned to the queue", response or "")
        self.assertEqual(self.store.get(job_id).status, JobStatus.QUEUED)

    def test_discovers_chat_id_from_recent_message(self) -> None:
        self.api.updates = [
            {
                "update_id": 7,
                "message": {
                    "chat": {
                        "id": 12345,
                        "type": "private",
                        "username": "operator",
                    },
                    "text": "/start",
                },
            }
        ]

        chats = discover_chat_ids(self.api)

        self.assertEqual(
            chats,
            [{"id": "12345", "type": "private", "title": "operator"}],
        )


if __name__ == "__main__":
    unittest.main()
