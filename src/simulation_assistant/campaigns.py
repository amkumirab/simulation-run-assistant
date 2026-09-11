from __future__ import annotations

import csv
import html
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from simulation_assistant.preflight import RunCandidate, build_run_signature
from simulation_assistant.types import Job, JobStatus


WPT_BASELINE_SWEEP = {
    "gap": ("100[mm]", "150[mm]", "200[mm]"),
    "xoff": ("0[mm]", "25[mm]", "50[mm]", "75[mm]"),
    "tilt": ("0[deg]", "5[deg]", "10[deg]"),
    "yoff": ("0[mm]",),
}
CAMPAIGN_RETRY_STATES = {"missing", "failed", "rejected", "unvalidated"}


@dataclass(frozen=True)
class CampaignState:
    index: int
    parameters: dict[str, Any]
    signature: str
    status: str
    job_id: int | None
    validation_status: str
    metrics: dict[str, Any]


@dataclass(frozen=True)
class CampaignPlan:
    states: tuple[CampaignState, ...]
    run_context: dict[str, Any]
    output_formulas: dict[str, str]

    @property
    def pending(self) -> tuple[CampaignState, ...]:
        return tuple(state for state in self.states if state.status in CAMPAIGN_RETRY_STATES)

    @property
    def completed_count(self) -> int:
        return sum(state.status in {"valid", "warning"} for state in self.states)

    @property
    def active_count(self) -> int:
        return sum(state.status in {"queued", "running"} for state in self.states)

    @property
    def rejected_count(self) -> int:
        return sum(state.status in {"rejected", "unvalidated"} for state in self.states)

    @property
    def failed_count(self) -> int:
        return sum(state.status == "failed" for state in self.states)

    def candidates_to_enqueue(self) -> tuple[RunCandidate, ...]:
        return tuple(
            RunCandidate(dict(state.parameters), state.signature)
            for state in self.pending
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_wpt_baseline_parameters(
    fixed_parameters: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build the documented 3 x 4 x 3 WPT alignment campaign."""
    required = set(WPT_BASELINE_SWEEP)
    missing = sorted(required.difference(fixed_parameters))
    if missing:
        raise ValueError(
            "The connected model is missing baseline input(s): " + ", ".join(missing)
        )
    base = dict(fixed_parameters)
    states: list[dict[str, Any]] = []
    for gap in WPT_BASELINE_SWEEP["gap"]:
        for xoff in WPT_BASELINE_SWEEP["xoff"]:
            for tilt in WPT_BASELINE_SWEEP["tilt"]:
                parameters = dict(base)
                parameters.update(
                    {
                        "gap": gap,
                        "xoff": xoff,
                        "tilt": tilt,
                        "yoff": WPT_BASELINE_SWEEP["yoff"][0],
                    }
                )
                states.append(parameters)
    return states


def build_campaign_plan(
    parameter_sets: Iterable[Mapping[str, Any]],
    *,
    adapter: str,
    output_formulas: Mapping[str, str],
    run_context: Mapping[str, Any],
    existing_jobs: Iterable[Job],
) -> CampaignPlan:
    formulas = dict(output_formulas)
    context = dict(run_context)
    jobs_by_signature: dict[str, list[Job]] = {}
    for job in existing_jobs:
        if job.run_signature:
            jobs_by_signature.setdefault(job.run_signature, []).append(job)
    for jobs in jobs_by_signature.values():
        jobs.sort(key=lambda item: item.id, reverse=True)

    states: list[CampaignState] = []
    seen: set[str] = set()
    for index, raw_parameters in enumerate(parameter_sets, 1):
        parameters = dict(raw_parameters)
        signature = build_run_signature(adapter, parameters, formulas, context)
        if signature in seen:
            raise ValueError("Campaign parameter states must be unique")
        seen.add(signature)
        status, job, validation = _classify_jobs(jobs_by_signature.get(signature, []))
        states.append(
            CampaignState(
                index=index,
                parameters=parameters,
                signature=signature,
                status=status,
                job_id=job.id if job is not None else None,
                validation_status=validation,
                metrics=_job_metrics(job),
            )
        )
    return CampaignPlan(tuple(states), context, formulas)


def estimate_campaign_storage_bytes(
    state_count: int,
    completed_jobs: Iterable[Job],
) -> int | None:
    if state_count < 0:
        raise ValueError("Campaign state count cannot be negative")
    sizes: list[float] = []
    for job in completed_jobs:
        if job.status != JobStatus.SUCCEEDED or job.adapter != "comsol":
            continue
        value = _job_metrics(job).get("output_model_bytes")
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and value >= 0
        ):
            sizes.append(float(value))
        if len(sizes) >= 20:
            break
    if not sizes:
        return None
    return round(state_count * (sum(sizes) / len(sizes)))


def write_campaign_csv(path: str | Path, plan: CampaignPlan) -> Path:
    destination = _report_path(path, ".csv")
    parameter_names, metric_names, fieldnames = _report_columns(plan)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for state in plan.states:
            writer.writerow(
                {
                    "state": state.index,
                    "status": state.status,
                    "validation_status": state.validation_status,
                    "job_id": state.job_id or "",
                    **{
                        f"input_{name}": state.parameters.get(name, "")
                        for name in parameter_names
                    },
                    **{
                        f"output_{name}": state.metrics.get(name, "")
                        for name in metric_names
                    },
                }
            )
    return destination.resolve()


def write_campaign_html(path: str | Path, plan: CampaignPlan) -> Path:
    destination = _report_path(path, ".html")
    parameter_names, metric_names, columns = _report_columns(plan)
    rows: list[str] = []
    for state in plan.states:
        values = {
            "state": state.index,
            "status": state.status,
            "validation_status": state.validation_status,
            "job_id": state.job_id or "",
            **{
                f"input_{name}": state.parameters.get(name, "")
                for name in parameter_names
            },
            **{
                f"output_{name}": state.metrics.get(name, "")
                for name in metric_names
            },
        }
        cells = "".join(
            f"<td>{html.escape(str(values.get(name, '')))}</td>"
            for name in columns
        )
        rows.append(f'<tr data-status="{html.escape(state.status)}">{cells}</tr>')
    headings = "".join(f"<th>{html.escape(name)}</th>" for name in columns)
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WPT Baseline Campaign</title>
  <style>
    body {{ font: 14px system-ui, sans-serif; margin: 32px; color: #172630; }}
    h1 {{ margin-bottom: 4px; }}
    p {{ color: #667681; }}
    .summary {{ display: flex; gap: 12px; margin: 20px 0; flex-wrap: wrap; }}
    .summary span {{ background: #f3f6f8; padding: 10px 14px; border-radius: 8px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border: 1px solid #dce4e8; padding: 7px 9px; text-align: left; }}
    th {{ background: #16324a; color: white; position: sticky; top: 0; }}
    tr[data-status="valid"] {{ background: #e5f6f3; }}
    tr[data-status="rejected"], tr[data-status="failed"] {{ background: #feeceb; }}
  </style>
</head>
<body>
  <h1>WPT Baseline Campaign</h1>
  <p>Portable campaign status and normalized simulation results.</p>
  <div class="summary">
    <span>{len(plan.states)} states</span>
    <span>{plan.completed_count} accepted</span>
    <span>{plan.active_count} active</span>
    <span>{len(plan.pending)} pending</span>
  </div>
  <table><thead><tr>{headings}</tr></thead><tbody>{''.join(rows)}</tbody></table>
</body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination.resolve()


def _classify_jobs(jobs: list[Job]) -> tuple[str, Job | None, str]:
    active = next(
        (job for job in jobs if job.status in {JobStatus.RUNNING, JobStatus.QUEUED}),
        None,
    )
    if active is not None:
        return active.status.value, active, ""
    accepted: list[tuple[Job, str]] = []
    retryable: list[tuple[Job, str, str]] = []
    for job in jobs:
        if job.status == JobStatus.SUCCEEDED and job.result is not None:
            result = job.result if isinstance(job.result, dict) else {}
            metadata = result.get("metadata", {})
            validation = (
                metadata.get("scientific_validation", {})
                if isinstance(metadata, dict)
                else {}
            )
            validation_status = (
                str(validation.get("status", ""))
                if isinstance(validation, dict)
                else ""
            )
            if validation_status in {"valid", "warning"}:
                accepted.append((job, validation_status))
            elif validation_status == "rejected":
                retryable.append((job, "rejected", "rejected"))
            else:
                retryable.append((job, "unvalidated", ""))
        elif job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
            retryable.append((job, "failed", ""))
    if accepted:
        job, validation_status = accepted[0]
        return validation_status, job, validation_status
    if retryable:
        job, status, validation_status = max(
            retryable, key=lambda item: item[0].id
        )
        return status, job, validation_status
    return "missing", None, ""


def _job_metrics(job: Job | None) -> dict[str, Any]:
    if job is None or not isinstance(job.result, dict):
        return {}
    metrics = job.result.get("metrics", {})
    return dict(metrics) if isinstance(metrics, dict) else {}


def _report_columns(plan: CampaignPlan) -> tuple[list[str], list[str], list[str]]:
    parameter_names = sorted(
        {str(name) for state in plan.states for name in state.parameters}
    )
    metric_names = sorted(
        {str(name) for state in plan.states for name in state.metrics}
    )
    columns = [
        "state",
        "status",
        "validation_status",
        "job_id",
        *(f"input_{name}" for name in parameter_names),
        *(f"output_{name}" for name in metric_names),
    ]
    return parameter_names, metric_names, columns


def _report_path(path: str | Path, suffix: str) -> Path:
    destination = Path(path)
    if destination.suffix.casefold() != suffix:
        raise ValueError(f"Campaign report must use the {suffix} extension")
    return destination
