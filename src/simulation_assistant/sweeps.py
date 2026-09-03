from __future__ import annotations

import csv
import itertools
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from simulation_assistant.quantities import numeric_quantity_value
from simulation_assistant.types import Job, JobStatus


DEFAULT_MAX_SWEEP_JOBS = 500

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_RANGE_PATTERN = re.compile(
    rf"^\s*({_NUMBER})\s*:\s*({_NUMBER})\s*:\s*({_NUMBER})\s*(\[[^\[\]]+\])?\s*$"
)


def parse_sweep_values(specification: str) -> list[str]:
    """Parse a comma-separated list or an inclusive start:stop:step range."""
    text = specification.strip()
    if not text:
        raise ValueError("Sweep values cannot be empty")

    range_match = _RANGE_PATTERN.fullmatch(text)
    if range_match:
        return _expand_range(*range_match.groups())

    values = [value.strip() for value in text.split(",")]
    if any(not value for value in values):
        raise ValueError("Sweep lists cannot contain empty values")
    if len(values) < 2:
        raise ValueError(
            "A sweep needs at least two comma-separated values or a start:stop:step range"
        )
    unique_values = list(dict.fromkeys(values))
    if len(unique_values) < 2:
        raise ValueError("A sweep needs at least two distinct values")
    return unique_values


def _expand_range(start_text: str, stop_text: str, step_text: str, unit: str | None) -> list[str]:
    try:
        start = Decimal(start_text)
        stop = Decimal(stop_text)
        step = Decimal(step_text)
    except InvalidOperation as exc:
        raise ValueError("Sweep range contains an invalid number") from exc
    if step == 0:
        raise ValueError("Sweep range step cannot be zero")
    if start < stop and step < 0:
        raise ValueError("Sweep range step must be positive for an ascending range")
    if start > stop and step > 0:
        raise ValueError("Sweep range step must be negative for a descending range")

    values: list[str] = []
    current = start
    in_bounds = (lambda value: value <= stop) if step > 0 else (lambda value: value >= stop)
    while in_bounds(current):
        if len(values) >= DEFAULT_MAX_SWEEP_JOBS:
            raise ValueError(
                f"A single range cannot contain more than {DEFAULT_MAX_SWEEP_JOBS} values"
            )
        values.append(f"{_format_decimal(current)}{unit or ''}")
        current += step
    if len(values) < 2:
        raise ValueError("A sweep range must produce at least two values")
    return values


def _format_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def build_parameter_sets(
    fixed: Mapping[str, Any],
    sweep: Mapping[str, Iterable[Any]],
    *,
    max_jobs: int = DEFAULT_MAX_SWEEP_JOBS,
) -> list[dict[str, Any]]:
    """Build a deterministic Cartesian product for desktop sweep submission."""
    overlap = set(fixed).intersection(sweep)
    if overlap:
        names = ", ".join(sorted(overlap))
        raise ValueError(f"Parameters cannot be both fixed and swept: {names}")
    if max_jobs < 1:
        raise ValueError("Sweep job limit must be positive")

    keys = list(sweep)
    candidate_lists = [list(sweep[name]) for name in keys]
    for name, candidates in zip(keys, candidate_lists):
        if not candidates:
            raise ValueError(f"Sweep parameter '{name}' has no values")

    count = 1
    for candidates in candidate_lists:
        count *= len(candidates)
        if count > max_jobs:
            raise ValueError(f"Sweep expands to {count} jobs; the limit is {max_jobs}")

    if not keys:
        return [dict(fixed)]

    parameter_sets: list[dict[str, Any]] = []
    for combination in itertools.product(*candidate_lists):
        parameters = dict(fixed)
        parameters.update(dict(zip(keys, combination)))
        parameter_sets.append(parameters)
    return parameter_sets


def estimate_sequential_seconds(job_count: int, completed_jobs: Iterable[Job]) -> float | None:
    """Estimate a sequential batch from recent COMSOL wall-clock durations."""
    durations: list[float] = []
    for job in completed_jobs:
        if job.status != JobStatus.SUCCEEDED or job.adapter != "comsol":
            continue
        value = (job.result or {}).get("metrics", {}).get("comsol_duration_seconds")
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and value > 0
        ):
            durations.append(float(value))
        if len(durations) >= 20:
            break
    if not durations:
        return None
    return job_count * (sum(durations) / len(durations))


def numeric_parameter_value(value: Any) -> float | None:
    """Return a finite scalar normalized to SI when it has a supported unit."""
    return numeric_quantity_value(value)


def comparison_rows(
    jobs: Iterable[Job],
    metric: str,
    *,
    batch_name: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in jobs:
        if job.status != JobStatus.SUCCEEDED:
            continue
        if batch_name and job.batch_name != batch_name:
            continue
        metrics = (job.result or {}).get("metrics", {})
        value = metrics.get(metric)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            continue
        rows.append(
            {
                "job_id": job.id,
                "batch_name": job.batch_name,
                "parameters": job.parameters,
                "metric": metric,
                "value": float(value),
                "finished_at": job.finished_at or "",
            }
        )
    return rows


def write_comparison_csv(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> Path:
    records = list(rows)
    if not records:
        raise ValueError("There are no comparison rows to export")
    parameter_names = sorted(
        {
            str(name)
            for row in records
            for name in dict(row.get("parameters", {}))
        }
    )
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "job_id",
        "batch_name",
        *parameter_names,
        "metric",
        "value",
        "finished_at",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            parameters = dict(row.get("parameters", {}))
            writer.writerow(
                {
                    "job_id": row.get("job_id", ""),
                    "batch_name": row.get("batch_name", ""),
                    **{name: parameters.get(name, "") for name in parameter_names},
                    "metric": row.get("metric", ""),
                    "value": row.get("value", ""),
                    "finished_at": row.get("finished_at", ""),
                }
            )
    return output_path
