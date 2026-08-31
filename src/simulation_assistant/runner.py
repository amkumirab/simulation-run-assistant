from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from simulation_assistant.adapters import (
    ComsolAdapter,
    MockElectromagneticAdapter,
    SimulationAdapter,
    SimulationCancelled,
)
from simulation_assistant.notifications import Notifier, NullNotifier
from simulation_assistant.formulas import evaluate_output_formulas
from simulation_assistant.reporting import write_artifacts
from simulation_assistant.storage import JobStore
from simulation_assistant.types import Job, JobStatus, SimulationResult


@dataclass(frozen=True)
class RunSummary:
    processed: int
    succeeded: int
    failed: int
    cancelled: int = 0


class SimulationRunner:
    def __init__(
        self,
        store: JobStore,
        artifact_root: str | Path,
        adapters: Iterable[SimulationAdapter] | None = None,
        notifier: Notifier | None = None,
    ) -> None:
        available = adapters or [MockElectromagneticAdapter(), ComsolAdapter()]
        self.adapters = {adapter.name: adapter for adapter in available}
        self.store = store
        self.artifact_root = Path(artifact_root)
        self.notifier = notifier or NullNotifier()

    def run_pending(self, limit: int | None = None) -> RunSummary:
        if limit is not None and limit < 1:
            raise ValueError("limit must be greater than zero")

        if self.store.is_queue_paused():
            return RunSummary(processed=0, succeeded=0, failed=0)

        processed = succeeded = failed = cancelled = 0
        while limit is None or processed < limit:
            job = self.store.claim_next()
            if job is None:
                break
            processed += 1
            status = self._run_claimed(job)
            if status == JobStatus.SUCCEEDED:
                succeeded += 1
            elif status == JobStatus.CANCELLED:
                cancelled += 1
            else:
                failed += 1

        return RunSummary(
            processed=processed,
            succeeded=succeeded,
            failed=failed,
            cancelled=cancelled,
        )

    def run_job(self, job_id: int) -> RunSummary:
        """Run one queued job by ID without consuming earlier queue entries."""
        job = self.store.claim(job_id)
        status = self._run_claimed(job)
        return RunSummary(
            processed=1,
            succeeded=int(status == JobStatus.SUCCEEDED),
            failed=int(status == JobStatus.FAILED),
            cancelled=int(status == JobStatus.CANCELLED),
        )

    def _run_claimed(self, job: Job) -> JobStatus:
        try:
            adapter = self.adapters.get(job.adapter)
            if adapter is None:
                available = ", ".join(sorted(self.adapters))
                raise ValueError(
                    f"Unknown adapter '{job.adapter}'. Available: {available}"
                )
            work_dir = self.artifact_root / f"job-{job.id:06d}"
            work_dir.mkdir(parents=True, exist_ok=True)
            self.store.record_artifact_dir(job.id, work_dir)
            run_parameters = inspect.signature(adapter.run).parameters.values()
            supports_cancellation = any(
                parameter.name == "cancel_requested"
                or parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in run_parameters
            )
            if supports_cancellation:
                result = adapter.run(
                    job.parameters,
                    work_dir=work_dir,
                    cancel_requested=lambda: self.store.is_stop_requested(job.id),
                )
            else:
                result = adapter.run(job.parameters, work_dir=work_dir)
            if self.store.is_stop_requested(job.id):
                raise SimulationCancelled("Stop requested by user")
            if job.output_formulas:
                evaluation = evaluate_output_formulas(
                    job.output_formulas, result.metrics
                )
                metadata = dict(result.metadata)
                metadata["output_formulas"] = job.output_formulas
                metadata["formula_errors"] = evaluation.errors
                result = SimulationResult(
                    metrics={**result.metrics, **evaluation.values},
                    series=result.series,
                    metadata=metadata,
                )
            artifact_dir = write_artifacts(self.artifact_root, job, result)
            self.store.mark_succeeded(job.id, result.to_dict(), str(artifact_dir))
            self._notify_safely(
                f"Simulation #{job.id} succeeded\n"
                f"Batch: {job.batch_name}\nAdapter: {job.adapter}"
            )
            return JobStatus.SUCCEEDED
        except SimulationCancelled as exc:
            self.store.mark_cancelled(job.id, str(exc))
            self._notify_safely(
                f"Simulation #{job.id} stopped\n"
                f"Batch: {job.batch_name}\nReason: {exc}"
            )
            return JobStatus.CANCELLED
        except Exception as exc:  # Queue workers must isolate individual failures.
            self.store.mark_failed(job.id, f"{type(exc).__name__}: {exc}")
            self._notify_safely(
                f"Simulation #{job.id} failed\n"
                f"Batch: {job.batch_name}\nError: {type(exc).__name__}: {exc}"
            )
            return JobStatus.FAILED

    def _notify_safely(self, message: str) -> None:
        try:
            self.notifier.send(message)
        except Exception as exc:
            # Notification delivery must never change simulation status.
            print(f"Warning: notification failed: {exc}")
