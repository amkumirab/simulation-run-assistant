from __future__ import annotations

import csv
import html
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from simulation_assistant.quantities import parse_quantity
from simulation_assistant.types import Job, JobStatus


@dataclass(frozen=True)
class InputMapping:
    primary: str
    reference: str

    def __post_init__(self) -> None:
        primary = self.primary.strip()
        reference = self.reference.strip()
        if not primary or not reference:
            raise ValueError("Input mapping names cannot be empty")
        object.__setattr__(self, "primary", primary)
        object.__setattr__(self, "reference", reference)


@dataclass(frozen=True)
class MetricTolerance:
    primary_metric: str
    reference_metric: str
    max_relative_error_percent: float | None = None
    max_absolute_error: float | None = None
    warning_ratio: float = 0.8

    def __post_init__(self) -> None:
        primary = self.primary_metric.strip()
        reference = self.reference_metric.strip()
        if not primary or not reference:
            raise ValueError("Metric mapping names cannot be empty")
        relative = _positive_optional(
            self.max_relative_error_percent,
            "Maximum relative error",
        )
        absolute = _positive_optional(
            self.max_absolute_error,
            "Maximum absolute error",
        )
        if relative is None and absolute is None:
            raise ValueError("Each metric requires a relative or absolute tolerance")
        if (
            isinstance(self.warning_ratio, bool)
            or not isinstance(self.warning_ratio, (int, float))
            or not math.isfinite(float(self.warning_ratio))
            or not 0 < float(self.warning_ratio) < 1
        ):
            raise ValueError("Warning ratio must be between zero and one")
        object.__setattr__(self, "primary_metric", primary)
        object.__setattr__(self, "reference_metric", reference)
        object.__setattr__(self, "max_relative_error_percent", relative)
        object.__setattr__(self, "max_absolute_error", absolute)
        object.__setattr__(self, "warning_ratio", float(self.warning_ratio))


@dataclass(frozen=True)
class MetricComparison:
    primary_metric: str
    reference_metric: str
    primary_value: float
    reference_value: float
    signed_difference: float
    absolute_error: float
    relative_error_percent: float | None
    status: str
    tolerance_ratio: float


