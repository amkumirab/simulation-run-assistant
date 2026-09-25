from __future__ import annotations

import csv
import html
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from simulation_assistant.preflight import RunCandidate, build_run_signature
from simulation_assistant.types import Job, JobStatus


MESH_RETRY_STATES = {
    "missing",
    "missing_outputs",
    "failed",
    "rejected",
    "unvalidated",
}


@dataclass(frozen=True)
class MeshLevel:
    label: str
    value: str

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("Mesh level label cannot be empty")
        if not self.value.strip():
            raise ValueError(f"Mesh level '{self.label}' needs a parameter value")


@dataclass(frozen=True)
class ConvergenceMetric:
    name: str
    max_relative_change_percent: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Convergence metric name cannot be empty")
        tolerance = self.max_relative_change_percent
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(float(tolerance))
            or tolerance < 0
        ):
            raise ValueError(
                f"Convergence tolerance for '{self.name}' must be a non-negative number"
            )


@dataclass(frozen=True)
class MeshConvergenceState:
    index: int
    level: str
    mesh_value: str
    parameters: dict[str, Any]
    signature: str
    run_status: str
    job_id: int | None
    validation_status: str
    metrics: dict[str, Any]
    relative_changes_percent: dict[str, float]
    convergence_status: str
    message: str
    duration_seconds: float | None
    degrees_of_freedom: float | None


