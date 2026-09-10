from __future__ import annotations

import os
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from simulation_assistant.storage import JobStore
from simulation_assistant.types import Job, JobStatus


JOB_DIRECTORY = re.compile(r"^job-[0-9]+$")
COMPLETED_STATUSES = {
    JobStatus.SUCCEEDED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


@dataclass(frozen=True)
class RetentionPolicy:
    keep_days: int | None = None
    keep_latest_per_batch: int | None = None
    max_total_bytes: int | None = None
    remove_output_models: bool = False
    remove_orphans: bool = False

    def __post_init__(self) -> None:
        if self.keep_days is not None and self.keep_days < 1:
            raise ValueError("Retention days must be positive")
        if self.keep_latest_per_batch is not None and self.keep_latest_per_batch < 0:
            raise ValueError("Latest runs per batch cannot be negative")
        if self.max_total_bytes is not None and self.max_total_bytes < 0:
            raise ValueError("Maximum storage size cannot be negative")


@dataclass(frozen=True)
class ArtifactEntry:
    job_id: int
    batch_name: str
    status: str
    pinned: bool
    size_bytes: int
    output_model_bytes: int
    missing: bool
    protected_reasons: tuple[str, ...]
    planned_action: str | None


@dataclass(frozen=True)
class OrphanArtifact:
    name: str
    size_bytes: int
    planned_action: str | None


@dataclass(frozen=True)
class StorageAction:
    kind: str
    job_id: int | None
    target: str
    artifact_name: str
    expected_bytes: int
    reason: str


@dataclass(frozen=True)
class StoragePlan:
    artifact_root: str
    total_bytes: int
    reclaimable_bytes: int
    entries: tuple[ArtifactEntry, ...]
    orphans: tuple[OrphanArtifact, ...]
    actions: tuple[StorageAction, ...]
    missing_job_ids: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CleanupResult:
    completed_actions: int
    skipped_actions: int
    reclaimed_bytes: int
    messages: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_storage_plan(
    store: JobStore,
    artifact_root: str | Path,
    policy: RetentionPolicy,
    *,
    protected_job_ids: Iterable[int] = (),
    now: datetime | None = None,
) -> StoragePlan:
    root = Path(artifact_root).resolve()
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    jobs = store.list(limit=100_000)
    explicit_protected = {int(value) for value in protected_job_ids}
    latest_ids = _latest_job_ids(jobs, policy.keep_latest_per_batch)
    paths: dict[int, Path] = {}
    sizes: dict[int, int] = {}
    output_sizes: dict[int, int] = {}
    missing_ids: list[int] = []
    protected: dict[int, list[str]] = {}

    for job in jobs:
        reasons: list[str] = []
        if job.status not in COMPLETED_STATUSES:
            reasons.append("active_or_queued")
        if job.pinned:
            reasons.append("pinned")
        if job.id in explicit_protected:
            reasons.append("selected_best_result")
        if job.id in latest_ids:
            reasons.append("latest_per_batch")
        protected[job.id] = reasons
        if not job.artifact_dir:
            continue
        path = Path(job.artifact_dir).resolve()
        paths[job.id] = path
        if not _is_job_directory(path, root):
            reasons.append("outside_artifact_root")
            continue
        if not path.exists():
            missing_ids.append(job.id)
            continue
        sizes[job.id] = _tree_size(path)
        output = path / "output.mph"
        output_sizes[job.id] = _tree_size(output) if output.is_file() else 0

    path_owners: dict[Path, list[int]] = {}
    for job_id, path in paths.items():
        if _is_job_directory(path, root):
            path_owners.setdefault(path, []).append(job_id)
    for owner_ids in path_owners.values():
        if len(owner_ids) > 1:
            for job_id in owner_ids:
                protected[job_id].append("shared_artifact_directory")
    reference_ids = _latest_successful_ids(
        [job for job in jobs if job.id in sizes]
    )
    for job_id in reference_ids:
        protected[job_id].append("latest_successful_reference")

    referenced = {
        path.name
        for path in paths.values()
        if _is_job_directory(path, root)
    }
    orphan_items: list[OrphanArtifact] = []
    if root.is_dir():
        for child in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
            if (
                child.name in referenced
                or not JOB_DIRECTORY.fullmatch(child.name)
                or not child.is_dir()
            ):
                continue
            size = _tree_size(child)
            action = "delete_orphan" if policy.remove_orphans else None
            orphan_items.append(OrphanArtifact(child.name, size, action))

    candidates: dict[int, str] = {}
    cutoff = (
        current_time - timedelta(days=policy.keep_days)
        if policy.keep_days is not None
        else None
    )
    for job in jobs:
        if job.id not in sizes or protected[job.id]:
            continue
        finished = _timestamp(job.finished_at or job.created_at)
        if cutoff is not None and finished < cutoff:
            candidates[job.id] = f"older_than_{policy.keep_days}_days"
        if policy.keep_latest_per_batch is not None and job.id not in latest_ids:
            candidates.setdefault(job.id, "outside_latest_batch_runs")

    unique_job_sizes = {
        paths[job_id]: size for job_id, size in sizes.items()
    }
    total_bytes = sum(unique_job_sizes.values()) + sum(
        item.size_bytes for item in orphan_items
    )
    projected_bytes = total_bytes - sum(
        sizes[job_id] for job_id in candidates
    )
    if policy.remove_orphans:
        projected_bytes -= sum(item.size_bytes for item in orphan_items)
    if policy.max_total_bytes is not None and projected_bytes > policy.max_total_bytes:
        oldest = sorted(
            (
                job
                for job in jobs
                if job.id in sizes
                and not protected[job.id]
                and job.id not in candidates
            ),
            key=lambda job: (_timestamp(job.finished_at or job.created_at), job.id),
        )
        for job in oldest:
            candidates[job.id] = "storage_limit"
            projected_bytes -= sizes[job.id]
            if projected_bytes <= policy.max_total_bytes:
                break

    actions: list[StorageAction] = []
    for job in jobs:
        path = paths.get(job.id)
        if path is None or job.id not in sizes:
            continue
        if job.id in candidates:
            actions.append(
                StorageAction(
                    "delete_directory",
                    job.id,
                    str(path),
                    path.name,
                    sizes[job.id],
                    candidates[job.id],
                )
            )
        elif policy.remove_output_models and not protected[job.id] and output_sizes[job.id]:
            output = path / "output.mph"
            actions.append(
                StorageAction(
                    "delete_output_model",
                    job.id,
                    str(output),
                    f"{path.name}/output.mph",
                    output_sizes[job.id],
                    "output_model_retention",
                )
            )

    for orphan in orphan_items:
        if orphan.planned_action:
            child = root / orphan.name
            actions.append(
                StorageAction(
                    orphan.planned_action,
                    None,
                    str(child.resolve()),
                    orphan.name,
                    orphan.size_bytes,
                    "unreferenced_job_directory",
                )
            )

    action_by_job = {
        action.job_id: action.kind for action in actions if action.job_id is not None
    }
    entries = tuple(
        ArtifactEntry(
            job_id=job.id,
            batch_name=job.batch_name,
            status=job.status.value,
            pinned=job.pinned,
            size_bytes=sizes.get(job.id, 0),
            output_model_bytes=output_sizes.get(job.id, 0),
            missing=job.id in missing_ids,
            protected_reasons=tuple(protected[job.id]),
            planned_action=action_by_job.get(job.id),
        )
        for job in jobs
        if job.artifact_dir
    )
    return StoragePlan(
        artifact_root=str(root),
        total_bytes=total_bytes,
        reclaimable_bytes=sum(action.expected_bytes for action in actions),
        entries=entries,
        orphans=tuple(orphan_items),
        actions=tuple(actions),
        missing_job_ids=tuple(sorted(missing_ids)),
    )


def apply_storage_plan(plan: StoragePlan, store: JobStore) -> CleanupResult:
    root = Path(plan.artifact_root).resolve()
    completed = 0
    skipped = 0
    reclaimed = 0
    messages: list[str] = []
    for action in plan.actions:
        target = Path(action.target).resolve()
        if not _valid_action_target(action, target, root):
            skipped += 1
            messages.append(f"Skipped unsafe target: {action.artifact_name}")
            continue
        if action.job_id is not None:
            try:
                current_job = store.get(action.job_id)
            except KeyError:
                skipped += 1
                messages.append(f"Skipped missing Job #{action.job_id}")
                continue
            if current_job.pinned or current_job.status not in COMPLETED_STATUSES:
                skipped += 1
                messages.append(f"Skipped protected Job #{action.job_id}")
                continue
            if action.kind == "delete_directory":
                current_path = (
                    Path(current_job.artifact_dir).resolve()
                    if current_job.artifact_dir
                    else None
                )
                if current_path != target:
                    skipped += 1
                    messages.append(f"Skipped changed path for Job #{action.job_id}")
                    continue
            elif action.kind == "delete_output_model":
                current_path = (
                    Path(current_job.artifact_dir).resolve()
                    if current_job.artifact_dir
                    else None
                )
                if current_path != target.parent:
                    skipped += 1
                    messages.append(f"Skipped changed path for Job #{action.job_id}")
                    continue
        if not target.exists():
            skipped += 1
            messages.append(f"Skipped missing artifact: {action.artifact_name}")
            continue
        current_size = _tree_size(target)
        if current_size != action.expected_bytes:
            skipped += 1
            messages.append(f"Skipped changed artifact: {action.artifact_name}")
            continue
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        except OSError as exc:
            skipped += 1
            messages.append(
                f"Could not remove {action.artifact_name}: {exc.strerror or exc}"
            )
            continue
        if action.kind == "delete_directory" and action.job_id is not None:
            store.clear_artifact_dir(action.job_id)
        store.record_retention_event(
            action=action.kind,
            job_id=action.job_id,
            artifact_name=action.artifact_name,
            bytes_reclaimed=current_size,
            details={"reason": action.reason},
        )
        completed += 1
        reclaimed += current_size
    return CleanupResult(completed, skipped, reclaimed, tuple(messages))


def _latest_job_ids(jobs: list[Job], count: int | None) -> set[int]:
    if count is None or count == 0:
        return set()
    grouped: dict[str, list[Job]] = {}
    for job in jobs:
        grouped.setdefault(job.batch_name, []).append(job)
    return {
        job.id
        for batch_jobs in grouped.values()
        for job in sorted(batch_jobs, key=lambda item: item.id, reverse=True)[:count]
    }


def _latest_successful_ids(jobs: list[Job]) -> set[int]:
    references: dict[str, int] = {}
    for job in sorted(jobs, key=lambda item: item.id, reverse=True):
        validation = (job.result or {}).get("metadata", {}).get(
            "scientific_validation", {}
        )
        rejected = isinstance(validation, dict) and validation.get("status") == "rejected"
        if (
            job.status == JobStatus.SUCCEEDED
            and not rejected
            and job.batch_name not in references
        ):
            references[job.batch_name] = job.id
    return set(references.values())


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_job_directory(path: Path, root: Path) -> bool:
    return path != root and path.parent == root and JOB_DIRECTORY.fullmatch(path.name) is not None


def _valid_action_target(action: StorageAction, target: Path, root: Path) -> bool:
    if action.kind in {"delete_directory", "delete_orphan"}:
        return _is_job_directory(target, root)
    if action.kind == "delete_output_model":
        return (
            target.name == "output.mph"
            and _is_job_directory(target.parent, root)
        )
    return False


def _tree_size(path: Path) -> int:
    if path.is_file() or path.is_symlink():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        entries = list(os.scandir(path))
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_dir(follow_symlinks=False):
                total += _tree_size(Path(entry.path))
            else:
                total += entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    return total