@dataclass(frozen=True)
class ReferencePair:
    primary_job_id: int
    reference_job_id: int
    status: str
    input_state: dict[str, Any]
    comparisons: tuple[MetricComparison, ...]
    primary_validation: str
    reference_validation: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReferenceValidationResult:
    pairs: tuple[ReferencePair, ...]
    input_mappings: tuple[InputMapping, ...]
    metric_tolerances: tuple[MetricTolerance, ...]
    unmatched_primary_job_ids: tuple[int, ...]
    unmatched_reference_job_ids: tuple[int, ...]
    invalid_input_job_ids: tuple[int, ...]
    primary_batch: str
    reference_batch: str

    @property
    def passed_pairs(self) -> int:
        return sum(pair.status == "passed" for pair in self.pairs)

    @property
    def warning_pairs(self) -> int:
        return sum(pair.status == "warning" for pair in self.pairs)

    @property
    def failed_pairs(self) -> int:
        return sum(pair.status == "failed" for pair in self.pairs)

    @property
    def ineligible_pairs(self) -> int:
        return sum(
            pair.status in {"rejected", "unvalidated", "unavailable"}
            for pair in self.pairs
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compare_reference_models(
    primary_jobs: Iterable[Job],
    reference_jobs: Iterable[Job],
    input_mappings: Iterable[InputMapping],
    metric_tolerances: Iterable[MetricTolerance],
    *,
    primary_batch: str = "",
    reference_batch: str = "",
    primary_job_ids: Iterable[int] | None = None,
) -> ReferenceValidationResult:
    mappings = tuple(input_mappings)
    tolerances = tuple(metric_tolerances)
    if not mappings:
        raise ValueError("Reference validation requires at least one input mapping")
    if not tolerances:
        raise ValueError("Reference validation requires at least one metric tolerance")
    if len({item.primary for item in mappings}) != len(mappings):
        raise ValueError("Primary input mapping names must be unique")
    if len({item.reference for item in mappings}) != len(mappings):
        raise ValueError("Reference input mapping names must be unique")
    metric_pairs = {
        (item.primary_metric, item.reference_metric) for item in tolerances
    }
    if len(metric_pairs) != len(tolerances):
        raise ValueError("Metric tolerance mappings must be unique")

    selected_ids = (
        {int(job_id) for job_id in primary_job_ids}
        if primary_job_ids is not None
        else None
    )
    primary = [
        job
        for job in primary_jobs
        if (not primary_batch or job.batch_name == primary_batch)
        and (selected_ids is None or job.id in selected_ids)
    ]
    reference = [
        job
        for job in reference_jobs
        if not reference_batch or job.batch_name == reference_batch
    ]
    primary_by_key, invalid_primary = _latest_by_state(primary, mappings, "primary")
    reference_by_key, invalid_reference = _latest_by_state(
        reference,
        mappings,
        "reference",
    )
    common_keys = sorted(set(primary_by_key).intersection(reference_by_key))
    pairs = tuple(
        _compare_pair(
            primary_by_key[key],
            reference_by_key[key],
            mappings,
            tolerances,
        )
        for key in common_keys
    )
    unmatched_primary = tuple(
        sorted(primary_by_key[key].id for key in set(primary_by_key) - set(reference_by_key))
    )
    unmatched_reference = tuple(
        sorted(reference_by_key[key].id for key in set(reference_by_key) - set(primary_by_key))
    )
    return ReferenceValidationResult(
        pairs=pairs,
        input_mappings=mappings,
        metric_tolerances=tolerances,
        unmatched_primary_job_ids=unmatched_primary,
        unmatched_reference_job_ids=unmatched_reference,
        invalid_input_job_ids=tuple(sorted({*invalid_primary, *invalid_reference})),
        primary_batch=primary_batch,
        reference_batch=reference_batch,
    )


def write_reference_csv(
    path: str | Path,
    result: ReferenceValidationResult,
) -> Path:
    if not result.pairs:
        raise ValueError("There are no paired reference results to export")
    destination = _report_path(path, ".csv")
    input_names = [mapping.primary for mapping in result.input_mappings]
    metric_keys = [
        f"{item.primary_metric}__{item.reference_metric}"
        for item in result.metric_tolerances
    ]
    fieldnames = [
        "primary_job_id",
        "reference_job_id",
        "status",
        "message",
        "primary_validation",
        "reference_validation",
        *(f"input:{name}" for name in input_names),
        *(
            f"{field}:{key}"
            for key in metric_keys
            for field in (
                "primary",
                "reference",
                "signed_difference",
                "absolute_error",
                "relative_error_percent",
                "status",
            )
        ),
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for pair in result.pairs:
            row: dict[str, Any] = {
                "primary_job_id": pair.primary_job_id,
                "reference_job_id": pair.reference_job_id,
                "status": pair.status,
                "message": pair.message,
                "primary_validation": pair.primary_validation,
                "reference_validation": pair.reference_validation,
                **{
                    f"input:{name}": pair.input_state.get(name, "")
                    for name in input_names
                },
            }
            for comparison in pair.comparisons:
                key = f"{comparison.primary_metric}__{comparison.reference_metric}"
                row.update(
                    {
                        f"primary:{key}": comparison.primary_value,
                        f"reference:{key}": comparison.reference_value,
                        f"signed_difference:{key}": comparison.signed_difference,
                        f"absolute_error:{key}": comparison.absolute_error,
                        f"relative_error_percent:{key}": (
                            comparison.relative_error_percent
                            if comparison.relative_error_percent is not None
                            else ""
                        ),
                        f"status:{key}": comparison.status,
                    }
                )
            writer.writerow(row)
    return destination.resolve()


def write_reference_html(
    path: str | Path,
    result: ReferenceValidationResult,
) -> Path:
    if not result.pairs:
        raise ValueError("There are no paired reference results to export")
    destination = _report_path(path, ".html")
    headings = [
        "Primary job",
        "Reference job",
        "Status",
        "Input state",
        "Metric comparison",
        "Message",
    ]
    rows: list[str] = []
    for pair in result.pairs:
        metrics = "; ".join(
            f"{item.primary_metric}: {item.primary_value:g} vs "
            f"{item.reference_value:g}, error "
            f"{item.relative_error_percent:.3g}% ({item.status})"
            if item.relative_error_percent is not None
            else f"{item.primary_metric}: {item.primary_value:g} vs "
            f"{item.reference_value:g}, absolute error "
            f"{item.absolute_error:g} ({item.status})"
            for item in pair.comparisons
        ) or "No comparable metrics"
        values = [
            f"#{pair.primary_job_id}",
            f"#{pair.reference_job_id}",
            pair.status.title(),
            ", ".join(f"{name}={value}" for name, value in pair.input_state.items()),
            metrics,
            pair.message,
        ]
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in values)
        rows.append(f'<tr class="{pair.status}">{cells}</tr>')
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reference Model Validation</title>
  <style>
    body {{ font: 14px system-ui, sans-serif; margin: 32px; color: #172630; }}
    p {{ color: #667681; }}
    .summary {{ display: flex; gap: 10px; margin: 16px 0; flex-wrap: wrap; }}
    .summary span {{ background: #f3f6f8; border-radius: 8px; padding: 8px 12px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #dce4e8; padding: 8px; text-align: left; }}
    th {{ background: #16324a; color: white; }}
    tr.passed {{ background: #e5f6f3; }}
    tr.warning {{ background: #fff4d8; }}
    tr.failed, tr.rejected {{ background: #feeceb; }}
  </style>
</head>
<body>
  <h1>Reference Model Validation</h1>
  <p>{html.escape(result.primary_batch)} compared with {html.escape(result.reference_batch)}</p>
  <div class="summary">
    <span>{result.passed_pairs} passed</span>
    <span>{result.warning_pairs} warnings</span>
    <span>{result.failed_pairs} failed</span>
    <span>{result.ineligible_pairs} ineligible</span>
    <span>{len(result.unmatched_primary_job_ids)} unmatched primary</span>
    <span>{len(result.unmatched_reference_job_ids)} unmatched reference</span>
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


def _latest_by_state(
    jobs: list[Job],
    mappings: tuple[InputMapping, ...],
    side: str,
) -> tuple[dict[str, Job], set[int]]:
    latest: dict[str, Job] = {}
    invalid: set[int] = set()
    for job in jobs:
        values: list[tuple[str, Any]] = []
        valid = True
        for mapping in mappings:
            name = mapping.primary if side == "primary" else mapping.reference
            if name not in job.parameters:
                valid = False
                break
            canonical = _canonical_input(job.parameters[name])
            if canonical is None:
                valid = False
                break
            values.append((mapping.primary, canonical))
        if not valid:
            invalid.add(job.id)
            continue
        key = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        previous = latest.get(key)
        if previous is None or job.id > previous.id:
            latest[key] = job
    return latest, invalid


def _compare_pair(
    primary: Job,
    reference: Job,
    mappings: tuple[InputMapping, ...],
    tolerances: tuple[MetricTolerance, ...],
) -> ReferencePair:
    input_state = {
        mapping.primary: primary.parameters[mapping.primary] for mapping in mappings
    }
    primary_validation = _validation_status(primary)
    reference_validation = _validation_status(reference)
    blocked_status, message = _pair_gate(
        primary,
        reference,
        primary_validation,
        reference_validation,
    )
    if blocked_status is not None:
        return ReferencePair(
            primary.id,
            reference.id,
            blocked_status,
            input_state,
            (),
            primary_validation,
            reference_validation,
            message,
        )

    primary_metrics = _metrics(primary)
    reference_metrics = _metrics(reference)
    comparisons: list[MetricComparison] = []
    missing: list[str] = []
    for tolerance in tolerances:
        primary_value = _finite_number(primary_metrics.get(tolerance.primary_metric))
        reference_value = _finite_number(
            reference_metrics.get(tolerance.reference_metric)
        )
        if primary_value is None or reference_value is None:
            missing.append(
                f"{tolerance.primary_metric}/{tolerance.reference_metric}"
            )
            continue
        comparisons.append(_compare_metric(primary_value, reference_value, tolerance))
    if missing:
        return ReferencePair(
            primary.id,
            reference.id,
            "unavailable",
            input_state,
            tuple(comparisons),
            primary_validation,
            reference_validation,
            "Missing metric mapping(s): " + ", ".join(missing),
        )
    statuses = {item.status for item in comparisons}
    if "failed" in statuses:
        status = "failed"
        message = "One or more metric errors exceed the configured tolerance."
    elif "warning" in statuses or "warning" in {
        primary_validation,
        reference_validation,
    }:
        status = "warning"
        message = "The pair is within limits but requires review."
    else:
        status = "passed"
        message = "All mapped metrics are within the configured tolerance."
    return ReferencePair(
        primary.id,
        reference.id,
        status,
        input_state,
        tuple(comparisons),
        primary_validation,
        reference_validation,
        message,
    )


def _compare_metric(
    primary: float,
    reference: float,
    tolerance: MetricTolerance,
) -> MetricComparison:
    difference = primary - reference
    absolute_error = abs(difference)
    if reference == 0:
        relative_error = 0.0 if absolute_error == 0 else None
    else:
        relative_error = absolute_error / abs(reference) * 100.0
    ratios: list[float] = []
    if tolerance.max_absolute_error is not None:
        ratios.append(absolute_error / tolerance.max_absolute_error)
    if tolerance.max_relative_error_percent is not None:
        ratios.append(
            relative_error / tolerance.max_relative_error_percent
            if relative_error is not None
            else math.inf
        )
    tolerance_ratio = min(ratios)
    if tolerance_ratio > 1:
        status = "failed"
    elif tolerance_ratio >= tolerance.warning_ratio:
        status = "warning"
    else:
        status = "passed"
    return MetricComparison(
        primary_metric=tolerance.primary_metric,
        reference_metric=tolerance.reference_metric,
        primary_value=primary,
        reference_value=reference,
        signed_difference=difference,
        absolute_error=absolute_error,
        relative_error_percent=relative_error,
        status=status,
        tolerance_ratio=tolerance_ratio,
    )


def _pair_gate(
    primary: Job,
    reference: Job,
    primary_validation: str,
    reference_validation: str,
) -> tuple[str | None, str]:
    if primary.status != JobStatus.SUCCEEDED or reference.status != JobStatus.SUCCEEDED:
        return "unavailable", "Both jobs must finish successfully before comparison."
    if "rejected" in {primary_validation, reference_validation}:
        return "rejected", "A scientifically rejected result cannot validate a model."
    if primary_validation not in {"valid", "warning"} or reference_validation not in {
        "valid",
        "warning",
    }:
        return "unvalidated", "Both jobs require a recorded scientific-validation result."
    return None, ""


def _validation_status(job: Job) -> str:
    result = job.result if isinstance(job.result, dict) else {}
    metadata = result.get("metadata", {})
    validation = metadata.get("scientific_validation", {}) if isinstance(metadata, dict) else {}
    return str(validation.get("status", "not_recorded")) if isinstance(validation, dict) else "not_recorded"


def _metrics(job: Job) -> Mapping[str, Any]:
    result = job.result if isinstance(job.result, dict) else {}
    metrics = result.get("metrics", {})
    return metrics if isinstance(metrics, Mapping) else {}


def _canonical_input(value: Any) -> list[Any] | None:
    quantity = parse_quantity(value)
    if quantity is not None:
        return ["quantity", quantity.dimension, f"{quantity.si_value:.15g}"]
    if isinstance(value, (str, bool)) or value is None:
        return ["value", value]
    return None


def _positive_optional(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise ValueError(f"{label} must be positive and finite")
    return float(value)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _report_path(path: str | Path, suffix: str) -> Path:
    destination = Path(path)
    if destination.suffix.casefold() != suffix:
        raise ValueError(f"Reference validation report must use the {suffix} extension")
    return destination