@dataclass(frozen=True)
class MeshConvergencePlan:
    base_job_id: int
    mesh_parameter: str
    levels: tuple[MeshLevel, ...]
    metrics: tuple[ConvergenceMetric, ...]
    states: tuple[MeshConvergenceState, ...]
    run_context: dict[str, Any]
    output_formulas: dict[str, str]
    status: str
    recommended_level: str | None
    recommended_job_id: int | None
    message: str

    @property
    def pending(self) -> tuple[MeshConvergenceState, ...]:
        return tuple(
            state for state in self.states if state.run_status in MESH_RETRY_STATES
        )

    @property
    def completed_count(self) -> int:
        return sum(state.run_status in {"valid", "warning"} for state in self.states)

    @property
    def active_count(self) -> int:
        return sum(state.run_status in {"queued", "running"} for state in self.states)

    def candidates_to_enqueue(self) -> tuple[RunCandidate, ...]:
        return tuple(
            RunCandidate(dict(state.parameters), state.signature)
            for state in self.pending
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_mesh_levels(specification: str) -> tuple[MeshLevel, ...]:
    """Parse ordered ``label=value`` pairs used by the desktop workspace."""
    levels: list[MeshLevel] = []
    for index, item in enumerate(specification.split(","), 1):
        text = item.strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(
                f"Mesh level {index} must use the label=value format"
            )
        label, value = (part.strip() for part in text.split("=", 1))
        levels.append(MeshLevel(label, value))
    if len(levels) < 2:
        raise ValueError("A mesh convergence study requires at least two levels")
    labels = [level.label.casefold() for level in levels]
    if len(set(labels)) != len(labels):
        raise ValueError("Mesh level labels must be unique")
    values = [level.value.casefold() for level in levels]
    if len(set(values)) != len(values):
        raise ValueError("Mesh level values must be unique")
    return tuple(levels)


def build_mesh_convergence_plan(
    base_job: Job,
    mesh_parameter: str,
    levels: Iterable[MeshLevel],
    metrics: Iterable[ConvergenceMetric],
    *,
    output_formulas: Mapping[str, str],
    run_context: Mapping[str, Any],
    existing_jobs: Iterable[Job],
) -> MeshConvergencePlan:
    parameter_name = mesh_parameter.strip()
    if not parameter_name:
        raise ValueError("Mesh control parameter cannot be empty")
    prepared_levels = tuple(levels)
    if len(prepared_levels) < 2:
        raise ValueError("A mesh convergence study requires at least two levels")
    labels = [level.label.casefold() for level in prepared_levels]
    values = [level.value.casefold() for level in prepared_levels]
    if len(set(labels)) != len(labels):
        raise ValueError("Mesh level labels must be unique")
    if len(set(values)) != len(values):
        raise ValueError("Mesh level values must be unique")

    prepared_metrics = tuple(metrics)
    if not prepared_metrics:
        raise ValueError("Select at least one physical output for convergence")
    metric_names = [metric.name for metric in prepared_metrics]
    if len(set(metric_names)) != len(metric_names):
        raise ValueError("Convergence metric names must be unique")
    if base_job.status != JobStatus.SUCCEEDED or _validation_status(base_job) not in {
        "valid",
        "warning",
    }:
        raise ValueError("The base job must have an accepted scientific result")

    formulas = dict(output_formulas)
    context = dict(run_context)
    jobs_by_signature: dict[str, list[Job]] = {}
    for job in existing_jobs:
        if job.run_signature:
            jobs_by_signature.setdefault(job.run_signature, []).append(job)
    for matches in jobs_by_signature.values():
        matches.sort(key=lambda item: item.id, reverse=True)

    raw_states: list[dict[str, Any]] = []
    signatures: set[str] = set()
    for index, level in enumerate(prepared_levels, 1):
        parameters = dict(base_job.parameters)
        parameters[parameter_name] = level.value
        signature = build_run_signature("comsol", parameters, formulas, context)
        if signature in signatures:
            raise ValueError("Mesh levels must produce unique simulation states")
        signatures.add(signature)
        run_status, job, validation = _classify_jobs(
            jobs_by_signature.get(signature, []),
            metric_names,
        )
        raw_states.append(
            {
                "index": index,
                "level": level,
                "parameters": parameters,
                "signature": signature,
                "run_status": run_status,
                "job": job,
                "validation": validation,
                "metrics": _job_metrics(job),
            }
        )

    states: list[MeshConvergenceState] = []
    transition_passes: dict[int, bool] = {}
    for index, raw in enumerate(raw_states):
        changes: dict[str, float] = {}
        convergence_status = "waiting"
        message = "Run or resume this mesh level."
        accepted = raw["run_status"] in {"valid", "warning"}
        if accepted and index == 0:
            convergence_status = "baseline"
            message = "Coarsest completed level; the next level provides the first comparison."
        elif accepted:
            previous = raw_states[index - 1]
            previous_accepted = previous["run_status"] in {"valid", "warning"}
            if not previous_accepted:
                convergence_status = "incomplete"
                message = "The preceding mesh level does not have an accepted result."
            else:
                missing: list[str] = []
                failed: list[str] = []
                for metric in prepared_metrics:
                    coarse = _finite_number(previous["metrics"].get(metric.name))
                    fine = _finite_number(raw["metrics"].get(metric.name))
                    if coarse is None or fine is None:
                        missing.append(metric.name)
                        continue
                    change = _relative_change_percent(coarse, fine)
                    changes[metric.name] = change
                    if change > metric.max_relative_change_percent:
                        failed.append(metric.name)
                if missing:
                    convergence_status = "incomplete"
                    message = "Missing numeric output(s): " + ", ".join(missing)
                elif failed:
                    convergence_status = "not_converged"
                    message = "Tolerance exceeded for: " + ", ".join(failed)
                    transition_passes[index] = False
                else:
                    convergence_status = "converged"
                    message = "All selected outputs are within tolerance."
                    transition_passes[index] = True
        elif raw["run_status"] in {"rejected", "unvalidated"}:
            convergence_status = "invalid"
            message = "The simulation result did not pass scientific validation."
        elif raw["run_status"] == "failed":
            convergence_status = "failed"
            message = "The simulation must be run again before comparison."

        job = raw["job"]
        states.append(
            MeshConvergenceState(
                index=raw["index"],
                level=raw["level"].label,
                mesh_value=raw["level"].value,
                parameters=raw["parameters"],
                signature=raw["signature"],
                run_status=raw["run_status"],
                job_id=job.id if job is not None else None,
                validation_status=raw["validation"],
                metrics=raw["metrics"],
                relative_changes_percent=changes,
                convergence_status=convergence_status,
                message=message,
                duration_seconds=_duration_seconds(raw["metrics"]),
                degrees_of_freedom=_finite_number(
                    raw["metrics"].get("degrees_of_freedom")
                ),
            )
        )

    accepted_all = all(
        state.run_status in {"valid", "warning"} for state in states
    )
    complete_transitions = all(index in transition_passes for index in range(1, len(states)))
    recommended_index: int | None = None
    if accepted_all and complete_transitions:
        for index in range(1, len(states)):
            if all(transition_passes.get(step, False) for step in range(index, len(states))):
                recommended_index = index
                break

    if recommended_index is not None:
        status = "converged"
        recommended = states[recommended_index]
        message = (
            f"{recommended.level} is the lightest level whose remaining refinements "
            "stay within every selected tolerance."
        )
    elif accepted_all and complete_transitions:
        status = "not_converged"
        recommended = None
        message = "The finest completed transition still exceeds a selected tolerance."
    elif any(state.run_status in {"queued", "running"} for state in states):
        status = "running"
        recommended = None
        message = "The study has queued or running mesh levels."
    else:
        status = "incomplete"
        recommended = None
        message = "Complete every mesh level with accepted outputs to assess convergence."

    return MeshConvergencePlan(
        base_job_id=base_job.id,
        mesh_parameter=parameter_name,
        levels=prepared_levels,
        metrics=prepared_metrics,
        states=tuple(states),
        run_context=context,
        output_formulas=formulas,
        status=status,
        recommended_level=recommended.level if recommended else None,
        recommended_job_id=recommended.job_id if recommended else None,
        message=message,
    )


def write_mesh_convergence_csv(
    path: str | Path,
    plan: MeshConvergencePlan,
) -> Path:
    destination = _report_path(path, ".csv")
    metric_names = [metric.name for metric in plan.metrics]
    fields = [
        "level_index",
        "level",
        "mesh_parameter",
        "mesh_value",
        "job_id",
        "run_status",
        "validation_status",
        "convergence_status",
        "duration_seconds",
        "degrees_of_freedom",
        *(f"output:{name}" for name in metric_names),
        *(f"relative_change_percent:{name}" for name in metric_names),
        "message",
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for state in plan.states:
            writer.writerow(
                {
                    "level_index": state.index,
                    "level": state.level,
                    "mesh_parameter": plan.mesh_parameter,
                    "mesh_value": state.mesh_value,
                    "job_id": state.job_id or "",
                    "run_status": state.run_status,
                    "validation_status": state.validation_status,
                    "convergence_status": state.convergence_status,
                    "duration_seconds": state.duration_seconds
                    if state.duration_seconds is not None
                    else "",
                    "degrees_of_freedom": state.degrees_of_freedom
                    if state.degrees_of_freedom is not None
                    else "",
                    **{
                        f"output:{name}": state.metrics.get(name, "")
                        for name in metric_names
                    },
                    **{
                        f"relative_change_percent:{name}": (
                            state.relative_changes_percent.get(name, "")
                        )
                        for name in metric_names
                    },
                    "message": state.message,
                }
            )
    return destination.resolve()


def write_mesh_convergence_html(
    path: str | Path,
    plan: MeshConvergencePlan,
) -> Path:
    destination = _report_path(path, ".html")
    metric_names = [metric.name for metric in plan.metrics]
    rows: list[str] = []
    for state in plan.states:
        output_text = ", ".join(
            f"{name}={state.metrics.get(name, '')}" for name in metric_names
        )
        change_text = ", ".join(
            f"{name}={value:.4g}%"
            for name, value in state.relative_changes_percent.items()
        )
        values = (
            state.index,
            state.level,
            state.mesh_value,
            f"#{state.job_id}" if state.job_id else "",
            state.run_status,
            state.validation_status,
            state.convergence_status,
            output_text,
            change_text,
            _display_number(state.degrees_of_freedom),
            _display_number(state.duration_seconds),
        )
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in values)
        rows.append(
            f'<tr data-status="{html.escape(state.convergence_status)}">{cells}</tr>'
        )
    recommended = (
        f"{html.escape(plan.recommended_level)} (Job #{plan.recommended_job_id})"
        if plan.recommended_level and plan.recommended_job_id
        else "Not available"
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Mesh Convergence Study</title>
  <style>
    body {{ font: 14px system-ui, sans-serif; margin: 32px; color: #172630; }}
    p {{ color: #667681; }}
    .summary {{ display: flex; gap: 10px; margin: 16px 0; flex-wrap: wrap; }}
    .summary span {{ background: #f3f6f8; border-radius: 8px; padding: 8px 12px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border: 1px solid #dce4e8; padding: 8px; text-align: left; }}
    th {{ background: #16324a; color: white; position: sticky; top: 0; }}
    tr[data-status="converged"] {{ background: #e5f6f3; }}
    tr[data-status="not_converged"], tr[data-status="failed"],
    tr[data-status="invalid"] {{ background: #feeceb; }}
  </style>
</head>
<body>
  <h1>Mesh Convergence Study</h1>
  <p>{html.escape(plan.message)}</p>
  <div class="summary">
    <span>Status: {html.escape(plan.status)}</span>
    <span>Base Job: #{plan.base_job_id}</span>
    <span>Mesh parameter: {html.escape(plan.mesh_parameter)}</span>
    <span>Recommended level: {recommended}</span>
  </div>
  <table>
    <thead><tr><th>#</th><th>Level</th><th>Value</th><th>Job</th><th>Run</th>
    <th>Validation</th><th>Convergence</th><th>Outputs</th><th>Change</th>
    <th>DOF</th><th>Duration (s)</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination.resolve()


def _classify_jobs(
    jobs: list[Job],
    required_metrics: Iterable[str],
) -> tuple[str, Job | None, str]:
    metric_names = tuple(required_metrics)
    active = next(
        (job for job in jobs if job.status in {JobStatus.RUNNING, JobStatus.QUEUED}),
        None,
    )
    if active is not None:
        return active.status.value, active, ""
    accepted: list[tuple[Job, str]] = []
    retryable: list[tuple[Job, str, str]] = []
    for job in jobs:
        if job.status == JobStatus.SUCCEEDED:
            validation = _validation_status(job)
            if validation in {"valid", "warning"}:
                metrics = _job_metrics(job)
                if all(_finite_number(metrics.get(name)) is not None for name in metric_names):
                    accepted.append((job, validation))
                else:
                    retryable.append((job, "missing_outputs", validation))
            elif validation == "rejected":
                retryable.append((job, "rejected", validation))
            else:
                retryable.append((job, "unvalidated", validation))
        elif job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
            retryable.append((job, "failed", ""))
    if accepted:
        job, validation = accepted[0]
        return validation, job, validation
    if retryable:
        job, status, validation = max(retryable, key=lambda item: item[0].id)
        return status, job, validation
    return "missing", None, ""


def _validation_status(job: Job) -> str:
    result = job.result if isinstance(job.result, dict) else {}
    metadata = result.get("metadata", {})
    validation = (
        metadata.get("scientific_validation", {})
        if isinstance(metadata, dict)
        else {}
    )
    return (
        str(validation.get("status", "not_recorded"))
        if isinstance(validation, dict)
        else "not_recorded"
    )


def _job_metrics(job: Job | None) -> dict[str, Any]:
    if job is None or not isinstance(job.result, dict):
        return {}
    metrics = job.result.get("metrics", {})
    return dict(metrics) if isinstance(metrics, dict) else {}


def _relative_change_percent(coarse: float, fine: float) -> float:
    scale = max(abs(fine), 1e-30)
    return abs(fine - coarse) / scale * 100.0


def _duration_seconds(metrics: Mapping[str, Any]) -> float | None:
    for name in (
        "comsol_duration_seconds",
        "comsol_reported_run_seconds",
        "comsol_reported_total_seconds",
    ):
        value = _finite_number(metrics.get(name))
        if value is not None:
            return value
    return None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _display_number(value: float | None) -> str:
    return "" if value is None else f"{value:.9g}"


def _report_path(path: str | Path, suffix: str) -> Path:
    destination = Path(path)
    if destination.suffix.casefold() != suffix:
        raise ValueError(f"Mesh convergence report must use the {suffix} extension")
    return destination
