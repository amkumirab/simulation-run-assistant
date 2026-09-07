from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from simulation_assistant.quantities import parse_quantity


METRIC_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FINDING_LEVELS = {"warning", "error"}
DIAGNOSTIC_LEVELS = {"ignore", "warning", "error"}


@dataclass(frozen=True)
class MetricBound:
    metric: str
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None
    severity: str = "error"
    exclusive_minimum: bool = False
    exclusive_maximum: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "min": self.minimum,
            "max": self.maximum,
            "unit": self.unit,
            "severity": self.severity,
            "exclusive_min": self.exclusive_minimum,
            "exclusive_max": self.exclusive_maximum,
        }


@dataclass(frozen=True)
class ReciprocityRule:
    left: str
    right: str
    relative_tolerance: float
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationPolicy:
    required_metrics: tuple[str, ...] = ()
    bounds: tuple[MetricBound, ...] = ()
    reciprocity: tuple[ReciprocityRule, ...] = ()
    require_fresh_pipeline: bool = False
    solver_warnings: str = "warning"
    convergence_issues: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_metrics": list(self.required_metrics),
            "bounds": [item.to_dict() for item in self.bounds],
            "reciprocity": [item.to_dict() for item in self.reciprocity],
            "require_fresh_pipeline": self.require_fresh_pipeline,
            "solver_warnings": self.solver_warnings,
            "convergence_issues": self.convergence_issues,
        }


@dataclass(frozen=True)
class ValidationFinding:
    level: str
    code: str
    message: str
    action: str
    metric: str | None = None
    observed: float | str | None = None


@dataclass(frozen=True)
class ScientificValidationReport:
    status: str
    checked_metrics: tuple[str, ...]
    findings: tuple[ValidationFinding, ...]

    @property
    def rejected(self) -> bool:
        return self.status == "rejected"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_validation_policy(
    value: Any,
    *,
    implicit_required_metrics: Iterable[str] = (),
    require_fresh_pipeline: bool = False,
    metric_units: Mapping[str, str | None] | None = None,
) -> ValidationPolicy:
    if value is None:
        data: Mapping[str, Any] = {}
    elif isinstance(value, Mapping):
        data = value
    else:
        raise ValueError("Model contract 'validation' must be an object")

    required = [
        _metric_name(item, "validation.required_metrics[]")
        for item in _list(data, "required_metrics")
    ]
    required = list(dict.fromkeys([*implicit_required_metrics, *required]))
    bounds = tuple(
        _parse_bound(item, index, metric_units or {})
        for index, item in enumerate(_list(data, "bounds"))
    )
    bound_names = [item.metric for item in bounds]
    if len(bound_names) != len(set(bound_names)):
        raise ValueError("Model contract validation bound metrics must be unique")
    reciprocity = tuple(
        _parse_reciprocity(item, index, metric_units or {})
        for index, item in enumerate(_list(data, "reciprocity"))
    )
    pairs = [{item.left, item.right} for item in reciprocity]
    if any(pair in pairs[:index] for index, pair in enumerate(pairs)):
        raise ValueError("Model contract validation reciprocity pairs must be unique")

    fresh = data.get("require_fresh_pipeline", require_fresh_pipeline)
    if not isinstance(fresh, bool):
        raise ValueError(
            "Model contract 'validation.require_fresh_pipeline' must be true or false"
        )
    solver_warnings = _diagnostic_level(
        data.get("solver_warnings", "warning"), "validation.solver_warnings"
    )
    convergence_issues = _diagnostic_level(
        data.get("convergence_issues", "error"),
        "validation.convergence_issues",
    )
    return ValidationPolicy(
        required_metrics=tuple(required),
        bounds=bounds,
        reciprocity=reciprocity,
        require_fresh_pipeline=fresh,
        solver_warnings=solver_warnings,
        convergence_issues=convergence_issues,
    )


