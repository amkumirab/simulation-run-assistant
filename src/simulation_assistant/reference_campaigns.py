from __future__ import annotations

import csv
import html
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from simulation_assistant.preflight import RunCandidate, build_run_signature
from simulation_assistant.reference_validation import InputMapping
from simulation_assistant.types import Job, JobStatus


REFERENCE_RETRY_STATES = {"missing", "failed", "rejected", "unvalidated"}


@dataclass(frozen=True)
class ReferenceCampaignState:
    index: int
    primary_job_id: int
    parameters: dict[str, Any]
    signature: str
    status: str
    reference_job_id: int | None
    validation_status: str
    metrics: dict[str, Any]


@dataclass(frozen=True)
class ReferenceCampaignPlan:
    states: tuple[ReferenceCampaignState, ...]
    excluded_primary_job_ids: tuple[int, ...]
    run_context: dict[str, Any]
    output_formulas: dict[str, str]
    input_mappings: tuple[InputMapping, ...]

    @property
    def pending(self) -> tuple[ReferenceCampaignState, ...]:
        return tuple(
            state for state in self.states if state.status in REFERENCE_RETRY_STATES
        )

    @property
    def completed_count(self) -> int:
        return sum(state.status in {"valid", "warning"} for state in self.states)

    @property
    def active_count(self) -> int:
        return sum(state.status in {"queued", "running"} for state in self.states)

    @property
    def failed_count(self) -> int:
        return sum(state.status == "failed" for state in self.states)

    @property
    def rejected_count(self) -> int:
        return sum(state.status in {"rejected", "unvalidated"} for state in self.states)

    def candidates_to_enqueue(self) -> tuple[RunCandidate, ...]:
        return tuple(
            RunCandidate(dict(state.parameters), state.signature)
            for state in self.pending
        )

    def pending_primary_job_ids(self) -> tuple[int, ...]:
        return tuple(state.primary_job_id for state in self.pending)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_reference_campaign_plan(
    primary_jobs: Iterable[Job],
    input_mappings: Iterable[InputMapping],
    reference_defaults: Mapping[str, Any],
    *,
    output_formulas: Mapping[str, str],
    run_context: Mapping[str, Any],
    existing_jobs: Iterable[Job],
) -> ReferenceCampaignPlan:
    mappings = tuple(input_mappings)
    if not mappings:
        raise ValueError("Reference campaign requires at least one input mapping")
    if len({mapping.primary for mapping in mappings}) != len(mappings):
        raise ValueError("Primary input mapping names must be unique")
    if len({mapping.reference for mapping in mappings}) != len(mappings):
        raise ValueError("Reference input mapping names must be unique")
    defaults = dict(reference_defaults)
    missing_targets = sorted(
        mapping.reference for mapping in mappings if mapping.reference not in defaults
    )
    if missing_targets:
        raise ValueError(
            "Connected reference model is missing mapped input(s): "
            + ", ".join(missing_targets)
        )

    eligible: list[Job] = []
    excluded: list[int] = []
    for job in primary_jobs:
        if job.status != JobStatus.SUCCEEDED or _validation_status(job) not in {
            "valid",
            "warning",
        }:
            excluded.append(job.id)
            continue
        missing_sources = [
            mapping.primary
            for mapping in mappings
            if mapping.primary not in job.parameters
        ]
        if missing_sources:
            excluded.append(job.id)
            continue
        eligible.append(job)
    if not eligible:
        raise ValueError("No accepted primary jobs contain every mapped input")

    formulas = dict(output_formulas)
    context = dict(run_context)
    states_by_signature: dict[str, tuple[Job, dict[str, Any]]] = {}
    for job in eligible:
        parameters = dict(defaults)
        for mapping in mappings:
            parameters[mapping.reference] = job.parameters[mapping.primary]
        signature = build_run_signature("comsol", parameters, formulas, context)
        previous = states_by_signature.get(signature)
        if previous is None or job.id > previous[0].id:
            if previous is not None:
                excluded.append(previous[0].id)
            states_by_signature[signature] = (job, parameters)
        else:
            excluded.append(job.id)

    jobs_by_signature: dict[str, list[Job]] = {}
    for job in existing_jobs:
        if job.run_signature:
            jobs_by_signature.setdefault(job.run_signature, []).append(job)
    for matches in jobs_by_signature.values():
        matches.sort(key=lambda item: item.id, reverse=True)

    prepared = sorted(
        states_by_signature.items(),
        key=lambda item: item[1][0].id,
    )
    states: list[ReferenceCampaignState] = []
    for index, (signature, (primary, parameters)) in enumerate(prepared, 1):
        status, reference, validation = _classify_reference_jobs(
            jobs_by_signature.get(signature, [])
        )
        states.append(
            ReferenceCampaignState(
                index=index,
                primary_job_id=primary.id,
                parameters=parameters,
                signature=signature,
                status=status,
                reference_job_id=reference.id if reference else None,
                validation_status=validation,
                metrics=_job_metrics(reference),
            )
        )
    return ReferenceCampaignPlan(
        states=tuple(states),
        excluded_primary_job_ids=tuple(sorted(set(excluded))),
        run_context=context,
        output_formulas=formulas,
        input_mappings=mappings,
    )


