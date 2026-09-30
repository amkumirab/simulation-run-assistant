from __future__ import annotations

import csv
import html
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from simulation_assistant.types import Job, JobStatus


TWO_PORT_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "frequency": ("frequency_Hz", "frequency_hz", "frequency", "freq_Hz", "f0_Hz"),
    "primary_inductance": ("L1_H", "L11_H", "primary_inductance_H"),
    "secondary_inductance": ("L2_H", "L22_H", "secondary_inductance_H"),
    "mutual_inductance_12": ("M12_H", "L12_H", "mutual_inductance_12_H"),
    "mutual_inductance_21": ("M21_H", "L21_H", "mutual_inductance_21_H"),
    "resistance_11": ("R1_ohm", "R11_ohm", "primary_resistance_ohm"),
    "resistance_22": ("R2_ohm", "R22_ohm", "secondary_resistance_ohm"),
    "resistance_12": ("R12_ohm", "transfer_resistance_12_ohm"),
    "resistance_21": ("R21_ohm", "transfer_resistance_21_ohm"),
}


@dataclass(frozen=True)
class TwoPortMetricMap:
    frequency: str
    primary_inductance: str
    secondary_inductance: str
    mutual_inductance_12: str
    mutual_inductance_21: str
    resistance_11: str
    resistance_22: str
    resistance_12: str
    resistance_21: str

    def __post_init__(self) -> None:
        values = tuple(asdict(self).values())
        if any(not value.strip() for value in values):
            raise ValueError("Every two-port metric mapping must be selected")
        if len(set(values)) != len(values):
            raise ValueError("Two-port metric mappings must be unique")


@dataclass(frozen=True)
class SeriesSeriesSettings:
    target_load_power_w: float = 3700.0
    capacitor_esr_each_ohm: float = 0.005
    load_min_ohm: float = 0.02
    load_max_ohm: float = 20.0
    load_samples: int = 500

    def __post_init__(self) -> None:
        positive = {
            "target load power": self.target_load_power_w,
            "minimum load": self.load_min_ohm,
            "maximum load": self.load_max_ohm,
        }
        for label, value in positive.items():
            if not _positive_finite(value):
                raise ValueError(f"{label.title()} must be positive and finite")
        if self.load_min_ohm >= self.load_max_ohm:
            raise ValueError("Maximum load must be greater than minimum load")
        if (
            isinstance(self.capacitor_esr_each_ohm, bool)
            or not isinstance(self.capacitor_esr_each_ohm, (int, float))
            or not math.isfinite(float(self.capacitor_esr_each_ohm))
            or self.capacitor_esr_each_ohm < 0
        ):
            raise ValueError("Capacitor ESR must be non-negative and finite")
        if (
            isinstance(self.load_samples, bool)
            or not isinstance(self.load_samples, int)
            or self.load_samples < 20
        ):
            raise ValueError("Load search requires at least 20 samples")


@dataclass(frozen=True)
class CircuitLimits:
    max_coil_current_rms_a: float = 100.0
    max_capacitor_voltage_rms_v: float = 1200.0
    min_load_power_retention: float = 0.8
    max_energy_balance_relative: float = 1e-8

    def __post_init__(self) -> None:
        for label, value in (
            ("Maximum coil current", self.max_coil_current_rms_a),
            ("Maximum capacitor voltage", self.max_capacitor_voltage_rms_v),
        ):
            if not _positive_finite(value):
                raise ValueError(f"{label} must be positive and finite")
        if (
            isinstance(self.min_load_power_retention, bool)
            or not isinstance(self.min_load_power_retention, (int, float))
            or not math.isfinite(float(self.min_load_power_retention))
            or not 0 <= self.min_load_power_retention <= 1
        ):
            raise ValueError("Minimum load-power retention must be between zero and one")
        if (
            isinstance(self.max_energy_balance_relative, bool)
            or not isinstance(self.max_energy_balance_relative, (int, float))
            or not math.isfinite(float(self.max_energy_balance_relative))
            or self.max_energy_balance_relative < 0
        ):
            raise ValueError("Energy-balance tolerance must be non-negative and finite")


