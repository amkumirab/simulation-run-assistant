"""Source-amplitude envelopes for sampled, linear WPT equivalent circuits."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable

from simulation_assistant.design_campaigns import (
    DesignCampaignReport, build_design_campaign,
)
from simulation_assistant.preflight import build_run_signature
from simulation_assistant.types import Job
from simulation_assistant.wpt_circuit import (
    CircuitLimits, CircuitOperatingPoint, SeriesSeriesControls, SeriesSeriesSettings,
    TwoPortMetricMap, extract_two_port, solve_with_controls, tune_series_series,
)


@dataclass(frozen=True)
class EnvelopeLimits:
    max_source_rms_v: float

    def __post_init__(self) -> None:
        value = self.max_source_rms_v
        try:
            valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                     and math.isfinite(value) and value > 0)
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("Maximum source voltage must be positive and finite (V RMS)")


@dataclass(frozen=True)
class EnvelopeScenario:
    design: str
    scenario: str
    job_id: int | None
    run_signature: str
    validation_status: str
    parameters: dict[str, Any]
    status: str
    message: str
    required_source_rms_v: float | None = None
    maximum_source_rms_v: float | None = None
    maximum_load_power_w: float | None = None
    limiting_constraints: tuple[str, ...] = ()
    source_ceilings_rms_v: dict[str, float] | None = None
    operating_point: CircuitOperatingPoint | None = None
    power_retention: float | None = None
    minimum_retention_met: bool | None = None
    checks: dict[str, bool] | None = None
    two_port: dict[str, float] | None = None


@dataclass(frozen=True)
class DesignEnvelope:
    name: str
    nominal_job_id: int | None
    status: str
    evaluated_count: int
    required_count: int
    controls: SeriesSeriesControls | None
    worst_case_maximum_load_power_w: float | None
    worst_scenario: str | None


@dataclass(frozen=True)
class OperatingEnvelope:
    settings: SeriesSeriesSettings
    circuit_limits: CircuitLimits
    mapping: TwoPortMetricMap
    limits: EnvelopeLimits
    designs: tuple[DesignEnvelope, ...]
    rows: tuple[EnvelopeScenario, ...]


def analyze_operating_envelope(
    campaign: DesignCampaignReport, jobs: Iterable[Job], limits: EnvelopeLimits,
) -> OperatingEnvelope:
    """Recheck current evidence, then vary source voltage only for each geometry.

    Invalid configuration raises ValueError. Invalid or missing scenario evidence
    yields an unavailable row. A complete summary requires every named sample.
    """
    context, formulas = campaign.plan.campaign.run_context, campaign.plan.campaign.output_formulas
    matching = [item for item in jobs if item.adapter == "comsol"
                and item.run_context == context and item.output_formulas == formulas
                and item.run_signature == build_run_signature("comsol", item.parameters, formulas, context)]
    plan = build_design_campaign(campaign.plan.designs, campaign.plan.scenarios,
                                run_context=context, output_formulas=formulas, existing_jobs=matching)
    jobs_by_id = {item.id: item for item in matching}
    rows, designs = [], []
    for index, design in enumerate(plan.designs):
        states = plan.states_for_design(index)
        controls = None
        nominal_message = "Accepted nominal result is unavailable"
        if states[0].status in {"valid", "warning"}:
            try:
                nominal = extract_two_port(jobs_by_id[states[0].job_id], campaign.mapping)
                controls, nominal_point = tune_series_series(nominal, campaign.settings)
                _validate_point(nominal_point, campaign.limits.max_energy_balance_relative)
            except (ValueError, OverflowError, ZeroDivisionError) as exc:
                controls = None
                nominal_message = f"Nominal circuit unavailable: {exc}"
        design_rows = []
        for scenario, state in zip(plan.scenarios, states):
            row = EnvelopeScenario(design.name, scenario.name, state.job_id,
                                   state.signature, state.validation_status, dict(state.parameters),
                                   "unavailable", nominal_message if controls is None else
                                   f"Matching accepted scenario evidence is unavailable (state: {state.status})")
            if controls is not None and state.status in {"valid", "warning"}:
                try:
                    two_port = extract_two_port(jobs_by_id[state.job_id], campaign.mapping)
                    row = _evaluate(row, two_port, controls, campaign, limits)
                except (ValueError, OverflowError, ZeroDivisionError) as exc:
                    row = replace(row, message=str(exc))
            design_rows.append(row)
        available = [row for row in design_rows if row.status != "unavailable"]
        complete = len(available) == len(design_rows)
        worst = min(available, key=lambda row: row.maximum_load_power_w) if complete else None
        status = ("incomplete" if not complete else
                  "derated" if any(row.status == "derated" for row in available) else "target_met")
        designs.append(DesignEnvelope(design.name, states[0].job_id, status, len(available), len(design_rows),
                                      controls, worst.maximum_load_power_w if worst else None,
                                      worst.scenario if worst else None))
        rows.extend(design_rows)
    return OperatingEnvelope(campaign.settings, campaign.limits, campaign.mapping, limits, tuple(designs), tuple(rows))


def _evaluate(row, two_port, controls, campaign, envelope_limits):
    unit = solve_with_controls(two_port, replace(controls, source_rms_v=1.0))
    _validate_point(unit, campaign.limits.max_energy_balance_relative)
    if unit.load_ac_w <= 0:
        raise ValueError("No positive modeled load power at this scenario")
    circuit_limits = campaign.limits
    ceilings = {"source_voltage": envelope_limits.max_source_rms_v}
    for name, stress, limit in (
        ("primary_current", unit.primary_current_rms_a, circuit_limits.max_coil_current_rms_a),
        ("secondary_current", unit.secondary_current_rms_a, circuit_limits.max_coil_current_rms_a),
        ("primary_capacitor", unit.primary_capacitor_rms_v, circuit_limits.max_capacitor_voltage_rms_v),
        ("secondary_capacitor", unit.secondary_capacitor_rms_v, circuit_limits.max_capacitor_voltage_rms_v),
    ):
        if stress <= 0:
            raise ValueError("A positive-transfer scenario requires positive circuit stresses")
        ceiling = limit / stress
        if not math.isfinite(ceiling):
            raise ValueError("Component source ceiling is outside the finite numerical range")
        ceilings[name] = ceiling
    maximum_voltage = min(ceilings.values())
    required_voltage = math.sqrt(campaign.settings.target_load_power_w / unit.load_ac_w)
    if not math.isfinite(required_voltage) or required_voltage <= 0:
        raise ValueError("Target voltage is outside the finite numerical range")
    ceiling_point = solve_with_controls(two_port, replace(controls, source_rms_v=maximum_voltage))
    point = solve_with_controls(two_port, replace(controls, source_rms_v=min(required_voltage, maximum_voltage)))
    for candidate in (ceiling_point, point):
        _validate_point(candidate, circuit_limits.max_energy_balance_relative)
        if not all(_stress_checks(candidate, circuit_limits, envelope_limits).values()):
            raise ValueError("Calculated operating point exceeds a configured RMS limit")
    retention = point.load_ac_w / campaign.settings.target_load_power_w
    target_met = retention >= 1.0 or math.isclose(retention, 1.0, rel_tol=1e-10)
    binding = tuple(name for name, ceiling in ceilings.items()
                    if math.isclose(ceiling, maximum_voltage, rel_tol=1e-10, abs_tol=0))
    return replace(row, status="target_met" if target_met else "derated",
                   message="Target AC load power is achievable" if target_met else
                           "Reduce source amplitude; target AC load power is not achievable within these limits",
                   required_source_rms_v=required_voltage, maximum_source_rms_v=maximum_voltage,
                   maximum_load_power_w=ceiling_point.load_ac_w, limiting_constraints=binding,
                   source_ceilings_rms_v=ceilings, operating_point=point, power_retention=retention,
                   minimum_retention_met=(retention >= circuit_limits.min_load_power_retention
                       or math.isclose(retention, circuit_limits.min_load_power_retention, rel_tol=1e-10)),
                   checks=_stress_checks(point, circuit_limits, envelope_limits), two_port=asdict(two_port))


def _stress_checks(point, limits, envelope):
    def within(value, ceiling):
        return value <= ceiling or math.isclose(value, ceiling, rel_tol=1e-10)
    return {
        "source_voltage": within(point.source_rms_v, envelope.max_source_rms_v),
        "primary_current": within(point.primary_current_rms_a, limits.max_coil_current_rms_a),
        "secondary_current": within(point.secondary_current_rms_a, limits.max_coil_current_rms_a),
        "primary_capacitor": within(point.primary_capacitor_rms_v, limits.max_capacitor_voltage_rms_v),
        "secondary_capacitor": within(point.secondary_capacitor_rms_v, limits.max_capacitor_voltage_rms_v),
        "energy_balance": point.energy_balance_relative <= limits.max_energy_balance_relative,
    }


def _validate_point(point, tolerance):
    for value in asdict(point).values():
        numbers = value if isinstance(value, tuple) else (value,)
        if not all(math.isfinite(number) for number in numbers):
            raise ValueError("Non-finite circuit operating point")
    if point.input_ac_w <= 0 or point.load_ac_w < 0 or not 0 <= point.ac_efficiency <= 1 + 1e-10:
        raise ValueError("Invalid circuit power or efficiency")
    if point.energy_balance_relative > tolerance:
        raise ValueError("Circuit energy-balance tolerance exceeded")
