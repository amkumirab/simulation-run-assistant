from __future__ import annotations

import csv
import html
import itertools
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from simulation_assistant.quantities import parse_quantity
from simulation_assistant.types import Job, JobStatus


SUPPORTED_ROBUST_MODES = {"worst_case", "average", "balanced"}


@dataclass(frozen=True)
class RobustObjective:
    metric: str
    direction: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        metric = self.metric.strip()
        direction = self.direction.strip().casefold()
        if not metric:
            raise ValueError("Robust objective metric cannot be empty")
        if direction not in {"maximize", "minimize"}:
            raise ValueError("Robust objective direction must be maximize or minimize")
        if (
            isinstance(self.weight, bool)
            or not isinstance(self.weight, (int, float))
            or not math.isfinite(float(self.weight))
            or self.weight <= 0
        ):
            raise ValueError("Robust objective weight must be positive and finite")
        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "weight", float(self.weight))


@dataclass(frozen=True)
class RobustMetricSummary:
    worst: float
    mean: float
    best: float
    aligned: float | None
    worst_case_change_percent: float | None


@dataclass(frozen=True)
class RobustState:
    job_id: int
    condition: dict[str, Any]
    metrics: dict[str, float]
    validation_status: str


@dataclass(frozen=True)
class RobustDesign:
    rank: int | None
    pareto_front: int | None
    score: float | None
    design_key: str
    design_parameters: dict[str, Any]
    job_ids: tuple[int, ...]
    states: tuple[RobustState, ...]
    expected_states: int
    covered_states: int
    coverage_percent: float
    complete: bool
    eligible: bool
    exclusion_reason: str | None
    rejected_states: int
    unvalidated_states: int
    unavailable_states: int
    metric_summaries: dict[str, RobustMetricSummary]


@dataclass(frozen=True)
class RobustResult:
    groups: tuple[RobustDesign, ...]
    objectives: tuple[RobustObjective, ...]
    condition_fields: tuple[str, ...]
    expected_conditions: tuple[dict[str, Any], ...]
    ranking_mode: str
    considered_jobs: int

    @property
    def ranked_groups(self) -> tuple[RobustDesign, ...]:
        return tuple(group for group in self.groups if group.rank is not None)


def analyze_robust_designs(
    jobs: Iterable[Job],
    objectives: Iterable[RobustObjective],
    *,
    condition_fields: Sequence[str] = ("xoff", "yoff", "tilt"),
    expected_conditions: Iterable[Mapping[str, Any]] | None = None,
    batch_name: str | None = None,
    ranking_mode: str = "balanced",
) -> RobustResult:
    objective_list = tuple(objectives)
    if not objective_list:
        raise ValueError("Robust analysis requires at least one objective")
    if len(objective_list) > 6:
        raise ValueError("Robust analysis supports at most six objectives")
    names = [objective.metric for objective in objective_list]
    if len(names) != len(set(names)):
        raise ValueError("Robust objective metrics must be unique")
    fields = tuple(field.strip() for field in condition_fields if field.strip())
    if not fields or len(fields) != len(set(fields)):
        raise ValueError("Condition fields must be non-empty and unique")
    mode = ranking_mode.strip().casefold()
    if mode not in SUPPORTED_ROBUST_MODES:
        raise ValueError("Ranking mode must be worst_case, average, or balanced")

    selected = [
        job
        for job in jobs
        if (not batch_name or job.batch_name == batch_name)
        and all(field in job.parameters for field in fields)
    ]
    if expected_conditions is None:
        expected = _infer_expected_conditions(selected, fields)
    else:
        expected = tuple(_condition(values, fields) for values in expected_conditions)
        if len({_mapping_key(item) for item in expected}) != len(expected):
            raise ValueError("Expected conditions must be unique")
    if not expected:
        raise ValueError("No misalignment conditions are available")

    expected_keys = {_mapping_key(item) for item in expected}
    grouped: dict[str, tuple[dict[str, Any], dict[str, Job]]] = {}
    for job in selected:
        condition = _condition(job.parameters, fields)
        condition_key = _mapping_key(condition)
        if condition_key not in expected_keys:
            continue
        design = {
            name: value
            for name, value in job.parameters.items()
            if name not in fields
        }
        design_key = _mapping_key(design)
        _, states = grouped.setdefault(design_key, (design, {}))
        previous = states.get(condition_key)
        if previous is None or job.id > previous.id:
            states[condition_key] = job

    groups = [
        _summarize_group(key, design, states, expected, objective_list)
        for key, (design, states) in grouped.items()
    ]
    eligible_indexes = [index for index, group in enumerate(groups) if group.eligible]
    scores = _robust_scores(groups, eligible_indexes, objective_list, mode)
    fronts = _robust_fronts(groups, eligible_indexes, objective_list)
    ranked_indexes = sorted(
        eligible_indexes,
        key=lambda index: (-scores[index], fronts[index], groups[index].design_key),
    )
    ranks = {index: rank for rank, index in enumerate(ranked_indexes, 1)}
    groups = [
        replace(
            group,
            rank=ranks.get(index),
            score=scores.get(index),
            pareto_front=fronts.get(index),
        )
        for index, group in enumerate(groups)
    ]
    groups.sort(
        key=lambda group: (
            group.rank is None,
            group.rank or 0,
            group.design_key,
        )
    )
    return RobustResult(
        groups=tuple(groups),
        objectives=objective_list,
        condition_fields=fields,
        expected_conditions=expected,
        ranking_mode=mode,
        considered_jobs=len(selected),
    )