@dataclass(frozen=True)
class TwoPortData:
    frequency_hz: float
    primary_inductance_h: float
    secondary_inductance_h: float
    mutual_inductance_12_h: float
    mutual_inductance_21_h: float
    resistance_11_ohm: float
    resistance_22_ohm: float
    resistance_12_ohm: float
    resistance_21_ohm: float

    @property
    def reciprocity_relative(self) -> float:
        scale = max(
            abs(self.mutual_inductance_12_h),
            abs(self.mutual_inductance_21_h),
            1e-30,
        )
        return (
            abs(self.mutual_inductance_12_h - self.mutual_inductance_21_h)
            / scale
        )


@dataclass(frozen=True)
class SeriesSeriesControls:
    frequency_hz: float
    primary_capacitance_f: float
    secondary_capacitance_f: float
    load_ohm: float
    source_rms_v: float
    capacitor_esr_each_ohm: float


@dataclass(frozen=True)
class CircuitOperatingPoint:
    primary_current_rms_a: float
    secondary_current_rms_a: float
    primary_current_complex_a: tuple[float, float]
    secondary_current_complex_a: tuple[float, float]
    source_rms_v: float
    load_rms_v: float
    primary_capacitor_rms_v: float
    secondary_capacitor_rms_v: float
    input_ac_w: float
    load_ac_w: float
    modeled_fem_loss_w: float
    capacitor_esr_loss_w: float
    ac_efficiency: float
    energy_balance_relative: float
    input_impedance_ohm: tuple[float, float]

    @property
    def max_coil_current_rms_a(self) -> float:
        return max(self.primary_current_rms_a, self.secondary_current_rms_a)

    @property
    def max_capacitor_voltage_rms_v(self) -> float:
        return max(
            self.primary_capacitor_rms_v,
            self.secondary_capacitor_rms_v,
        )


@dataclass(frozen=True)
class CircuitScenarioResult:
    job_id: int
    parameters: dict[str, Any]
    status: str
    message: str
    validation_status: str
    operating_point: CircuitOperatingPoint | None
    load_power_retention: float | None
    checks: dict[str, bool]


@dataclass(frozen=True)
class CircuitStudy:
    nominal_job_id: int
    metric_mapping: TwoPortMetricMap
    settings: SeriesSeriesSettings
    limits: CircuitLimits
    controls: SeriesSeriesControls
    scenarios: tuple[CircuitScenarioResult, ...]

    @property
    def passed_count(self) -> int:
        return sum(item.status == "passed" for item in self.scenarios)

    @property
    def failed_count(self) -> int:
        return sum(item.status == "failed" for item in self.scenarios)

    @property
    def ineligible_count(self) -> int:
        return sum(item.status == "ineligible" for item in self.scenarios)

    @property
    def all_passed(self) -> bool:
        return bool(self.scenarios) and self.passed_count == len(self.scenarios)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def suggest_two_port_metric_names(
    metric_names: Iterable[str],
) -> dict[str, str]:
    available = {str(name).casefold(): str(name) for name in metric_names}
    suggestions: dict[str, str] = {}
    used: set[str] = set()
    for field, aliases in TWO_PORT_METRIC_ALIASES.items():
        match = next(
            (
                available[alias.casefold()]
                for alias in aliases
                if alias.casefold() in available
                and available[alias.casefold()] not in used
            ),
            None,
        )
        if match is not None:
            suggestions[field] = match
            used.add(match)
    return suggestions


def extract_two_port(job: Job, mapping: TwoPortMetricMap) -> TwoPortData:
    if job.status != JobStatus.SUCCEEDED:
        raise ValueError(f"Job #{job.id} did not complete successfully")
    validation = _validation_status(job)
    if validation not in {"valid", "warning"}:
        raise ValueError(f"Job #{job.id} does not have an accepted scientific result")
    metrics = _job_metrics(job)
    values = {
        field: _required_metric(metrics, metric_name, job.id)
        for field, metric_name in asdict(mapping).items()
    }
    two_port = TwoPortData(
        frequency_hz=values["frequency"],
        primary_inductance_h=values["primary_inductance"],
        secondary_inductance_h=values["secondary_inductance"],
        mutual_inductance_12_h=values["mutual_inductance_12"],
        mutual_inductance_21_h=values["mutual_inductance_21"],
        resistance_11_ohm=values["resistance_11"],
        resistance_22_ohm=values["resistance_22"],
        resistance_12_ohm=values["resistance_12"],
        resistance_21_ohm=values["resistance_21"],
    )
    _validate_two_port(two_port)
    return two_port


