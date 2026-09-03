from __future__ import annotations

import csv
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from simulation_assistant.quantities import parse_quantity, reference_unit
from simulation_assistant.types import Job, JobStatus


SUPPORTED_OPERATORS = {"<", "<=", ">", ">="}
SUPPORTED_DIRECTIONS = {"maximize", "minimize"}


@dataclass(frozen=True)
class RankingConstraint:
    source: str
    field: str
    operator: str
    threshold: float
    dimension: str | None = None

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
        if self.dimension is not None and reference_unit(self.dimension) is None:
            raise ValueError(f"Unsupported constraint dimension: {self.dimension}")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "threshold", float(self.threshold))

    @classmethod
    def from_value(
        cls,
        source: str,
        field: str,
        operator: str,
        threshold: Any,
    ) -> RankingConstraint:
        quantity = parse_quantity(threshold)
        if quantity is None:
            raise ValueError("Constraint threshold must use a supported finite quantity")
        return cls(
            source=source,
            field=field,
            operator=operator,
            threshold=quantity.si_value,
            dimension=quantity.dimension,
        )

    @property
    def key(self) -> str:
        return f"{self.source}:{self.field}"

    @property
    def label(self) -> str:
        unit = reference_unit(self.dimension)
        suffix = f" {unit}" if unit else ""
        return (
            f"{self.source.title()} {self.field} {self.operator} "
            f"{self.threshold:g}{suffix}"
        )


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
    constraints: tuple[RankingConstraint, ...]
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
            quantity = parse_quantity(raw_value)
            if quantity is None or quantity.dimension != constraint.dimension:
                unavailable = True
                break
            value = quantity.si_value
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
        constraints=tuple(constraint_list),
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
    constraints = {constraint.key: constraint for constraint in result.constraints}
    constraint_names = sorted(
        {name for row in result.rows for name in row.constraint_values}
    )
    constraint_headers = {
        name: _constraint_csv_header(name, constraints.get(name))
        for name in constraint_names
    }
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "rank",
        "job_id",
        "batch_name",
        "objective",
        "objective_value",
        *[f"input:{name}" for name in parameter_names],
        *[constraint_headers[name] for name in constraint_names],
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
                        constraint_headers[name]: row.constraint_values.get(name, "")
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


def _constraint_csv_header(
    key: str,
    constraint: RankingConstraint | None,
) -> str:
    unit = reference_unit(constraint.dimension) if constraint else None
    suffix = f"[{unit}]" if unit else ""
    return f"constraint:{key}{suffix}"