def validate_scientific_result(
    metrics: Mapping[str, Any],
    metadata: Mapping[str, Any],
    policy: ValidationPolicy | None = None,
) -> ScientificValidationReport:
    active_policy = policy or ValidationPolicy()
    findings: list[ValidationFinding] = []
    finite_metrics: dict[str, float] = {}

    for name, value in metrics.items():
        parsed = _finite_number(value)
        if parsed is None:
            _finding(
                findings,
                "error",
                "non_finite_metric",
                f"Metric '{name}' is not a finite number.",
                "Inspect the numerical evaluation and exclude undefined values.",
                metric=str(name),
                observed=str(value),
            )
        else:
            finite_metrics[str(name)] = parsed

    for name in active_policy.required_metrics:
        if name not in finite_metrics:
            _finding(
                findings,
                "error",
                "required_metric_missing",
                f"Required metric '{name}' is missing or invalid.",
                "Repair its result-table binding or Derived Values evaluation.",
                metric=name,
            )

    if active_policy.require_fresh_pipeline:
        pipeline = metadata.get("result_pipeline")
        pipeline_status = (
            str(pipeline.get("status", "unknown"))
            if isinstance(pipeline, Mapping)
            else "unknown"
        )
        if pipeline_status != "fresh":
            _finding(
                findings,
                "error",
                "result_pipeline_not_fresh",
                f"The result pipeline is '{pipeline_status}', not fresh.",
                "Run a verified Job Sequence that solves before evaluating Derived Values.",
                observed=pipeline_status,
            )

    for rule in active_policy.bounds:
        value = finite_metrics.get(rule.metric)
        if value is None:
            continue
        below = rule.minimum is not None and (
            value <= rule.minimum if rule.exclusive_minimum else value < rule.minimum
        )
        above = rule.maximum is not None and (
            value >= rule.maximum if rule.exclusive_maximum else value > rule.maximum
        )
        if below or above:
            expected = _bound_description(rule)
            _finding(
                findings,
                rule.severity,
                "metric_out_of_bounds",
                f"Metric '{rule.metric}' is outside the allowed range {expected}.",
                "Review the model setup, units, and physical assumptions before using this run.",
                metric=rule.metric,
                observed=value,
            )

    for rule in active_policy.reciprocity:
        left = finite_metrics.get(rule.left)
        right = finite_metrics.get(rule.right)
        if left is None or right is None:
            missing = rule.left if left is None else rule.right
            _finding(
                findings,
                rule.severity,
                "reciprocity_metric_missing",
                f"Reciprocity check cannot run because '{missing}' is unavailable.",
                "Add both directional quantities to the model contract outputs.",
                metric=missing,
            )
            continue
        scale = max(abs(left), abs(right))
        relative_error = 0.0 if scale == 0 else abs(left - right) / scale
        if relative_error > rule.relative_tolerance:
            _finding(
                findings,
                rule.severity,
                "reciprocity_tolerance_exceeded",
                f"Metrics '{rule.left}' and '{rule.right}' differ by "
                f"{relative_error:.3%}; limit is {rule.relative_tolerance:.3%}.",
                "Check coil orientation, mesh resolution, domains, and evaluation definitions.",
                metric=f"{rule.left}:{rule.right}",
                observed=relative_error,
            )

    diagnostics = metadata.get("solver_diagnostics")
    if isinstance(diagnostics, Mapping):
        _diagnostic_findings(findings, diagnostics, active_policy)
    formula_errors = metadata.get("formula_errors")
    if isinstance(formula_errors, Mapping) and formula_errors:
        _finding(
            findings,
            "warning",
            "computed_output_errors",
            f"{len(formula_errors)} computed output formula(s) could not be evaluated.",
            "Open Formula errors and correct the missing symbol or expression.",
        )

    status = (
        "rejected"
        if any(item.level == "error" for item in findings)
        else "warning"
        if findings
        else "valid"
    )
    return ScientificValidationReport(
        status=status,
        checked_metrics=tuple(sorted(finite_metrics)),
        findings=tuple(findings),
    )


def _parse_bound(
    value: Any,
    index: int,
    metric_units: Mapping[str, str | None],
) -> MetricBound:
    label = f"validation.bounds[{index}]"
    if not isinstance(value, Mapping):
        raise ValueError(f"Model contract '{label}' must be an object")
    metric = _metric_name(value.get("metric"), f"{label}.metric")
    minimum = _optional_finite_number(
        value.get("min", value.get("minimum")), f"{label}.min"
    )
    maximum = _optional_finite_number(
        value.get("max", value.get("maximum")), f"{label}.max"
    )
    if minimum is None and maximum is None:
        raise ValueError(f"Model contract '{label}' requires min or max")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"Model contract '{label}.min' cannot exceed max")
    unit = value.get("unit")
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise ValueError(f"Model contract '{label}.unit' must be a non-empty string")
    unit = unit.strip() if isinstance(unit, str) else None
    parsed_unit = parse_quantity(f"1[{unit}]") if unit else None
    if unit and parsed_unit is None:
        raise ValueError(f"Model contract '{label}.unit' is not a supported unit")
    declared_unit = metric_units.get(metric)
    parsed_declared_unit = (
        parse_quantity(f"1[{declared_unit}]") if declared_unit else None
    )
    if (
        parsed_declared_unit is not None
        and parsed_unit is not None
        and parsed_declared_unit.unit != parsed_unit.unit
    ):
        raise ValueError(
            f"Model contract '{label}.unit' must match output unit '{declared_unit}'"
        )
    severity = _finding_level(value.get("severity", "error"), f"{label}.severity")
    exclusive_minimum = _boolean(value.get("exclusive_min", False), f"{label}.exclusive_min")
    exclusive_maximum = _boolean(value.get("exclusive_max", False), f"{label}.exclusive_max")
    if minimum == maximum and (exclusive_minimum or exclusive_maximum):
        raise ValueError(f"Model contract '{label}' defines an empty range")
    return MetricBound(
        metric,
        minimum,
        maximum,
        unit,
        severity,
        exclusive_minimum,
        exclusive_maximum,
    )