def tune_series_series(
    two_port: TwoPortData,
    settings: SeriesSeriesSettings,
) -> tuple[SeriesSeriesControls, CircuitOperatingPoint]:
    _validate_two_port(two_port)
    omega = 2.0 * math.pi * two_port.frequency_hz
    primary_capacitance = 1.0 / (
        omega * omega * two_port.primary_inductance_h
    )
    secondary_capacitance = 1.0 / (
        omega * omega * two_port.secondary_inductance_h
    )
    loads = _logspace(
        settings.load_min_ohm,
        settings.load_max_ohm,
        settings.load_samples,
    )
    trials = [
        solve_series_series(
            two_port,
            primary_capacitance,
            secondary_capacitance,
            load,
            source_rms_v=1.0,
            capacitor_esr_each_ohm=settings.capacitor_esr_each_ohm,
        )
        for load in loads
    ]
    best_index = max(range(len(trials)), key=lambda index: trials[index].ac_efficiency)
    best_load = loads[best_index]
    reference = trials[best_index]
    if reference.load_ac_w <= 0:
        raise ValueError("The two-port cannot deliver positive load power")
    source = math.sqrt(settings.target_load_power_w / reference.load_ac_w)
    controls = SeriesSeriesControls(
        frequency_hz=two_port.frequency_hz,
        primary_capacitance_f=primary_capacitance,
        secondary_capacitance_f=secondary_capacitance,
        load_ohm=best_load,
        source_rms_v=source,
        capacitor_esr_each_ohm=settings.capacitor_esr_each_ohm,
    )
    operating_point = solve_with_controls(two_port, controls)
    return controls, operating_point


def solve_with_controls(
    two_port: TwoPortData,
    controls: SeriesSeriesControls,
) -> CircuitOperatingPoint:
    _validate_two_port(two_port)
    if not _positive_finite(controls.frequency_hz):
        raise ValueError("Control frequency must be positive and finite")
    frequency_difference = abs(two_port.frequency_hz - controls.frequency_hz)
    if frequency_difference > controls.frequency_hz * 1e-9:
        raise ValueError(
            "The two-port frequency does not match the fixed nominal frequency"
        )
    return solve_series_series(
        two_port,
        controls.primary_capacitance_f,
        controls.secondary_capacitance_f,
        controls.load_ohm,
        source_rms_v=controls.source_rms_v,
        capacitor_esr_each_ohm=controls.capacitor_esr_each_ohm,
        operating_frequency_hz=controls.frequency_hz,
    )