def write_robust_csv(path: str | Path, result: RobustResult) -> Path:
    if not result.groups:
        raise ValueError("There are no robust design groups to export")
    destination = _report_path(path, ".csv")
    design_fields = sorted(
        {name for group in result.groups for name in group.design_parameters}
    )
    metric_fields = [objective.metric for objective in result.objectives]
    fieldnames = [
        "rank",
        "pareto_front",
        "robust_score",
        "eligible",
        "exclusion_reason",
        "coverage_percent",
        "covered_states",
        "expected_states",
        "job_ids",
        *(f"design:{name}" for name in design_fields),
        *(
            f"{stat}:{metric}"
            for metric in metric_fields
            for stat in ("worst", "mean", "best", "aligned", "worst_case_change_percent")
        ),
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for group in result.groups:
            writer.writerow(
                {
                    "rank": group.rank or "",
                    "pareto_front": group.pareto_front or "",
                    "robust_score": group.score if group.score is not None else "",
                    "eligible": group.eligible,
                    "exclusion_reason": group.exclusion_reason or "",
                    "coverage_percent": group.coverage_percent,
                    "covered_states": group.covered_states,
                    "expected_states": group.expected_states,
                    "job_ids": ";".join(str(job_id) for job_id in group.job_ids),
                    **{
                        f"design:{name}": group.design_parameters.get(name, "")
                        for name in design_fields
                    },
                    **_summary_cells(group, metric_fields),
                }
            )
    return destination.resolve()


def write_robust_html(path: str | Path, result: RobustResult) -> Path:
    if not result.groups:
        raise ValueError("There are no robust design groups to export")
    destination = _report_path(path, ".html")
    metric_names = [objective.metric for objective in result.objectives]
    headings = [
        "Rank",
        "Score",
        "Coverage",
        "Status",
        "Design",
        *(f"{name} worst / mean" for name in metric_names),
        "Jobs",
    ]
    rows: list[str] = []
    for group in result.groups:
        values = [
            group.rank or "—",
            f"{group.score:.4f}" if group.score is not None else "—",
            f"{group.covered_states}/{group.expected_states} ({group.coverage_percent:.1f}%)",
            "Eligible" if group.eligible else group.exclusion_reason,
            ", ".join(f"{name}={value}" for name, value in group.design_parameters.items()) or "Shared design",
            *(
                f"{group.metric_summaries[name].worst:g} / {group.metric_summaries[name].mean:g}"
                if name in group.metric_summaries
                else "—"
                for name in metric_names
            ),
            ", ".join(f"#{job_id}" for job_id in group.job_ids),
        ]
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in values)
        row_class = "eligible" if group.eligible else "excluded"
        rows.append(f'<tr class="{row_class}">{cells}</tr>')
    objective_text = " · ".join(
        f"{html.escape(item.metric)} ({item.direction}, weight {item.weight:g})"
        for item in result.objectives
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Robust Misalignment Analysis</title>
  <style>
    body {{ font: 14px system-ui, sans-serif; margin: 32px; color: #172630; }}
    p {{ color: #667681; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #dce4e8; padding: 8px; text-align: left; }}
    th {{ background: #16324a; color: white; }}
    tr.eligible {{ background: #f3fbf9; }}
    tr.excluded {{ color: #667681; background: #f7f9fb; }}
  </style>
</head>
<body>
  <h1>Robust Misalignment Analysis</h1>
  <p>{objective_text}</p>
  <p>Ranking mode: {html.escape(result.ranking_mode.replace('_', ' ').title())}. Conditions: {html.escape(', '.join(result.condition_fields))}.</p>
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


def heatmap_values(
    group: RobustDesign,
    metric: str,
    *,
    x_field: str = "xoff",
    y_field: str = "tilt",
    direction: str = "maximize",
) -> tuple[tuple[Any, ...], tuple[Any, ...], dict[tuple[str, str], float]]:
    normalized_direction = direction.strip().casefold()
    if normalized_direction not in {"maximize", "minimize"}:
        raise ValueError("Heatmap direction must be maximize or minimize")
    x_values = _ordered_unique(state.condition.get(x_field) for state in group.states)
    y_values = _ordered_unique(state.condition.get(y_field) for state in group.states)
    cells: dict[tuple[str, str], float] = {}
    for state in group.states:
        if metric in state.metrics:
            key = (str(state.condition.get(x_field)), str(state.condition.get(y_field)))
            value = state.metrics[metric]
            previous = cells.get(key)
            if previous is None:
                cells[key] = value
            elif normalized_direction == "maximize":
                cells[key] = min(previous, value)
            else:
                cells[key] = max(previous, value)
    return x_values, y_values, cells


def _summarize_group(
    design_key: str,
    design: dict[str, Any],
    jobs_by_condition: dict[str, Job],
    expected: tuple[dict[str, Any], ...],
    objectives: tuple[RobustObjective, ...],
) -> RobustDesign:
    states: list[RobustState] = []
    rejected = 0
    unvalidated = 0
    unavailable = 0
    aligned_metrics: dict[str, float] | None = None
    for condition in expected:
        job = jobs_by_condition.get(_mapping_key(condition))
        if job is None or job.status != JobStatus.SUCCEEDED:
            unavailable += 1
            continue
        result = job.result if isinstance(job.result, dict) else {}
        metadata = result.get("metadata", {})
        validation = metadata.get("scientific_validation", {}) if isinstance(metadata, dict) else {}
        validation_status = str(validation.get("status", "not_recorded")) if isinstance(validation, dict) else "not_recorded"
        if validation_status == "rejected":
            rejected += 1
            continue
        if validation_status not in {"valid", "warning"}:
            unvalidated += 1
            continue
        raw_metrics = result.get("metrics", {})
        if not isinstance(raw_metrics, dict):
            unavailable += 1
            continue
        metrics = {name: _finite_number(raw_metrics.get(name)) for name in (item.metric for item in objectives)}
        if any(value is None for value in metrics.values()):
            unavailable += 1
            continue
        numeric_metrics = {name: float(value) for name, value in metrics.items() if value is not None}
        states.append(RobustState(job.id, dict(condition), numeric_metrics, validation_status))
        if _is_aligned(condition):
            aligned_metrics = numeric_metrics

    complete = len(states) == len(expected)
    eligible = complete and rejected == 0 and unvalidated == 0 and unavailable == 0
    if rejected:
        reason = f"{rejected} scientifically rejected state(s)"
    elif unvalidated:
        reason = f"{unvalidated} unvalidated state(s)"
    elif unavailable:
        reason = f"{unavailable} missing or unavailable state(s)"
    elif not complete:
        reason = "Incomplete condition coverage"
    else:
        reason = None
    summaries: dict[str, RobustMetricSummary] = {}
    if states:
        for objective in objectives:
            values = [state.metrics[objective.metric] for state in states]
            worst = min(values) if objective.direction == "maximize" else max(values)
            best = max(values) if objective.direction == "maximize" else min(values)
            aligned = aligned_metrics.get(objective.metric) if aligned_metrics else None
            change = None
            if aligned not in {None, 0.0}:
                sign = 1 if objective.direction == "maximize" else -1
                change = sign * (aligned - worst) / abs(aligned) * 100.0
            summaries[objective.metric] = RobustMetricSummary(
                worst=worst,
                mean=sum(values) / len(values),
                best=best,
                aligned=aligned,
                worst_case_change_percent=change,
            )
    return RobustDesign(
        rank=None,
        pareto_front=None,
        score=None,
        design_key=design_key,
        design_parameters=dict(design),
        job_ids=tuple(sorted(state.job_id for state in states)),
        states=tuple(states),
        expected_states=len(expected),
        covered_states=len(states),
        coverage_percent=100.0 * len(states) / len(expected),
        complete=complete,
        eligible=eligible,
        exclusion_reason=reason,
        rejected_states=rejected,
        unvalidated_states=unvalidated,
        unavailable_states=unavailable,
        metric_summaries=summaries,
    )


def _robust_scores(
    groups: list[RobustDesign],
    indexes: list[int],
    objectives: tuple[RobustObjective, ...],
    mode: str,
) -> dict[int, float]:
    scores = {index: 0.0 for index in indexes}
    total_weight = sum(objective.weight for objective in objectives)
    for objective in objectives:
        worst_values = {index: groups[index].metric_summaries[objective.metric].worst for index in indexes}
        mean_values = {index: groups[index].metric_summaries[objective.metric].mean for index in indexes}
        worst_scores = _normalize(worst_values, objective.direction)
        mean_scores = _normalize(mean_values, objective.direction)
        for index in indexes:
            component = {
                "worst_case": worst_scores[index],
                "average": mean_scores[index],
                "balanced": (worst_scores[index] + mean_scores[index]) / 2.0,
            }[mode]
            scores[index] += component * objective.weight / total_weight
    return scores


def _robust_fronts(
    groups: list[RobustDesign],
    indexes: list[int],
    objectives: tuple[RobustObjective, ...],
) -> dict[int, int]:
    dominators = {index: set() for index in indexes}
    dominated = {index: set() for index in indexes}
    for position, left in enumerate(indexes):
        for right in indexes[position + 1 :]:
            if _group_dominates(groups[left], groups[right], objectives):
                dominated[left].add(right)
                dominators[right].add(left)
            elif _group_dominates(groups[right], groups[left], objectives):
                dominated[right].add(left)
                dominators[left].add(right)
    remaining = {index: set(values) for index, values in dominators.items()}
    fronts: dict[int, int] = {}
    current = sorted(index for index, values in remaining.items() if not values)
    front = 1
    while current:
        next_front: list[int] = []
        for index in current:
            fronts[index] = front
            for other in dominated[index]:
                remaining[other].discard(index)
                if not remaining[other] and other not in fronts:
                    next_front.append(other)
        current = sorted(set(next_front))
        front += 1
    return fronts


def _group_dominates(left: RobustDesign, right: RobustDesign, objectives: tuple[RobustObjective, ...]) -> bool:
    no_worse = True
    better = False
    for objective in objectives:
        left_value = left.metric_summaries[objective.metric].worst
        right_value = right.metric_summaries[objective.metric].worst
        if objective.direction == "maximize":
            no_worse = no_worse and left_value >= right_value
            better = better or left_value > right_value
        else:
            no_worse = no_worse and left_value <= right_value
            better = better or left_value < right_value
    return no_worse and better


def _normalize(values: dict[int, float], direction: str) -> dict[int, float]:
    if not values:
        return {}
    minimum, maximum = min(values.values()), max(values.values())
    if maximum == minimum:
        return {index: 1.0 for index in values}
    if direction == "maximize":
        return {index: (value - minimum) / (maximum - minimum) for index, value in values.items()}
    return {index: (maximum - value) / (maximum - minimum) for index, value in values.items()}


def _infer_expected_conditions(jobs: list[Job], fields: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    values = [_ordered_unique(job.parameters[field] for job in jobs) for field in fields]
    if any(not items for items in values):
        return ()
    return tuple(dict(zip(fields, combination)) for combination in itertools.product(*values))


def _ordered_unique(values: Iterable[Any]) -> tuple[Any, ...]:
    unique: dict[str, Any] = {}
    for value in values:
        unique.setdefault(_value_key(value), value)
    return tuple(value for _, value in sorted(unique.items(), key=lambda item: item[0]))


def _condition(values: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    missing = [field for field in fields if field not in values]
    if missing:
        raise ValueError("Condition is missing field(s): " + ", ".join(missing))
    return {field: values[field] for field in fields}


def _mapping_key(values: Mapping[str, Any]) -> str:
    canonical = [(str(name), _canonical_value(value)) for name, value in sorted(values.items())]
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _canonical_value(value: Any) -> Any:
    quantity = parse_quantity(value)
    if quantity is not None:
        return ["quantity", quantity.dimension, f"{quantity.si_value:.15g}"]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return ["value", value]
    return ["value", str(value)]


def _value_key(value: Any) -> str:
    return json.dumps(_canonical_value(value), separators=(",", ":"), ensure_ascii=True)


def _is_aligned(condition: Mapping[str, Any]) -> bool:
    for value in condition.values():
        quantity = parse_quantity(value)
        if quantity is None or not math.isclose(quantity.si_value, 0.0, abs_tol=1e-15):
            return False
    return True


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _summary_cells(group: RobustDesign, metrics: list[str]) -> dict[str, Any]:
    cells: dict[str, Any] = {}
    for metric in metrics:
        summary = group.metric_summaries.get(metric)
        for stat in ("worst", "mean", "best", "aligned", "worst_case_change_percent"):
            cells[f"{stat}:{metric}"] = getattr(summary, stat) if summary is not None else ""
    return cells


def _report_path(path: str | Path, suffix: str) -> Path:
    destination = Path(path)
    if destination.suffix.casefold() != suffix:
        raise ValueError(f"Robust analysis report must use the {suffix} extension")
    return destination
