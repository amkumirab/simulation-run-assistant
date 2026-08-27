from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from simulation_assistant.formulas import validate_output_formulas
from simulation_assistant.preflight import build_run_signature
from simulation_assistant.types import Job, JobStatus


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    """Small SQLite repository with atomic job claiming."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_name TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'queued', 'running', 'succeeded', 'failed', 'cancelled'
                        )
                    ),
                    parameters TEXT NOT NULL,
                    output_formulas TEXT NOT NULL DEFAULT '{}',
                    run_signature TEXT,
                    run_context TEXT NOT NULL DEFAULT '{}',
                    result TEXT,
                    error TEXT,
                    artifact_dir TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status_id ON jobs(status, id);
                CREATE TABLE IF NOT EXISTS queue_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO queue_settings(key, value)
                VALUES ('paused', '0');
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "output_formulas" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN output_formulas TEXT NOT NULL "
                    "DEFAULT '{}'"
                )
            if "run_signature" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN run_signature TEXT")
            if "run_context" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN run_context TEXT NOT NULL DEFAULT '{}'"
                )
            schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
            ).fetchone()
            if schema is not None and "cancelled" not in str(schema["sql"]).lower():
                self._migrate_status_constraint(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_signature_status "
                "ON jobs(run_signature, status, id)"
            )

    @staticmethod
    def _migrate_status_constraint(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            ALTER TABLE jobs RENAME TO jobs_before_status_migration;
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_name TEXT NOT NULL,
                adapter TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'queued', 'running', 'succeeded', 'failed', 'cancelled'
                    )
                ),
                parameters TEXT NOT NULL,
                output_formulas TEXT NOT NULL DEFAULT '{}',
                run_signature TEXT,
                run_context TEXT NOT NULL DEFAULT '{}',
                result TEXT,
                error TEXT,
                artifact_dir TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );
            INSERT INTO jobs(
                id, batch_name, adapter, status, parameters, output_formulas,
                run_signature, run_context, result, error, artifact_dir, attempts,
                created_at, started_at, finished_at
            )
            SELECT
                id, batch_name, adapter, status, parameters, output_formulas,
                run_signature, run_context, result, error, artifact_dir, attempts,
                created_at, started_at, finished_at
            FROM jobs_before_status_migration;
            DROP TABLE jobs_before_status_migration;
            CREATE INDEX idx_jobs_status_id ON jobs(status, id);
            COMMIT;
            """
        )

    def enqueue_batch(
        self,
        batch_name: str,
        adapter: str,
        parameter_sets: Iterable[dict[str, Any]],
        output_formulas: dict[str, str] | None = None,
        run_context: dict[str, Any] | None = None,
    ) -> list[int]:
        created_at = utc_now()
        formulas = validate_output_formulas(output_formulas)
        context = dict(run_context or {})
        context_json = json.dumps(context, sort_keys=True)
        rows = [
            (
                batch_name,
                adapter,
                JobStatus.QUEUED.value,
                json.dumps(parameters, sort_keys=True),
                json.dumps(formulas, sort_keys=True),
                (
                    build_run_signature(adapter, parameters, formulas, context)
                    if run_context is not None
                    else None
                ),
                context_json,
                created_at,
            )
            for parameters in parameter_sets
        ]
        if not rows:
            raise ValueError("A batch must contain at least one job")

        with self._connect() as connection:
            cursor = connection.cursor()
            ids: list[int] = []
            for row in rows:
                cursor.execute(
                    """
                    INSERT INTO jobs(
                        batch_name, adapter, status, parameters,
                        output_formulas, run_signature, run_context, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    row,
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def claim_next(self) -> Job | None:
        """Atomically move the oldest queued job to running."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._queue_paused(connection):
                connection.commit()
                return None
            row = connection.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY id LIMIT 1",
                (JobStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None

            started_at = utc_now()
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, started_at = ?, finished_at = NULL,
                    error = NULL, attempts = attempts + 1
                WHERE id = ?
                """,
                (JobStatus.RUNNING.value, started_at, row["id"]),
            )
            connection.commit()
        return self.get(int(row["id"]))

    def claim(self, job_id: int) -> Job:
        """Atomically move one specific queued job to running."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._queue_paused(connection):
                raise ValueError("Run queue is paused")
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Job {job_id} was not found")
            if row["status"] != JobStatus.QUEUED.value:
                raise ValueError(f"Job {job_id} is not queued")

            connection.execute(
                """
                UPDATE jobs
                SET status = ?, started_at = ?, finished_at = NULL,
                    error = NULL, attempts = attempts + 1
                WHERE id = ?
                """,
                (JobStatus.RUNNING.value, utc_now(), job_id),
            )
            connection.commit()
        return self.get(job_id)

    def mark_succeeded(
        self,
        job_id: int,
        result: dict[str, Any],
        artifact_dir: str,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, result = ?, artifact_dir = ?, error = NULL,
                    finished_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    JobStatus.SUCCEEDED.value,
                    json.dumps(result, sort_keys=True),
                    artifact_dir,
                    utc_now(),
                    job_id,
                    JobStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Job {job_id} is not running")

    def mark_failed(self, job_id: int, error: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, finished_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    JobStatus.FAILED.value,
                    error[:4000],
                    utc_now(),
                    job_id,
                    JobStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Job {job_id} is not running")

    def retry(self, job_id: int) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = NULL, result = NULL, artifact_dir = NULL,
                    started_at = NULL, finished_at = NULL
                WHERE id = ? AND status IN (?, ?)
                """,
                (
                    JobStatus.QUEUED.value,
                    job_id,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(
                    f"Job {job_id} does not exist or is not failed or cancelled"
                )

    def cancel(self, job_id: int) -> None:
        """Cancel one queued job without deleting its history."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, finished_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    JobStatus.CANCELLED.value,
                    "Cancelled before execution",
                    utc_now(),
                    job_id,
                    JobStatus.QUEUED.value,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Job {job_id} does not exist or is not queued")

    def is_queue_paused(self) -> bool:
        with self._connect() as connection:
            return self._queue_paused(connection)

    def set_queue_paused(self, paused: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO queue_settings(key, value) VALUES ('paused', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("1" if paused else "0",),
            )

    def recover_interrupted(self, *, requeue: bool) -> list[int]:
        """Resolve jobs left running after an interrupted worker process."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT id FROM jobs WHERE status = ? ORDER BY id",
                (JobStatus.RUNNING.value,),
            ).fetchall()
            job_ids = [int(row["id"]) for row in rows]
            if not job_ids:
                connection.commit()
                return []
            if requeue:
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = ?, error = NULL, result = NULL, artifact_dir = NULL,
                        started_at = NULL, finished_at = NULL
                    WHERE status = ?
                    """,
                    (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
                )
            else:
                connection.execute(
                    """
                    UPDATE jobs
                    SET status = ?, error = ?, finished_at = ?
                    WHERE status = ?
                    """,
                    (
                        JobStatus.FAILED.value,
                        "Interrupted run recovered by user",
                        utc_now(),
                        JobStatus.RUNNING.value,
                    ),
                )
            connection.commit()
        return job_ids

    def get(self, job_id: int) -> Job:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Job {job_id} was not found")
        return self._to_job(row)

    def list(self, status: JobStatus | None = None, limit: int = 100) -> list[Job]:
        with self._connect() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status.value, limit),
                ).fetchall()
        return [self._to_job(row) for row in rows]

    def list_by_run_signatures(self, signatures: Iterable[str]) -> list[Job]:
        unique = tuple(dict.fromkeys(str(signature) for signature in signatures))
        if not unique:
            return []
        placeholders = ", ".join("?" for _ in unique)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE run_signature IN ({placeholders}) "
                "ORDER BY id DESC",
                unique,
            ).fetchall()
        return [self._to_job(row) for row in rows]

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in JobStatus}
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
            ).fetchall()
        for row in rows:
            counts[str(row["status"])] = int(row["count"])
        return counts

    @staticmethod
    def _queue_paused(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            "SELECT value FROM queue_settings WHERE key = 'paused'"
        ).fetchone()
        return row is not None and str(row["value"]) == "1"

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _to_job(row: sqlite3.Row) -> Job:
        run_context = json.loads(row["run_context"] or "{}")
        if not isinstance(run_context, dict):
            run_context = {}
        return Job(
            id=int(row["id"]),
            batch_name=str(row["batch_name"]),
            adapter=str(row["adapter"]),
            status=JobStatus(row["status"]),
            parameters=json.loads(row["parameters"]),
            output_formulas=json.loads(row["output_formulas"] or "{}"),
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            artifact_dir=row["artifact_dir"],
            attempts=int(row["attempts"]),
            created_at=str(row["created_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            run_signature=row["run_signature"],
            run_context=run_context,
        )