def solve_series_series(
    two_port: TwoPortData,
    primary_capacitance_f: float,
    secondary_capacitance_f: float,
    load_ohm: float,
    *,
    source_rms_v: float = 1.0,
    capacitor_esr_each_ohm: float = 0.0,
    operating_frequency_hz: float | None = None,
) -> CircuitOperatingPoint:
    _validate_two_port(two_port)
    for label, value in (
        ("Primary capacitance", primary_capacitance_f),
        ("Secondary capacitance", secondary_capacitance_f),
        ("Load", load_ohm),
        ("Source voltage", source_rms_v),
    ):
        if not _positive_finite(value):
            raise ValueError(f"{label} must be positive and finite")
    if (
        isinstance(capacitor_esr_each_ohm, bool)
        or not isinstance(capacitor_esr_each_ohm, (int, float))
        or not math.isfinite(float(capacitor_esr_each_ohm))
        or capacitor_esr_each_ohm < 0
    ):
        raise ValueError("Capacitor ESR must be non-negative and finite")

    frequency_hz = (
        two_port.frequency_hz
        if operating_frequency_hz is None
        else operating_frequency_hz
    )
    if not _positive_finite(frequency_hz):
        raise ValueError("Operating frequency must be positive and finite")
    omega = 2.0 * math.pi * frequency_hz
    z11 = complex(
        two_port.resistance_11_ohm,
        omega * two_port.primary_inductance_h,
    )
    z22 = complex(
        two_port.resistance_22_ohm,
        omega * two_port.secondary_inductance_h,
    )
    z12 = complex(
        two_port.resistance_12_ohm,
        omega * two_port.mutual_inductance_12_h,
    )
    z21 = complex(
        two_port.resistance_21_ohm,
        omega * two_port.mutual_inductance_21_h,
    )
    a = z11 + capacitor_esr_each_ohm - 1j / (
        omega * primary_capacitance_f
    )
    d = z22 + capacitor_esr_each_ohm + load_ohm - 1j / (
        omega * secondary_capacitance_f
    )
    determinant = a * d - z12 * z21
    if abs(determinant) <= 1e-24:
        raise ValueError("The compensated circuit matrix is singular")
    primary_current = source_rms_v * d / determinant
    secondary_current = -source_rms_v * z21 / determinant
    input_power = float((source_rms_v * primary_current.conjugate()).real)
    load_power = float(abs(secondary_current) ** 2 * load_ohm)
    voltage_1 = z11 * primary_current + z12 * secondary_current
    voltage_2 = z21 * primary_current + z22 * secondary_current
    fem_loss = float(
        (primary_current.conjugate() * voltage_1).real
        + (secondary_current.conjugate() * voltage_2).real
    )
    capacitor_loss = float(
        capacitor_esr_each_ohm
        * (abs(primary_current) ** 2 + abs(secondary_current) ** 2)
    )
    if input_power <= 0 or fem_loss < -1e-8:
        raise ValueError("The operating point is non-passive or reverses source power")
    energy_balance = abs(
        input_power - load_power - fem_loss - capacitor_loss
    ) / input_power
    input_impedance = source_rms_v / primary_current
    return CircuitOperatingPoint(
        primary_current_rms_a=float(abs(primary_current)),
        secondary_current_rms_a=float(abs(secondary_current)),
        primary_current_complex_a=(
            float(primary_current.real),
            float(primary_current.imag),
        ),
        secondary_current_complex_a=(
            float(secondary_current.real),
            float(secondary_current.imag),
        ),
        source_rms_v=float(source_rms_v),
        load_rms_v=float(abs(secondary_current) * load_ohm),
        primary_capacitor_rms_v=float(
            abs(primary_current) / (omega * primary_capacitance_f)
        ),
        secondary_capacitor_rms_v=float(
            abs(secondary_current) / (omega * secondary_capacitance_f)
        ),
        input_ac_w=input_power,
        load_ac_w=load_power,
        modeled_fem_loss_w=fem_loss,
        capacitor_esr_loss_w=capacitor_loss,
        ac_efficiency=load_power / input_power,
        energy_balance_relative=energy_balance,
        input_impedance_ohm=(
            float(input_impedance.real),
            float(input_impedance.imag),
        ),
    )