def _parse_reciprocity(
    value: Any,
    index: int,
    metric_units: Mapping[str, str | None],
) -> ReciprocityRule:
    label = f"validation.reciprocity[{index}]"
    if not isinstance(value, Mapping):
        raise ValueError(f"Model contract '{label}' must be an object")
    left = _metric_name(value.get("left"), f"{label}.left")
    right = _metric_name(value.get("right"), f"{label}.right")
    if left == right:
        raise ValueError(f"Model contract '{label}' must use two different metrics")
    left_unit = metric_units.get(left)
    right_unit = metric_units.get(right)
    left_quantity = parse_quantity(f"1[{left_unit}]") if left_unit else None
    right_quantity = parse_quantity(f"1[{right_unit}]") if right_unit else None
    if (
        left_quantity is not None
        and right_quantity is not None
        and left_quantity.unit != right_quantity.unit
    ):
        raise ValueError(
            f"Model contract '{label}' metrics must use the same output unit"
        )
    tolerance = _optional_finite_number(
        value.get("relative_tolerance"), f"{label}.relative_tolerance"
    )
    if tolerance is None or tolerance < 0 or tolerance > 1:
        raise ValueError(
            f"Model contract '{label}.relative_tolerance' must be between 0 and 1"
        )
    severity = _finding_level(value.get("severity", "error"), f"{label}.severity")
    return ReciprocityRule(left, right, tolerance, severity)


def _diagnostic_findings(
    findings: list[ValidationFinding],
    diagnostics: Mapping[str, Any],
    policy: ValidationPolicy,
) -> None:
    errors = _messages(diagnostics.get("errors"))
    if errors:
        _finding(
            findings,
            "error",
            "solver_errors_detected",
            f"The solver log contains {len(errors)} error indicator(s): {errors[0]}",
            "Review the solver log and resolve the reported numerical failure.",
        )
    convergence = _messages(diagnostics.get("convergence_issues"))
    if convergence and policy.convergence_issues != "ignore":
        _finding(
            findings,
            policy.convergence_issues,
            "convergence_issues_detected",
            f"The solver log contains {len(convergence)} convergence issue(s): "
            f"{convergence[0]}",
            "Review solver tolerances, initial values, mesh, and material definitions.",
        )
    warnings = _messages(diagnostics.get("warnings"))
    if warnings and policy.solver_warnings != "ignore":
        _finding(
            findings,
            policy.solver_warnings,
            "solver_warnings_detected",
            f"The solver log contains {len(warnings)} warning(s): {warnings[0]}",
            "Review the complete solver log before accepting the result.",
        )


def _bound_description(rule: MetricBound) -> str:
    unit = f" {rule.unit}" if rule.unit else ""
    if rule.minimum is not None and rule.maximum is not None:
        left = ">" if rule.exclusive_minimum else ">="
        right = "<" if rule.exclusive_maximum else "<="
        return f"{left} {rule.minimum:g}{unit} and {right} {rule.maximum:g}{unit}"
    if rule.minimum is not None:
        operator = ">" if rule.exclusive_minimum else ">="
        return f"{operator} {rule.minimum:g}{unit}"
    operator = "<" if rule.exclusive_maximum else "<="
    return f"{operator} {rule.maximum:g}{unit}"


def _messages(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item)[:300] for item in value if str(item).strip()][:20]


def _list(data: Mapping[str, Any], name: str) -> list[Any]:
    value = data.get(name, [])
    if not isinstance(value, list):
        raise ValueError(f"Model contract 'validation.{name}' must be a list")
    return value


def _metric_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not METRIC_NAME.fullmatch(value.strip()):
        raise ValueError(f"Model contract '{label}' is not a valid metric name")
    return value.strip()


def _finding_level(value: Any, label: str) -> str:
    level = str(value).strip().lower()
    if level not in FINDING_LEVELS:
        raise ValueError(f"Model contract '{label}' must be warning or error")
    return level


def _diagnostic_level(value: Any, label: str) -> str:
    level = str(value).strip().lower()
    if level not in DIAGNOSTIC_LEVELS:
        raise ValueError(f"Model contract '{label}' must be ignore, warning, or error")
    return level


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"Model contract '{label}' must be true or false")
    return value


def _optional_finite_number(value: Any, label: str) -> float | None:
    if value is None:
        return None
    parsed = _finite_number(value)
    if parsed is None:
        raise ValueError(f"Model contract '{label}' must be a finite number")
    return parsed


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _finding(
    findings: list[ValidationFinding],
    level: str,
    code: str,
    message: str,
    action: str,
    *,
    metric: str | None = None,
    observed: float | str | None = None,
) -> None:
    findings.append(
        ValidationFinding(level, code, message, action, metric, observed)
    )
