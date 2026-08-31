import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from simulation_assistant.progress import format_duration, inspect_job_progress
from simulation_assistant.types import Job, JobStatus


class RunProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.started = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
        self.job = Job(
            id=7,
            batch_name="monitor-test",
            adapter="comsol",
            status=JobStatus.RUNNING,
            parameters={},
            output_formulas={},
            result=None,
            error=None,
            artifact_dir=str(self.root),
            attempts=1,
            created_at=self.started.isoformat(),
            started_at=self.started.isoformat(),
            finished_at=None,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_log(self, text: str, modified_at: datetime) -> Path:
        path = self.root / "comsol.log"
        path.write_text(text, encoding="utf-8")
        timestamp = modified_at.timestamp()
        os.utime(path, (timestamp, timestamp))
        return path

    def test_reads_real_comsol_progress_and_saving_stage(self) -> None:
        modified = self.started + timedelta(seconds=70)
        self.write_log(
            """<---- Stationary Solver 1 in Study 1/Solution 1 (sol1) --------
Current Progress:   4 % - Dependent Variables 1
Current Progress: 100 % - Solving linear system
Run time: 60 s.
Saving model: C:\\private\\output.mph
""",
            modified,
        )

        progress = inspect_job_progress(
            self.job,
            now=self.started + timedelta(seconds=75),
        )

        self.assertEqual(progress.percent, 100)
        self.assertEqual(progress.stage, "Saving results")
        self.assertEqual(progress.message, "Saving the output model")
        self.assertEqual(progress.elapsed_seconds, 75)
        self.assertEqual(progress.idle_seconds, 5)
        self.assertFalse(progress.stale)
        self.assertIn("100%", progress.summary)
        self.assertTrue(progress.log_exists)

    def test_recognizes_completed_progress(self) -> None:
        self.write_log(
            "Current Progress: 100 % - Done\n",
            self.started + timedelta(seconds=10),
        )

        progress = inspect_job_progress(
            replace(self.job, status=JobStatus.SUCCEEDED),
            now=self.started + timedelta(seconds=11),
        )

        self.assertEqual(progress.percent, 100)
        self.assertEqual(progress.stage, "Completed")
        self.assertFalse(progress.stale)

    def test_warns_when_a_running_job_has_no_recent_activity(self) -> None:
        progress = inspect_job_progress(
            self.job,
            now=self.started + timedelta(seconds=301),
            stale_after_seconds=300,
        )

        self.assertEqual(progress.stage, "Starting solver")
        self.assertTrue(progress.stale)
        self.assertIn("No recent activity", progress.summary)
        self.assertFalse(progress.log_exists)

    def test_ignores_a_log_from_an_earlier_attempt(self) -> None:
        self.write_log("Current Progress: 100 % - Done\n", self.started)
        newer_job = replace(
            self.job,
            started_at=(self.started + timedelta(seconds=20)).isoformat(),
        )

        progress = inspect_job_progress(
            newer_job,
            now=self.started + timedelta(seconds=30),
        )

        self.assertFalse(progress.log_exists)
        self.assertIsNone(progress.percent)
        self.assertEqual(progress.message, "Waiting for current-attempt log output")

    def test_bounds_and_sanitizes_the_log_tail(self) -> None:
        lines = [f"line {index}\x00" for index in range(20)]
        self.write_log("\n".join(lines), self.started + timedelta(seconds=1))

        progress = inspect_job_progress(
            self.job,
            now=self.started + timedelta(seconds=2),
            max_tail_lines=4,
        )

        self.assertEqual(progress.log_tail, ["line 16", "line 17", "line 18", "line 19"])

    def test_formats_elapsed_time(self) -> None:
        self.assertEqual(format_duration(8), "8s")
        self.assertEqual(format_duration(68), "1m 8s")
        self.assertEqual(format_duration(3668), "1h 1m 8s")


if __name__ == "__main__":
    unittest.main()