def analyze_fixed_control_scenarios(
    nominal_job: Job,
    scenario_jobs: Iterable[Job],
    mapping: TwoPortMetricMap,
    settings: SeriesSeriesSettings | None = None,
    limits: CircuitLimits | None = None,
) -> CircuitStudy:
    prepared_settings = settings or SeriesSeriesSettings()
    prepared_limits = limits or CircuitLimits()
    nominal_two_port = extract_two_port(nominal_job, mapping)
    controls, nominal_point = tune_series_series(
        nominal_two_port,
        prepared_settings,
    )
    jobs = [nominal_job]
    jobs.extend(job for job in scenario_jobs if job.id != nominal_job.id)
    unique_jobs = list({job.id: job for job in jobs}.values())
    scenarios: list[CircuitScenarioResult] = []
    for job in unique_jobs:
        validation = _validation_status(job)
        try:
            two_port = extract_two_port(job, mapping)
            point = nominal_point if job.id == nominal_job.id else solve_with_controls(
                two_port,
                controls,
            )
        except ValueError as exc:
            scenarios.append(
                CircuitScenarioResult(
                    job_id=job.id,
                    parameters=dict(job.parameters),
                    status="ineligible",
                    message=str(exc),
                    validation_status=validation,
                    operating_point=None,
                    load_power_retention=None,
                    checks={},
                )
            )
            continue
        retention = point.load_ac_w / nominal_point.load_ac_w
        checks = {
            "scientific_result": validation in {"valid", "warning"},
            "load_power_retention": (
                retention >= prepared_limits.min_load_power_retention
            ),
            "coil_current": (
                point.max_coil_current_rms_a
                <= prepared_limits.max_coil_current_rms_a
            ),
            "capacitor_voltage": (
                point.max_capacitor_voltage_rms_v
                <= prepared_limits.max_capacitor_voltage_rms_v
            ),
            "energy_balance": (
                point.energy_balance_relative
                <= prepared_limits.max_energy_balance_relative
            ),
        }
        failed_checks = [name for name, passed in checks.items() if not passed]
        scenarios.append(
            CircuitScenarioResult(
                job_id=job.id,
                parameters=dict(job.parameters),
                status="passed" if not failed_checks else "failed",
                message=(
                    "Every operating-point check passed."
                    if not failed_checks
                    else "Failed check(s): " + ", ".join(failed_checks)
                ),
                validation_status=validation,
                operating_point=point,
                load_power_retention=retention,
                checks=checks,
            )
        )
    return CircuitStudy(
        nominal_job_id=nominal_job.id,
        metric_mapping=mapping,
        settings=prepared_settings,
        limits=prepared_limits,
        controls=controls,
        scenarios=tuple(scenarios),
    )


