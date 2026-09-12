from __future__ import annotations

import csv
import html
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from simulation_assistant.quantities import parse_quantity
from simulation_assistant.ranking import RankingConstraint
from simulation_assistant.types import Job, JobStatus


@dataclass(frozen=True)
class ParetoObjective:
    metric: str
    direction: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        metric = self.metric.strip()
        direction = self.direction.strip().casefold()
        if not metric:
            raise ValueError("Pareto objective metric cannot be empty")
        if direction not in {"maximize", "minimize"}:
            raise ValueError("Pareto objective direction must be maximize or minimize")
        if (
            isinstance(self.weight, bool)
            or not isinstance(self.weight, (int, float))
            or not math.isfinite(float(self.weight))
            or self.weight <= 0
        ):
            raise ValueError("Pareto objective weight must be positive and finite")
        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "weight", float(self.weight))


@dataclass(frozen=True)
class ParetoRun:
    front: int
    compromise_score: float
    job_id: int
    batch_name: str
    objective_values: dict[str, float]
    normalized_values: dict[str, float]
    dominated_by: tuple[int, ...]
    parameters: dict[str, Any]
    constraint_values: dict[str, float]
    validation_status: str
    finished_at: str


@dataclass(frozen=True)
class ParetoResult:
    rows: tuple[ParetoRun, ...]
    objectives: tuple[ParetoObjective, ...]
    constraints: tuple[RankingConstraint, ...]
    considered_jobs: int
    eligible_jobs: int
    constraint_rejected_jobs: int
    validation_rejected_jobs: int
    unvalidated_jobs: int
    missing_values: int

    @property
    def pareto_front(self) -> tuple[ParetoRun, ...]:
        return tuple(row for row in self.rows if row.front == 1)


@dataclass(frozen=True)
class _Candidate:
    job: Job
    objective_values: dict[str, float]
    constraint_values: dict[str, float]
    validation_status: str


def analyze_pareto(
    jobs: Iterable[Job],
    objectives: Iterable[ParetoObjective],
    *,
    constraints: Iterable[RankingConstraint] = (),
    batch_name: str | None = None,
) -> ParetoResult:
    objective_list = tuple(objectives)
    if len(objective_list) < 2:
        raise ValueError("Pareto analysis requires at least two objectives")
    if len(objective_list) > 6:
        raise ValueError("Pareto analysis supports at most six objectives")
    objective_names = [objective.metric for objective in objective_list]
    if len(set(objective_names)) != len(objective_names):
        raise ValueError("Pareto objective metrics must be unique")
    constraint_list = tuple(constraints)

    considered = 0
    constrained_out = 0
    validation_rejected = 0
    unvalidated = 0
    missing = 0
    candidates: list[_Candidate] = []
    for job in jobs:
        if job.status != JobStatus.SUCCEEDED:
            continue
        if batch_name and job.batch_name != batch_name:
            continue
        considered += 1
        result = job.result if isinstance(job.result, dict) else {}
        metadata = result.get("metadata", {})
        validation = (
            metadata.get("scientific_validation", {})
            if isinstance(metadata, dict)
            else {}
        )
        validation_status = (
            str(validation.get("status", "not_recorded"))
            if isinstance(validation, dict)
            else "not_recorded"
        )
        if validation_status == "rejected":
            validation_rejected += 1
            continue
        if validation_status not in {"valid", "warning"}:
            unvalidated += 1
            continue
        metrics = result.get("metrics", {})
        if not isinstance(metrics, dict):
            missing += 1
            continue
        values = {
            name: _finite_number(metrics.get(name)) for name in objective_names
        }
        if any(value is None for value in values.values()):
            missing += 1
            continue

        constraint_values: dict[str, float] = {}
        unavailable = False
        failed = False
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
            constraint_values[constraint.key] = quantity.si_value
            if not _matches(
                quantity.si_value,
                constraint.operator,
                constraint.threshold,
            ):
                failed = True
                break
        if unavailable:
            missing += 1
            continue
        if failed:
            constrained_out += 1
            continue
        candidates.append(
            _Candidate(
                job=job,
                objective_values={
                    name: float(value) for name, value in values.items()
                },
                constraint_values=constraint_values,
                validation_status=validation_status,
            )
        )

    fronts, dominators = _pareto_fronts(candidates, objective_list)
    normalized = _normalize_candidates(candidates, objective_list)
    weight_total = sum(objective.weight for objective in objective_list)
    rows = [
        ParetoRun(
            front=fronts[index],
            compromise_score=sum(
                normalized[index][objective.metric] * objective.weight
                for objective in objective_list
            )
            / weight_total,
            job_id=candidate.job.id,
            batch_name=candidate.job.batch_name,
            objective_values=dict(candidate.objective_values),
            normalized_values=normalized[index],
            dominated_by=tuple(
                sorted(candidates[item].job.id for item in dominators[index])
            ),
            parameters=dict(candidate.job.parameters),
            constraint_values=dict(candidate.constraint_values),
            validation_status=candidate.validation_status,
            finished_at=candidate.job.finished_at or "",
        )
        for index, candidate in enumerate(candidates)
    ]
    rows.sort(key=lambda row: (row.front, -row.compromise_score, row.job_id))
    return ParetoResult(
        rows=tuple(rows),
        objectives=objective_list,
        constraints=constraint_list,
        considered_jobs=considered,
        eligible_jobs=len(candidates),
        constraint_rejected_jobs=constrained_out,
        validation_rejected_jobs=validation_rejected,
        unvalidated_jobs=unvalidated,
        missing_values=missing,
    )


