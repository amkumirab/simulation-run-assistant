import sqlite3
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.storage import JobStore
from simulation_assistant.types import JobStatus


class StorageMigrationTests(unittest.TestCase):
    def test_adds_output_formulas_to_an_existing_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "legacy.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """
                    CREATE TABLE jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        batch_name TEXT NOT NULL,
                        adapter TEXT NOT NULL,
                        status TEXT NOT NULL,
                        parameters TEXT NOT NULL,
                        result TEXT,
                        error TEXT,
                        artifact_dir TEXT,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            store = JobStore(database)
            store.initialize()
            job_id = store.enqueue_batch(
                "migrated",
                "mock-em",
                [{"x": 1}],
                output_formulas={"double_value": "value * 2"},
            )[0]

            self.assertEqual(
                store.get(job_id).output_formulas,
                {"double_value": "value * 2"},
            )
            store.cancel(job_id)
            self.assertEqual(store.get(job_id).status, JobStatus.CANCELLED)
            connection = sqlite3.connect(database)
            try:
                schema = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE name = 'jobs'"
                ).fetchone()[0]
                columns = {
                    row[1]
                    for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
                }
            finally:
                connection.close()
            self.assertIn("cancelled", schema)
            self.assertIn("run_signature", columns)
            self.assertIn("run_context", columns)
            self.assertIn("stop_requested_at", columns)
            self.assertIn("pinned", columns)

            store.set_pinned(job_id, True)
            self.assertTrue(store.get(job_id).pinned)
            store.record_retention_event(
                action="delete_output_model",
                job_id=job_id,
                artifact_name="job-000001/output.mph",
                bytes_reclaimed=1024,
            )
            history = store.retention_history()
            self.assertEqual(history[0]["job_id"], job_id)
            self.assertEqual(history[0]["bytes_reclaimed"], 1024)

    def test_saves_and_updates_reference_validation_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobStore(Path(temp_dir) / "jobs.db")
            store.initialize()
            job_ids = store.enqueue_batch(
                "validation",
                "mock",
                [{"gap": 0.1}, {"gap": 0.1}],
            )
            first_id = store.save_reference_validation(
                job_ids[0],
                job_ids[1],
                "passed",
                {"relative_error_percent": 2.5},
            )
            second_id = store.save_reference_validation(
                job_ids[0],
                job_ids[1],
                "warning",
                {"relative_error_percent": 8.5},
            )
            records = store.list_reference_validations()

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "warning")
        self.assertEqual(records[0]["details"]["relative_error_percent"], 8.5)


if __name__ == "__main__":
    unittest.main()
