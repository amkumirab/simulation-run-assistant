import sqlite3
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.storage import JobStore


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


if __name__ == "__main__":
    unittest.main()