def write_pareto_csv(path: str | Path, result: ParetoResult) -> Path:
    if not result.rows:
        raise ValueError("There are no Pareto rows to export")
    destination = _report_path(path, ".csv")
    parameter_names = sorted(
        {str(name) for row in result.rows for name in row.parameters}
    )
    constraint_names = sorted(
        {str(name) for row in result.rows for name in row.constraint_values}
    )
    objective_names = [objective.metric for objective in result.objectives]
    fieldnames = [
        "front",
        "compromise_score",
        "job_id",
        "batch_name",
        "scientific_validation",
        "dominated_by",
        *(f"objective:{name}" for name in objective_names),
        *(f"normalized:{name}" for name in objective_names),
        *(f"input:{name}" for name in parameter_names),
        *(f"constraint:{name}" for name in constraint_names),
        "finished_at",
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in result.rows:
            writer.writerow(
                {
                    "front": row.front,
                    "compromise_score": row.compromise_score,
                    "job_id": row.job_id,
                    "batch_name": row.batch_name,
                    "scientific_validation": row.validation_status,
                    "dominated_by": ";".join(str(value) for value in row.dominated_by),
                    **{
                        f"objective:{name}": row.objective_values[name]
                        for name in objective_names
                    },
                    **{
                        f"normalized:{name}": row.normalized_values[name]
                        for name in objective_names
                    },
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
    return destination.resolve()


def write_pareto_html(path: str | Path, result: ParetoResult) -> Path:
    if not result.rows:
        raise ValueError("There are no Pareto rows to export")
    destination = _report_path(path, ".html")
    objective_names = [objective.metric for objective in result.objectives]
    headings = [
        "Front",
        "Score",
        "Job",
        *objective_names,
        "Dominated by",
        "Input state",
    ]
    rows: list[str] = []
    for row in result.rows:
        values: list[Any] = [
            row.front,
            f"{row.compromise_score:.6f}",
            f"#{row.job_id}",
            *(row.objective_values[name] for name in objective_names),
            ", ".join(f"#{job_id}" for job_id in row.dominated_by),
            ", ".join(f"{name}={value}" for name, value in row.parameters.items()),
        ]
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in values)
        rows.append(f'<tr data-front="{row.front}">{cells}</tr>')
    objective_text = " · ".join(
        f"{html.escape(item.metric)} ({item.direction}, weight {item.weight:g})"
        for item in result.objectives
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pareto Analysis</title>
  <style>
    body {{ font: 14px system-ui, sans-serif; margin: 32px; color: #172630; }}
    p {{ color: #667681; }}
    .summary {{ display: flex; gap: 12px; margin: 18px 0; flex-wrap: wrap; }}
    .summary span {{ background: #f3f6f8; padding: 10px 14px; border-radius: 8px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #dce4e8; padding: 8px; text-align: left; }}
    th {{ background: #16324a; color: white; }}
    tr[data-front="1"] {{ background: #e5f6f3; }}
  </style>
</head>
<body>
  <h1>Pareto Analysis</h1>
  <p>{objective_text}</p>
  <div class="summary">
    <span>{result.eligible_jobs} eligible runs</span>
    <span>{len(result.pareto_front)} Pareto-optimal runs</span>
    <span>{result.validation_rejected_jobs} validation rejected</span>
    <span>{result.unvalidated_jobs} unvalidated</span>
    <span>{result.missing_values} missing values</span>
  </div>
  <table>
    <thead><tr>{''.join(f'<th>{html.escape(name)}</th>' for name in headings)}</tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination.resolve()


def _pareto_fronts(
    candidates: list[_Candidate],
    objectives: tuple[ParetoObjective, ...],
) -> tuple[list[int], list[set[int]]]:
    dominators = [set() for _ in candidates]
    dominated = [set() for _ in candidates]
    for left in range(len(candidates)):
        for right in range(left + 1, len(candidates)):
            if _dominates(candidates[left], candidates[right], objectives):
                dominated[left].add(right)
                dominators[right].add(left)
            elif _dominates(candidates[right], candidates[left], objectives):
                dominated[right].add(left)
                dominators[left].add(right)
    remaining = [set(values) for values in dominators]
    fronts = [0 for _ in candidates]
    current = [index for index, values in enumerate(remaining) if not values]
    front_number = 1
    while current:
        next_front: list[int] = []
        for index in current:
            fronts[index] = front_number
            for other in dominated[index]:
                remaining[other].discard(index)
                if not remaining[other] and fronts[other] == 0:
                    next_front.append(other)
        current = sorted(set(next_front))
        front_number += 1
    return fronts, dominators


def _dominates(
    left: _Candidate,
    right: _Candidate,
    objectives: tuple[ParetoObjective, ...],
) -> bool:
    no_worse = True
    strictly_better = False
    for objective in objectives:
        left_value = left.objective_values[objective.metric]
        right_value = right.objective_values[objective.metric]
        if objective.direction == "maximize":
            no_worse = no_worse and left_value >= right_value
            strictly_better = strictly_better or left_value > right_value
        else:
            no_worse = no_worse and left_value <= right_value
            strictly_better = strictly_better or left_value < right_value
    return no_worse and strictly_better


def _normalize_candidates(
    candidates: list[_Candidate],
    objectives: tuple[ParetoObjective, ...],
) -> list[dict[str, float]]:
    normalized = [dict() for _ in candidates]
    for objective in objectives:
        values = [item.objective_values[objective.metric] for item in candidates]
        if not values:
            continue
        minimum = min(values)
        maximum = max(values)
        span = maximum - minimum
        for index, value in enumerate(values):
            if span == 0:
                score = 1.0
            elif objective.direction == "maximize":
                score = (value - minimum) / span
            else:
                score = (maximum - value) / span
            normalized[index][objective.metric] = score
    return normalized


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


def _report_path(path: str | Path, suffix: str) -> Path:
    destination = Path(path)
    if destination.suffix.casefold() != suffix:
        raise ValueError(f"Pareto report must use the {suffix} extension")
    return destination
