from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class SimulationResult:
    """Normalized output returned by every simulation adapter."""

    metrics: dict[str, float]
    series: list[dict[str, float]]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Job:
    id: int
    batch_name: str
    adapter: str
    status: JobStatus
    parameters: dict[str, Any]
    output_formulas: dict[str, str]
    result: dict[str, Any] | None
    error: str | None
    artifact_dir: str | None
    attempts: int
    created_at: str
    started_at: str | None
    finished_at: str | None
    run_signature: str | None = None
    run_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data