def write_circuit_study_csv(path: str | Path, study: CircuitStudy) -> Path:
    destination = _report_path(path, ".csv")
    fields = [
        "job_id",
        "status",
        "validation_status",
        "fixed_frequency_hz",
        "primary_capacitance_f",
        "secondary_capacitance_f",
        "fixed_load_ohm",
        "fixed_source_rms_v",
        "capacitor_esr_each_ohm",
        "max_coil_current_limit_a",
        "max_capacitor_voltage_limit_v",
        "min_load_power_retention",
        "max_energy_balance_relative",
        "load_power_retention_percent",
        "load_ac_w",
        "input_ac_w",
        "ac_efficiency_percent",
        "primary_current_rms_a",
        "secondary_current_rms_a",
        "max_coil_current_rms_a",
        "primary_capacitor_rms_v",
        "secondary_capacitor_rms_v",
        "max_capacitor_voltage_rms_v",
        "source_rms_v",
        "load_rms_v",
        "energy_balance_relative",
        "check_scientific_result",
        "check_load_power_retention",
        "check_coil_current",
        "check_capacitor_voltage",
        "check_energy_balance",
        "parameters",
        "message",
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for scenario in study.scenarios:
            point = scenario.operating_point
            writer.writerow(
                {
                    "job_id": scenario.job_id,
                    "status": scenario.status,
                    "validation_status": scenario.validation_status,
                    "fixed_frequency_hz": study.controls.frequency_hz,
                    "primary_capacitance_f": study.controls.primary_capacitance_f,
                    "secondary_capacitance_f": study.controls.secondary_capacitance_f,
                    "fixed_load_ohm": study.controls.load_ohm,
                    "fixed_source_rms_v": study.controls.source_rms_v,
                    "capacitor_esr_each_ohm": (
                        study.controls.capacitor_esr_each_ohm
                    ),
                    "max_coil_current_limit_a": (
                        study.limits.max_coil_current_rms_a
                    ),
                    "max_capacitor_voltage_limit_v": (
                        study.limits.max_capacitor_voltage_rms_v
                    ),
                    "min_load_power_retention": (
                        study.limits.min_load_power_retention
                    ),
                    "max_energy_balance_relative": (
                        study.limits.max_energy_balance_relative
                    ),
                    "load_power_retention_percent": (
                        scenario.load_power_retention * 100.0
                        if scenario.load_power_retention is not None
                        else ""
                    ),
                    "load_ac_w": point.load_ac_w if point else "",
                    "input_ac_w": point.input_ac_w if point else "",
                    "ac_efficiency_percent": (
                        point.ac_efficiency * 100.0 if point else ""
                    ),
                    "primary_current_rms_a": (
                        point.primary_current_rms_a if point else ""
                    ),
                    "secondary_current_rms_a": (
                        point.secondary_current_rms_a if point else ""
                    ),
                    "max_coil_current_rms_a": (
                        point.max_coil_current_rms_a if point else ""
                    ),
                    "primary_capacitor_rms_v": (
                        point.primary_capacitor_rms_v if point else ""
                    ),
                    "secondary_capacitor_rms_v": (
                        point.secondary_capacitor_rms_v if point else ""
                    ),
                    "max_capacitor_voltage_rms_v": (
                        point.max_capacitor_voltage_rms_v if point else ""
                    ),
                    "source_rms_v": point.source_rms_v if point else "",
                    "load_rms_v": point.load_rms_v if point else "",
                    "energy_balance_relative": (
                        point.energy_balance_relative if point else ""
                    ),
                    "check_scientific_result": scenario.checks.get(
                        "scientific_result",
                        "",
                    ),
                    "check_load_power_retention": scenario.checks.get(
                        "load_power_retention",
                        "",
                    ),
                    "check_coil_current": scenario.checks.get(
                        "coil_current",
                        "",
                    ),
                    "check_capacitor_voltage": scenario.checks.get(
                        "capacitor_voltage",
                        "",
                    ),
                    "check_energy_balance": scenario.checks.get(
                        "energy_balance",
                        "",
                    ),
                    "parameters": "; ".join(
                        f"{name}={value}"
                        for name, value in sorted(scenario.parameters.items())
                    ),
                    "message": scenario.message,
                }
            )
    return destination.resolve()


def write_circuit_study_html(path: str | Path, study: CircuitStudy) -> Path:
    destination = _report_path(path, ".html")
    rows: list[str] = []
    for scenario in study.scenarios:
        point = scenario.operating_point
        values = (
            f"#{scenario.job_id}",
            scenario.status,
            scenario.validation_status,
            _percent(scenario.load_power_retention),
            _number(point.load_ac_w if point else None),
            _percent(point.ac_efficiency if point else None),
            _number(point.max_coil_current_rms_a if point else None),
            _number(point.max_capacitor_voltage_rms_v if point else None),
            _number(point.energy_balance_relative if point else None),
            ", ".join(
                f"{name}={value}"
                for name, value in sorted(scenario.parameters.items())
            ),
            scenario.message,
        )
        cells = "".join(f"<td>{html.escape(str(value))}</td>" for value in values)
        rows.append(f'<tr data-status="{scenario.status}">{cells}</tr>')
    controls = study.controls
    document = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Series-Series Circuit Study</title>
  <style>
    body {{ font: 14px system-ui, sans-serif; margin: 32px; color: #172630; }}
    p {{ color: #667681; }}
    .summary {{ display: flex; gap: 10px; margin: 16px 0; flex-wrap: wrap; }}
    .summary span {{ background: #f3f6f8; border-radius: 8px; padding: 8px 12px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
    th, td {{ border: 1px solid #dce4e8; padding: 8px; text-align: left; }}
    th {{ background: #16324a; color: white; position: sticky; top: 0; }}
    tr[data-status="passed"] {{ background: #e5f6f3; }}
    tr[data-status="failed"], tr[data-status="ineligible"] {{ background: #feeceb; }}
  </style>
</head>
<body>
  <h1>Series-Series Circuit Study</h1>
  <p>Fixed nominal compensation and source controls evaluated across accepted FEM jobs.</p>
  <div class="summary">
    <span>Nominal Job: #{study.nominal_job_id}</span>
    <span>Target load: {study.settings.target_load_power_w:.6g} W</span>
    <span>Load: {controls.load_ohm:.6g} ohm</span>
    <span>Source: {controls.source_rms_v:.6g} V RMS</span>
    <span>C1: {controls.primary_capacitance_f * 1e9:.6g} nF</span>
    <span>C2: {controls.secondary_capacitance_f * 1e9:.6g} nF</span>
    <span>Current limit: {study.limits.max_coil_current_rms_a:.6g} A RMS</span>
    <span>Capacitor limit: {study.limits.max_capacitor_voltage_rms_v:.6g} V RMS</span>
    <span>Power retention: {study.limits.min_load_power_retention * 100.0:.6g}% minimum</span>
    <span>Energy balance: {study.limits.max_energy_balance_relative:.6g} maximum</span>
    <span>{study.passed_count} passed</span>
    <span>{study.failed_count} failed</span>
    <span>{study.ineligible_count} ineligible</span>
  </div>
  <table>
    <thead><tr><th>Job</th><th>Status</th><th>Validation</th><th>Power retention</th>
    <th>Load power (W)</th><th>Efficiency</th><th>Max current (A)</th>
    <th>Max capacitor voltage (V)</th><th>Energy balance</th><th>Parameters</th>
    <th>Message</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <p>This is a sinusoidal AC equivalent. It does not include inverter switching,
  rectifier, DC/DC, battery, thermal, or hardware-calibration losses.</p>
</body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination.resolve()


def _validate_two_port(two_port: TwoPortData) -> None:
    values = asdict(two_port)
    for name, value in values.items():
        if not _finite_number(value):
            raise ValueError(f"Two-port value '{name}' must be finite")
    if two_port.frequency_hz <= 0:
        raise ValueError("Two-port frequency must be positive")
    if two_port.primary_inductance_h <= 0 or two_port.secondary_inductance_h <= 0:
        raise ValueError("Self-inductances must be positive")
    if two_port.resistance_11_ohm <= 0 or two_port.resistance_22_ohm <= 0:
        raise ValueError("Self-resistances must be positive")
    mutual_limit = math.sqrt(
        two_port.primary_inductance_h * two_port.secondary_inductance_h
    )
    if (
        abs(two_port.mutual_inductance_12_h) > mutual_limit * (1.0 + 1e-9)
        or abs(two_port.mutual_inductance_21_h) > mutual_limit * (1.0 + 1e-9)
    ):
        raise ValueError("Mutual inductance implies a coupling magnitude above one")
    omega = 2.0 * math.pi * two_port.frequency_hz
    hermitian_cross = complex(
        0.5 * (two_port.resistance_12_ohm + two_port.resistance_21_ohm),
        0.5
        * omega
        * (
            two_port.mutual_inductance_12_h
            - two_port.mutual_inductance_21_h
        ),
    )
    determinant = (
        two_port.resistance_11_ohm * two_port.resistance_22_ohm
        - abs(hermitian_cross) ** 2
    )
    scale = max(
        two_port.resistance_11_ohm * two_port.resistance_22_ohm,
        1e-30,
    )
    if determinant < -1e-9 * scale:
        raise ValueError("The real impedance matrix is not passive")


def _job_metrics(job: Job) -> Mapping[str, Any]:
    if not isinstance(job.result, dict):
        return {}
    metrics = job.result.get("metrics", {})
    return metrics if isinstance(metrics, dict) else {}


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


def _required_metric(metrics: Mapping[str, Any], name: str, job_id: int) -> float:
    value = metrics.get(name)
    if not _finite_number(value):
        raise ValueError(f"Job #{job_id} is missing finite metric '{name}'")
    return float(value)


def _logspace(start: float, stop: float, count: int) -> tuple[float, ...]:
    first = math.log(start)
    step = (math.log(stop) - first) / (count - 1)
    return tuple(math.exp(first + index * step) for index in range(count))


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _positive_finite(value: Any) -> bool:
    return _finite_number(value) and float(value) > 0


def _number(value: float | None) -> str:
    return "" if value is None else f"{value:.9g}"


def _percent(value: float | None) -> str:
    return "" if value is None else f"{value * 100.0:.6g}%"


def _report_path(path: str | Path, suffix: str) -> Path:
    destination = Path(path)
    if destination.suffix.casefold() != suffix:
        raise ValueError(f"Circuit study report must use the {suffix} extension")
    return destination