def write_reference_campaign_csv(
    path: str | Path,
    plan: ReferenceCampaignPlan,
) -> Path:
    destination = _report_path(path, ".csv")
    parameters = sorted(
        {str(name) for state in plan.states for name in state.parameters}
    )
    fields = [
        "state",
        "primary_job_id",
        "reference_job_id",
        "status",
        "validation_status",
        *(f"reference_input:{name}" for name in parameters),
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for state in plan.states:
            writer.writerow(
                {
                    "state": state.index,
                    "primary_job_id": state.primary_job_id,
                    "reference_job_id": state.reference_job_id or "",
                    "status": state.status,
                    "validation_status": state.validation_status,
                    **{
                        f"reference_input:{name}": state.parameters.get(name, "")
                        for name in parameters
                    },
                }
            )
    return destination.resolve()


def write_reference_campaign_html(
    path: str | Path,
    plan: ReferenceCampaignPlan,
) -> Path:
    destination = _report_path(path, ".html")
    rows: list[str] = []
    for state in plan.states:
        values = [
            state.index,
            f"#{state.primary_job_id}",
            f"#{state.reference_job_id}" if state.reference_job_id else "",
            state.status,
            state.validation_status,
            ", ".join(
                f"{name}={value}" for name, value in state.parameters.items()
            ),
        ]
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in values)
        rows.append(f'<tr data-status="{html.escape(state.status)}">{cells}</tr>')
    headings = (
        "State",
        "Primary job",
        "Reference job",
        "Status",
        "Validation",
        "Reference inputs",
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reference Validation Campaign</title>
  <style>
    body {{ font: 14px system-ui, sans-serif; margin: 32px; color: #172630; }}
    p {{ color: #667681; }}
    .summary {{ display: flex; gap: 10px; margin: 16px 0; flex-wrap: wrap; }}
    .summary span {{ background: #f3f6f8; border-radius: 8px; padding: 8px 12px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #dce4e8; padding: 8px; text-align: left; }}
    th {{ background: #16324a; color: white; }}
    tr[data-status="valid"], tr[data-status="warning"] {{ background: #e5f6f3; }}
    tr[data-status="failed"], tr[data-status="rejected"] {{ background: #feeceb; }}
  </style>
</head>
<body>
  <h1>Reference Validation Campaign</h1>
  <p>Portable execution plan for selected primary design states.</p>
  <div class="summary">
    <span>{len(plan.states)} states</span>
    <span>{plan.completed_count} accepted</span>
    <span>{plan.active_count} active</span>
    <span>{len(plan.pending)} pending</span>
    <span>{len(plan.excluded_primary_job_ids)} excluded primary jobs</span>
  </div>
  <table>
    <thead><tr>{''.join(f'<th>{heading}</th>' for heading in headings)}</tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination.resolve()


def _classify_reference_jobs(jobs: list[Job]) -> tuple[str, Job | None, str]:
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
                accepted.append((job, validation))
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


def _report_path(path: str | Path, suffix: str) -> Path:
    destination = Path(path)
    if destination.suffix.casefold() != suffix:
        raise ValueError(f"Reference campaign report must use the {suffix} extension")
    return destination
