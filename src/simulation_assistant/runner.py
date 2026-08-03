from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from simulation_assistant.adapters import (
    ComsolAdapter,
    MockElectromagneticAdapter,
    SimulationAdapter,
)
from simulation_assistant.notifications import Notifier, NullNotifier
from simulation_assistant.reporting import write_artifacts
from simulation_assistant.storage import JobStore


@dataclass(frozen=True)
class RunSummary:
    processed: int
    succeeded: int
    failed: int


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

        processed = succeeded = failed = 0
        while limit is None or processed < limit:
            job = self.store.claim_next()
            if job is None:
                break
            processed += 1

            try:
                adapter = self.adapters.get(job.adapter)
                if adapter is None:
                    available = ", ".join(sorted(self.adapters))
                    raise ValueError(
                        f"Unknown adapter '{job.adapter}'. Available: {available}"
                    )
                work_dir = self.artifact_root / f"job-{job.id:06d}"
                result = adapter.run(job.parameters, work_dir=work_dir)
                artifact_dir = write_artifacts(self.artifact_root, job, result)
                self.store.mark_succeeded(job.id, result.to_dict(), str(artifact_dir))
                succeeded += 1
                self._notify_safely(
                    f"Simulation #{job.id} succeeded\n"
                    f"Batch: {job.batch_name}\nAdapter: {job.adapter}"
                )
            except Exception as exc:  # Queue workers must isolate individual failures.
                self.store.mark_failed(job.id, f"{type(exc).__name__}: {exc}")
                failed += 1
                self._notify_safely(
                    f"Simulation #{job.id} failed\n"
                    f"Batch: {job.batch_name}\nError: {type(exc).__name__}: {exc}"
                )

        return RunSummary(processed=processed, succeeded=succeeded, failed=failed)

    def _notify_safely(self, message: str) -> None:
        try:
            self.notifier.send(message)
        except Exception as exc:
            # Notification delivery must never change simulation status.
            print(f"Warning: notification failed: {exc}")
