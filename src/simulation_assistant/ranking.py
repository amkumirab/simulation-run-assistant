from __future__ import annotations

import csv
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from simulation_assistant.sweeps import numeric_parameter_value
from simulation_assistant.types import Job, JobStatus


SUPPORTED_OPERATORS = {"<", "<=", ">", ">="}
SUPPORTED_DIRECTIONS = {"maximize", "minimize"}


@dataclass(frozen=True)
class RankingConstraint:
    source: str
    field: str
    operator: str
    threshold: float

    def __post_init__(self) -> None:
        source = self.source.strip().casefold()
        field = self.field.strip()
        operator = self.operator.strip()
        if source not in {"input", "output"}:
            raise ValueError("Constraint source must be input or output")
        if not field:
            raise ValueError("Constraint field cannot be empty")
        if operator not in SUPPORTED_OPERATORS:
            raise ValueError(f"Unsupported constraint operator: {operator}")
        if (
            isinstance(self.threshold, bool)
            or not isinstance(self.threshold, (int, float))
            or not math.isfinite(float(self.threshold))
        ):
            raise ValueError("Constraint threshold must be finite")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "threshold", float(self.threshold))

    @property
    def key(self) -> str:
        return f"{self.source}:{self.field}"

    @property
    def label(self) -> str:
        return f"{self.source.title()} {self.field} {self.operator} {self.threshold:g}"


@dataclass(frozen=True)
class RankedRun:
    rank: int
    job_id: int
    batch_name: str
    objective: str
    objective_value: float
    parameters: dict[str, Any]
    constraint_values: dict[str, float]
    finished_at: str


@dataclass(frozen=True)
class RankingResult:
    rows: tuple[RankedRun, ...]
    considered_jobs: int
    qualifying_jobs: int
    rejected_jobs: int
    missing_values: int


def rank_sweep_results(
    jobs: Iterable[Job],
    objective: str,
    *,
    direction: str = "maximize",
    constraints: Iterable[RankingConstraint] = (),
    batch_name: str | None = None,
    limit: int | None = None,
) -> RankingResult:
    """Rank successful runs that contain an objective and satisfy every constraint."""
    objective_name = objective.strip()
    if not objective_name:
        raise ValueError("Objective output cannot be empty")
    normalized_direction = direction.strip().casefold()
    if normalized_direction not in SUPPORTED_DIRECTIONS:
        raise ValueError("Ranking direction must be maximize or minimize")
    if limit is not None and limit < 1:
        raise ValueError("Ranking limit must be positive")

    constraint_list = list(constraints)
    rows: list[RankedRun] = []
    considered = 0
    rejected = 0
    missing = 0
    for job in jobs:
        if job.status != JobStatus.SUCCEEDED:
            continue
        if batch_name and job.batch_name != batch_name:
            continue
        considered += 1
        metrics = (job.result or {}).get("metrics", {})
        objective_value = _finite_number(metrics.get(objective_name))
        if objective_value is None:
            missing += 1
            continue

        values: dict[str, float] = {}
        failed = False
        unavailable = False
        for constraint in constraint_list:
            raw_value = (
                job.parameters.get(constraint.field)
                if constraint.source == "input"
                else metrics.get(constraint.field)
            )
            value = numeric_parameter_value(raw_value)
            if value is None:
                unavailable = True
                break
            values[constraint.key] = value
            if not _matches(value, constraint.operator, constraint.threshold):
                failed = True
                break
        if unavailable:
            missing += 1
            continue
        if failed:
            rejected += 1
            continue
        rows.append(
            RankedRun(
                rank=0,
                job_id=job.id,
                batch_name=job.batch_name,
                objective=objective_name,
                objective_value=objective_value,
                parameters=dict(job.parameters),
                constraint_values=values,
                finished_at=job.finished_at or "",
            )
        )

    multiplier = -1 if normalized_direction == "maximize" else 1
    rows.sort(key=lambda row: (multiplier * row.objective_value, row.job_id))
    qualifying = len(rows)
    if limit is not None:
        rows = rows[:limit]
    ranked = tuple(replace(row, rank=index) for index, row in enumerate(rows, 1))
    return RankingResult(
        rows=ranked,
        considered_jobs=considered,
        qualifying_jobs=qualifying,
        rejected_jobs=rejected,
        missing_values=missing,
    )


def write_ranking_csv(path: str | Path, result: RankingResult) -> Path:
    if not result.rows:
        raise ValueError("There are no ranked runs to export")
    parameter_names = sorted(
        {name for row in result.rows for name in row.parameters}
    )
    constraint_names = sorted(
        {name for row in result.rows for name in row.constraint_values}
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "rank",
        "job_id",
        "batch_name",
        "objective",
        "objective_value",
        *[f"input:{name}" for name in parameter_names],
        *[f"constraint:{name}" for name in constraint_names],
        "finished_at",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in result.rows:
            writer.writerow(
                {
                    "rank": row.rank,
                    "job_id": row.job_id,
                    "batch_name": row.batch_name,
                    "objective": row.objective,
                    "objective_value": row.objective_value,
                    **{
                        f"input:{name}": row.parameters.get(name, "")
                        for name in parameter_names
                    },
                    **{
                        f"constraint:{name}": row.constraint_values.get(name, "")
                        for name in constraint_names
                    },
                    "finished_at": row.finished_at,
                }
            )
    return output_path


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _matches(value: float, operator: str, threshold: float) -> bool:
    return {
        "<": value < threshold,
        "<=": value <= threshold,
        ">": value > threshold,
        ">=": value >= threshold,
    }[operator]
