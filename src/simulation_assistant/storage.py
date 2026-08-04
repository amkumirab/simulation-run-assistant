from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

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
                        status IN ('queued', 'running', 'succeeded', 'failed')
                    ),
                    parameters TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    artifact_dir TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status_id ON jobs(status, id);
                """
            )

    def enqueue_batch(
        self,
        batch_name: str,
        adapter: str,
        parameter_sets: Iterable[dict[str, Any]],
    ) -> list[int]:
        created_at = utc_now()
        rows = [
            (
                batch_name,
                adapter,
                JobStatus.QUEUED.value,
                json.dumps(parameters, sort_keys=True),
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
                    INSERT INTO jobs(batch_name, adapter, status, parameters, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    row,
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def claim_next(self) -> Job | None:
        """Atomically move the oldest queued job to running."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
                WHERE id = ? AND status = ?
                """,
                (JobStatus.QUEUED.value, job_id, JobStatus.FAILED.value),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Job {job_id} does not exist or is not failed")

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

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in JobStatus}
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
            ).fetchall()
        for row in rows:
            counts[str(row["status"])] = int(row["count"])
        return counts

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
        return Job(
            id=int(row["id"]),
            batch_name=str(row["batch_name"]),
            adapter=str(row["adapter"]),
            status=JobStatus(row["status"]),
            parameters=json.loads(row["parameters"]),
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            artifact_dir=row["artifact_dir"],
            attempts=int(row["attempts"]),
            created_at=str(row["created_at"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )
