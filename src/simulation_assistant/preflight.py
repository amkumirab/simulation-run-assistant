from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from simulation_assistant.types import Job, JobStatus


@dataclass(frozen=True)
class RunCandidate:
    parameters: dict[str, Any]
    signature: str


@dataclass(frozen=True)
class DuplicateRun:
    candidate: RunCandidate
    job: Job


@dataclass(frozen=True)
class RunPreflightPlan:
    requested: tuple[RunCandidate, ...]
    new: tuple[RunCandidate, ...]
    succeeded: tuple[DuplicateRun, ...]
    scheduled: tuple[DuplicateRun, ...]
    repeated: tuple[RunCandidate, ...]
    run_context: dict[str, Any]

    @property
    def duplicate_count(self) -> int:
        return len(self.succeeded) + len(self.scheduled) + len(self.repeated)

    @property
    def has_duplicates(self) -> bool:
        return self.duplicate_count > 0

    @property
    def successful_job_ids(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(match.job.id for match in self.succeeded))

    @property
    def scheduled_job_ids(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(match.job.id for match in self.scheduled))


def build_comsol_run_context(
    model_path: str | Path,
    *,
    study_tag: str | None,
    job_tag: str | None,
    plot_tags: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a path-free identity for one COMSOL model and output contract."""
    path = Path(model_path)
    stat = path.stat()
    target_kind = "job" if job_tag else "study"
    target_tag = job_tag or study_tag or "default"
    return {
        "model": {
            "name": path.name,
            "size_bytes": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
        },
        "target": {"kind": target_kind, "tag": target_tag},
        "plot_tags": sorted({str(tag) for tag in plot_tags}),
    }


def build_run_signature(
    adapter: str,
    parameters: Mapping[str, Any],
    output_formulas: Mapping[str, str],
    run_context: Mapping[str, Any],
) -> str:
    payload = {
        "version": 1,
        "adapter": adapter,
        "parameters": dict(parameters),
        "output_formulas": dict(output_formulas),
        "run_context": dict(run_context),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_preflight_plan(
    parameter_sets: Iterable[dict[str, Any]],
    *,
    adapter: str,
    output_formulas: Mapping[str, str],
    run_context: Mapping[str, Any],
    existing_jobs: Iterable[Job],
) -> RunPreflightPlan:
    context = dict(run_context)
    candidates = tuple(
        RunCandidate(
            parameters=dict(parameters),
            signature=build_run_signature(
                adapter,
                parameters,
                output_formulas,
                context,
            ),
        )
        for parameters in parameter_sets
    )
    matches: dict[str, list[Job]] = {}
    for job in existing_jobs:
        if job.run_signature:
            matches.setdefault(job.run_signature, []).append(job)
    for jobs in matches.values():
        jobs.sort(key=lambda job: job.id, reverse=True)

    new: list[RunCandidate] = []
    succeeded: list[DuplicateRun] = []
    scheduled: list[DuplicateRun] = []
    repeated: list[RunCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.signature in seen:
            repeated.append(candidate)
            continue
        seen.add(candidate.signature)
        jobs = matches.get(candidate.signature, [])
        active = next(
            (
                job
                for job in jobs
                if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}
            ),
            None,
        )
        if active is not None:
            scheduled.append(DuplicateRun(candidate, active))
            continue
        successful = next(
            (
                job
                for job in jobs
                if job.status == JobStatus.SUCCEEDED and job.result is not None
            ),
            None,
        )
        if successful is not None:
            succeeded.append(DuplicateRun(candidate, successful))
            continue
        new.append(candidate)

    return RunPreflightPlan(
        requested=candidates,
        new=tuple(new),
        succeeded=tuple(succeeded),
        scheduled=tuple(scheduled),
        repeated=tuple(repeated),
        run_context=context,
    )
