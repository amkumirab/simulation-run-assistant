"""Named WPT scenarios evaluated independently for each nominal design."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from simulation_assistant.campaigns import CampaignPlan, CampaignState, build_campaign_plan
from simulation_assistant.quantities import parse_quantity
from simulation_assistant.types import Job, JobStatus
from simulation_assistant.wpt_circuit import (
    CircuitLimits, CircuitStudy, SeriesSeriesSettings, TwoPortMetricMap,
    analyze_fixed_control_scenarios,
)

SCENARIO_DIMENSIONS = {"gap": "length", "xoff": "length", "yoff": "length", "tilt": "angle"}
MAX_CAMPAIGN_STATES = 500


@dataclass(frozen=True)
class DesignCandidate:
    name: str
    source_job_id: int
    parameters: dict[str, Any]


@dataclass(frozen=True)
class Scenario:
    name: str
    overrides: dict[str, str]


@dataclass(frozen=True)
class DesignCampaignPlan:
    designs: tuple[DesignCandidate, ...]
    scenarios: tuple[Scenario, ...]
    campaign: CampaignPlan

    def states_for_design(self, index: int) -> tuple[CampaignState, ...]:
        start = index * len(self.scenarios)
        return self.campaign.states[start:start + len(self.scenarios)]


@dataclass(frozen=True)
class DesignEvaluation:
    design: DesignCandidate
    status: str
    accepted_count: int
    required_count: int
    message: str
    study: CircuitStudy | None


@dataclass(frozen=True)
class DesignCampaignReport:
    plan: DesignCampaignPlan
    mapping: TwoPortMetricMap
    settings: SeriesSeriesSettings
    limits: CircuitLimits
    designs: tuple[DesignEvaluation, ...]


def designs_from_jobs(jobs: Iterable[Job]) -> tuple[DesignCandidate, ...]:
    selected = tuple(jobs)
    if not selected:
        raise ValueError("Select at least one accepted nominal COMSOL job")
    first = selected[0]
    for item in selected:
        metadata = (item.result or {}).get("metadata", {})
        validation = metadata.get("scientific_validation", {}) if isinstance(metadata, dict) else {}
        if (item.adapter != "comsol" or item.status != JobStatus.SUCCEEDED
                or not isinstance(validation, dict)
                or validation.get("status") not in {"valid", "warning"}):
            raise ValueError(f"Job #{item.id} must have an accepted scientific COMSOL result")
        if item.run_context != first.run_context or item.output_formulas != first.output_formulas:
            raise ValueError("Selected nominal jobs must share the same model and formula identity")
    return tuple(DesignCandidate(f"Design #{item.id}", item.id, dict(item.parameters)) for item in selected)


def _quantity_key(value: Any) -> Any:
    quantity = parse_quantity(value)
    if quantity is None:
        return str(value).strip()
    value = 0.0 if quantity.si_value == 0 else quantity.si_value
    return (quantity.dimension, format(value, ".12g"))


def build_design_campaign(
    designs: Iterable[DesignCandidate], scenarios: Iterable[Scenario], *,
    run_context: Mapping[str, Any], output_formulas: Mapping[str, str],
    existing_jobs: Iterable[Job],
) -> DesignCampaignPlan:
    designs, scenarios = tuple(designs), tuple(scenarios)
    if not designs or not scenarios:
        raise ValueError("Select at least one design and a Nominal scenario")
    if len(designs) * len(scenarios) > MAX_CAMPAIGN_STATES:
        raise ValueError("A design campaign may contain at most 500 states")
    if scenarios[0].name.casefold() != "nominal" or scenarios[0].overrides:
        raise ValueError("The first scenario must be Nominal with no overrides")
    for items, label in ((designs, "Design"), (scenarios, "Scenario")):
        names = [item.name.strip().casefold() for item in items]
        if any(not name or len(name) > 100 for name in names) or len(set(names)) != len(names):
            raise ValueError(f"{label} names must be nonempty, unique and at most 100 characters")
    for scenario in scenarios:
        for name, value in scenario.overrides.items():
            if name not in SCENARIO_DIMENSIONS:
                raise ValueError(f"Scenarios may override only gap, xoff, yoff and tilt, not '{name}'")
            _validate_scenario_quantity(name, value)
    geometry_keys = set()
    parameter_sets: list[dict[str, Any]] = []
    for design in designs:
        if (not isinstance(design.parameters, dict) or not design.parameters
                or any(not isinstance(name, str) or not name.strip()
                       or not isinstance(value, (str, int, float)) or isinstance(value, bool)
                       or (isinstance(value, float) and not math.isfinite(value))
                       for name, value in design.parameters.items())):
            raise ValueError("Design inputs must be nonempty scalar values with finite numbers")
        geometry = tuple(sorted((name, _quantity_key(value)) for name, value in design.parameters.items()
                                if name not in SCENARIO_DIMENSIONS))
        if geometry in geometry_keys:
            raise ValueError("Selected jobs describe the same geometry; choose one nominal job per design")
        geometry_keys.add(geometry)
        point_keys = set()
        for scenario in scenarios:
            absent = set(scenario.overrides) - set(design.parameters)
            if absent:
                raise ValueError("Design is missing scenario input(s): " + ", ".join(sorted(absent)))
            parameters = {**design.parameters, **scenario.overrides}
            for name in SCENARIO_DIMENSIONS.keys() & parameters.keys():
                _validate_scenario_quantity(name, parameters[name])
            key = tuple(sorted((name, _quantity_key(value)) for name, value in parameters.items()))
            if key in point_keys:
                raise ValueError(f"Equivalent scenario states for {design.name}; remove the duplicate row")
            point_keys.add(key)
            parameter_sets.append(parameters)
    campaign = build_campaign_plan(parameter_sets, adapter="comsol", run_context=run_context,
                                   output_formulas=output_formulas, existing_jobs=existing_jobs)
    return DesignCampaignPlan(designs, scenarios, campaign)


def _validate_scenario_quantity(name: str, value: Any) -> None:
    quantity = parse_quantity(value)
    if (quantity is None or quantity.dimension != SCENARIO_DIMENSIONS[name]
            or not math.isfinite(quantity.si_value) or (name == "gap" and quantity.si_value <= 0)):
        raise ValueError(f"{name} must be a finite {SCENARIO_DIMENSIONS[name]} quantity with units")


def require_campaign_identity(
    plan: DesignCampaignPlan, run_context: Mapping[str, Any], output_formulas: Mapping[str, str],
) -> None:
    if plan.campaign.run_context != dict(run_context) or plan.campaign.output_formulas != dict(output_formulas):
        raise ValueError("Connected model, contract, target or formula identity differs from the campaign")


def analyze_design_campaign(
    plan: DesignCampaignPlan, jobs: Iterable[Job], mapping: TwoPortMetricMap, *,
    settings: SeriesSeriesSettings | None = None, limits: CircuitLimits | None = None,
) -> DesignCampaignReport:
    settings, limits = settings or SeriesSeriesSettings(), limits or CircuitLimits()
    jobs_by_id = {job.id: job for job in jobs}
    evaluations = []
    for index, design in enumerate(plan.designs):
        states = plan.states_for_design(index)
        accepted_jobs = [jobs_by_id[state.job_id] for state in states
                         if state.status in {"valid", "warning"} and state.job_id in jobs_by_id
                         and jobs_by_id[state.job_id].run_signature == state.signature]
        count = len(accepted_jobs)
        study = None
        message = ""
        nominal_id = states[0].job_id
        nominal = next((job for job in accepted_jobs if job.id == nominal_id), None)
        if nominal is not None:
            try:
                study = analyze_fixed_control_scenarios(nominal, accepted_jobs, mapping,
                                                        settings=settings, limits=limits)
            except ValueError as exc:
                message = str(exc)
        else:
            message = "Accepted nominal result is not available"
        if count < len(states):
            status = "incomplete"
            message = f"{count}/{len(states)} accepted scenarios. {message}".strip()
        elif study is None or study.ineligible_count:
            status = "ineligible"
            if not message:
                message = "Some two-port results cannot be evaluated with nominal controls"
        else:
            status = "passed" if study.all_passed else "failed"
            message = f"{study.passed_count}/{len(states)} scenarios meet the configured circuit limits"
        evaluations.append(DesignEvaluation(design, status, count, len(states), message, study))
    return DesignCampaignReport(plan, mapping, settings, limits, tuple(evaluations))
