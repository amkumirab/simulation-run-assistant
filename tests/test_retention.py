import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from simulation_assistant.retention import (
    RetentionPolicy,
    apply_storage_plan,
    build_storage_plan,
)
from simulation_assistant.storage import JobStore


class RetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.store = JobStore(self.root / "runs.db")
        self.store.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _successful_job(
        self,
        batch: str,
        content: bytes = b"result",
        *,
        finished_at: str | None = None,
    ) -> int:
        job_id = self.store.enqueue_batch(batch, "mock-em", [{"x": 1}])[0]
        self.store.claim(job_id)
        artifact_dir = self.artifacts / f"job-{job_id:06d}"
        artifact_dir.mkdir()
        (artifact_dir / "result.json").write_bytes(content)
        self.store.mark_succeeded(job_id, {"metrics": {"value": job_id}}, str(artifact_dir))
        if finished_at:
            connection = sqlite3.connect(self.store.path)
            try:
                connection.execute(
                    "UPDATE jobs SET finished_at = ? WHERE id = ?",
                    (finished_at, job_id),
                )
                connection.commit()
            finally:
                connection.close()
        return job_id

    def test_plan_protects_active_pinned_latest_and_selected_jobs(self) -> None:
        old_id = self._successful_job("sweep", b"old", finished_at="2025-01-01T00:00:00+00:00")
        pinned_id = self._successful_job("sweep", b"pinned")
        selected_id = self._successful_job("other", b"selected")
        latest_id = self._successful_job("sweep", b"latest")
        self.store.set_pinned(pinned_id, True)
        active_id = self.store.enqueue_batch("active", "mock-em", [{"x": 2}])[0]

        plan = build_storage_plan(
            self.store,
            self.artifacts,
            RetentionPolicy(keep_days=30, keep_latest_per_batch=1),
            protected_job_ids=[selected_id],
            now=datetime(2026, 9, 10, tzinfo=timezone.utc),
        )

        actions = {action.job_id: action for action in plan.actions}
        self.assertIn(old_id, actions)
        entries = {entry.job_id: entry for entry in plan.entries}
        self.assertIn("pinned", entries[pinned_id].protected_reasons)
        self.assertIn("selected_best_result", entries[selected_id].protected_reasons)
        self.assertIn("latest_per_batch", entries[latest_id].protected_reasons)
        self.assertNotIn(active_id, entries)

    def test_apply_deletes_only_the_previewed_directory_and_keeps_job_history(self) -> None:
        old_id = self._successful_job("sweep", b"123456")
        self._successful_job("sweep", b"latest")
        old_dir = self.artifacts / f"job-{old_id:06d}"
        plan = build_storage_plan(
            self.store,
            self.artifacts,
            RetentionPolicy(keep_latest_per_batch=1),
        )

        result = apply_storage_plan(plan, self.store)

        self.assertEqual(result.completed_actions, 1)
        self.assertEqual(result.reclaimed_bytes, 6)
        self.assertFalse(old_dir.exists())
        self.assertIsNone(self.store.get(old_id).artifact_dir)
        self.assertEqual(self.store.get(old_id).result["metrics"]["value"], old_id)
        self.assertEqual(self.store.retention_history()[0]["job_id"], old_id)

    def test_output_model_cleanup_preserves_smaller_results(self) -> None:
        job_id = self._successful_job("sweep")
        artifact_dir = self.artifacts / f"job-{job_id:06d}"
        output = artifact_dir / "output.mph"
        output.write_bytes(b"model-data")
        other_id = self._successful_job("sweep")
        self.store.set_pinned(other_id, True)
        plan = build_storage_plan(
            self.store,
            self.artifacts,
            RetentionPolicy(remove_output_models=True),
        )

        result = apply_storage_plan(plan, self.store)

        self.assertEqual(result.completed_actions, 1)
        self.assertFalse(output.exists())
        self.assertTrue((artifact_dir / "result.json").exists())
        self.assertEqual(Path(self.store.get(job_id).artifact_dir), artifact_dir)

    def test_changed_artifact_is_skipped_after_preview(self) -> None:
        old_id = self._successful_job("sweep", b"old")
        self._successful_job("sweep", b"latest")
        artifact_dir = self.artifacts / f"job-{old_id:06d}"
        plan = build_storage_plan(
            self.store,
            self.artifacts,
            RetentionPolicy(keep_latest_per_batch=1),
        )
        (artifact_dir / "new.log").write_bytes(b"changed")

        result = apply_storage_plan(plan, self.store)

        self.assertEqual(result.completed_actions, 0)
        self.assertEqual(result.skipped_actions, 1)
        self.assertTrue(artifact_dir.exists())

    def test_job_pinned_after_preview_is_skipped(self) -> None:
        old_id = self._successful_job("sweep", b"old")
        self._successful_job("sweep", b"latest")
        artifact_dir = self.artifacts / f"job-{old_id:06d}"
        plan = build_storage_plan(
            self.store,
            self.artifacts,
            RetentionPolicy(keep_latest_per_batch=1),
        )
        self.store.set_pinned(old_id, True)

        result = apply_storage_plan(plan, self.store)

        self.assertEqual(result.completed_actions, 0)
        self.assertEqual(result.skipped_actions, 1)
        self.assertTrue(artifact_dir.exists())

    def test_size_limit_selects_oldest_eligible_artifact(self) -> None:
        oldest_id = self._successful_job(
            "sweep",
            b"123456",
            finished_at="2025-01-01T00:00:00+00:00",
        )
        latest_id = self._successful_job(
            "sweep",
            b"abcdef",
            finished_at="2026-01-01T00:00:00+00:00",
        )

        plan = build_storage_plan(
            self.store,
            self.artifacts,
            RetentionPolicy(max_total_bytes=6),
        )

        self.assertEqual([action.job_id for action in plan.actions], [oldest_id])
        latest = next(entry for entry in plan.entries if entry.job_id == latest_id)
        self.assertIn("latest_successful_reference", latest.protected_reasons)

    def test_missing_latest_result_keeps_the_latest_available_reference(self) -> None:
        available_id = self._successful_job("sweep", b"available")
        missing_id = self._successful_job("sweep", b"missing")
        missing_dir = self.artifacts / f"job-{missing_id:06d}"
        for child in missing_dir.iterdir():
            child.unlink()
        missing_dir.rmdir()

        plan = build_storage_plan(
            self.store,
            self.artifacts,
            RetentionPolicy(keep_latest_per_batch=0),
        )

        available = next(entry for entry in plan.entries if entry.job_id == available_id)
        self.assertIn("latest_successful_reference", available.protected_reasons)
        self.assertNotIn(available_id, {action.job_id for action in plan.actions})

    def test_orphans_require_an_explicit_policy(self) -> None:
        orphan = self.artifacts / "job-999999"
        orphan.mkdir()
        (orphan / "result.json").write_bytes(b"orphan")

        preview = build_storage_plan(
            self.store,
            self.artifacts,
            RetentionPolicy(),
        )
        cleanup = build_storage_plan(
            self.store,
            self.artifacts,
            RetentionPolicy(remove_orphans=True),
        )

        self.assertIsNone(preview.orphans[0].planned_action)
        self.assertEqual(cleanup.orphans[0].planned_action, "delete_orphan")
        apply_storage_plan(cleanup, self.store)
        self.assertFalse(orphan.exists())

    def test_outside_and_shared_artifact_directories_are_never_planned(self) -> None:
        first_id = self._successful_job("sweep")
        second_id = self._successful_job("sweep")
        shared = self.artifacts / f"job-{first_id:06d}"
        outside = self.root / "outside" / "job-123456"
        outside.mkdir(parents=True)
        (outside / "result.json").write_bytes(b"outside")
        connection = sqlite3.connect(self.store.path)
        try:
            connection.execute(
                "UPDATE jobs SET artifact_dir = ? WHERE id = ?",
                (str(shared), second_id),
            )
            connection.commit()
        finally:
            connection.close()
        outside_id = self.store.enqueue_batch("outside", "mock-em", [{"x": 3}])[0]
        self.store.cancel(outside_id)
        connection = sqlite3.connect(self.store.path)
        try:
            connection.execute(
                "UPDATE jobs SET artifact_dir = ? WHERE id = ?",
                (str(outside), outside_id),
            )
            connection.commit()
        finally:
            connection.close()

        plan = build_storage_plan(
            self.store,
            self.artifacts,
            RetentionPolicy(keep_latest_per_batch=0, keep_days=1),
            now=datetime(2026, 9, 10, tzinfo=timezone.utc),
        )

        self.assertFalse(plan.actions)
        entries = {entry.job_id: entry for entry in plan.entries}
        self.assertIn("shared_artifact_directory", entries[first_id].protected_reasons)
        self.assertIn("shared_artifact_directory", entries[second_id].protected_reasons)
        self.assertIn("outside_artifact_root", entries[outside_id].protected_reasons)


if __name__ == "__main__":
    unittest.main()
