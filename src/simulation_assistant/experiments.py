"""Bounded mixed-input exploration; no optimization or solver side effects."""
from __future__ import annotations

import itertools
import math
import random
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from simulation_assistant.campaigns import CampaignPlan, build_campaign_plan
from simulation_assistant.model_contract import ModelContract, validate_contract_parameters
from simulation_assistant.preflight import build_run_signature
from simulation_assistant.quantities import parse_quantity
from simulation_assistant.types import Job

MAX_POINTS = 500
MAX_ATTEMPTS = 20_000
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class InputRange:
    name: str
    minimum: str
    maximum: str
    kind: str = "continuous"


@dataclass(frozen=True)
class ExperimentSpec:
    ranges: tuple[InputRange, ...]
    fixed: dict[str, str]
    budget: int = 30
    seed: int = 7
    radius_constraint: bool = False


@dataclass(frozen=True)
class ExperimentDesign:
    spec: ExperimentSpec
    points: tuple[dict[str, str], ...]

    @property
    def shortfall(self) -> int:
        return self.spec.budget - len(self.points)


def validate_spec(spec: ExperimentSpec, contract: ModelContract | None = None) -> None:
    """Reject invalid domains before sampling; limits apply to range endpoints."""
    if type(spec.budget) is not int or not 1 <= spec.budget <= MAX_POINTS:
        raise ValueError("Experiment budget must be an integer from 1 to 500")
    if type(spec.seed) is not int or not 0 <= spec.seed <= 2**32 - 1:
        raise ValueError("Seed must be an integer from 0 to 4294967295")
    if type(spec.radius_constraint) is not bool:
        raise ValueError("Radius constraint must be true or false")
    if not isinstance(spec.ranges, tuple) or not 1 <= len(spec.ranges) <= 20:
        raise ValueError("Select between 1 and 20 input ranges")
    if not isinstance(spec.fixed, dict) or len(spec.fixed) > 200:
        raise ValueError("Fixed inputs must be a bounded parameter object")
    if any(not isinstance(item, InputRange) for item in spec.ranges):
        raise ValueError("Every range must be an InputRange")
    names = [item.name for item in spec.ranges]
    for name in names + list(spec.fixed):
        if not isinstance(name, str) or len(name) > 100 or not NAME.fullmatch(name):
            raise ValueError("Input names must be valid model parameter identifiers")
    if len(set(names)) != len(names) or set(names).intersection(spec.fixed):
        raise ValueError("Inputs must be unique and cannot be both fixed and ranged")
    for name, value in spec.fixed.items():
        if (not isinstance(value, str) or len(value) > 200 or parse_quantity(value) is None
                or not math.isfinite(parse_quantity(value).si_value)):
            raise ValueError(f"Fixed input '{name}' must be a finite supported scalar quantity")
        if name in {"N1", "N2"}:
            _count(name, value)
    endpoints = [dict(spec.fixed), dict(spec.fixed)]
    for item in spec.ranges:
        if item.kind not in {"continuous", "integer"}:
            raise ValueError(f"Unsupported range kind for '{item.name}'")
        low, high, _unit, _factor = _bounds(item)
        if low > high or not math.isfinite(high - low):
            raise ValueError(f"Range '{item.name}' needs finite ordered bounds")
        if item.kind == "integer":
            _count(item.name, item.minimum)
            _count(item.name, item.maximum)
            if abs(low) > 10**12 or abs(high) > 10**12:
                raise ValueError("Integer endpoints must be within +/-1e12")
        elif item.name in {"N1", "N2"}:
            raise ValueError(f"Coil count '{item.name}' requires an integer range")
        endpoints[0][item.name], endpoints[1][item.name] = item.minimum, item.maximum
    if spec.radius_constraint:
        if not {"r_in", "r_out"}.issubset(set(names) | set(spec.fixed)):
            raise ValueError("Radius constraint requires r_in and r_out inputs")
        for point in endpoints:
            if any(parse_quantity(point[name]).dimension != "length" for name in ("r_in", "r_out")):
                raise ValueError("Radius inputs require length units")
    if contract is not None:
        present = set(names) | set(spec.fixed)
        missing = [item.name for item in contract.inputs if item.required and item.name not in present]
        if missing:
            raise ValueError("Missing required model inputs: " + ", ".join(missing))
        validate_contract_parameters(contract, endpoints)


def _count(name: str, value: str) -> None:
    q = parse_quantity(value)
    if q is None or q.dimension is not None or not q.si_value.is_integer():
        raise ValueError(f"Integer input '{name}' requires whole dimensionless values")
    if name in {"N1", "N2"} and q.si_value < 1:
        raise ValueError(f"Coil count '{name}' must be positive")


def _bounds(item: InputRange) -> tuple[float, float, str | None, float]:
    for value in (item.minimum, item.maximum):
        if not isinstance(value, str) or len(value) > 200:
            raise ValueError(f"Range '{item.name}' requires scalar quantity text")
    low, high = parse_quantity(item.minimum), parse_quantity(item.maximum)
    if low is None or high is None or low.dimension != high.dimension:
        raise ValueError(f"Range '{item.name}' requires finite compatible scalar bounds")
    if not all(math.isfinite(q.si_value) for q in (low, high)):
        raise ValueError(f"Range '{item.name}' exceeds supported numeric limits")
    factor = parse_quantity(f"1[{low.unit}]").si_value if low.unit else 1.0
    return low.si_value, high.si_value, low.unit, factor


def _radius_ok(point: Mapping[str, str], enabled: bool) -> bool:
    return not enabled or parse_quantity(point["r_in"]).si_value < parse_quantity(point["r_out"]).si_value


def generate_experiments(spec: ExperimentSpec, contract: ModelContract | None = None) -> ExperimentDesign:
    """Seeded stratified samples with bounded rejection and an explicit shortfall."""
    validate_spec(spec, contract)
    rng = random.Random(spec.seed)
    bounds = [_bounds(item) for item in spec.ranges]
    sizes = [int(high - low) + 1 if item.kind == "integer" else (1 if low == high else 0)
             for item, (low, high, _, _) in zip(spec.ranges, bounds)]
    discrete = all(sizes) and math.prod(sizes) <= MAX_ATTEMPTS
    points, seen = [], set()

    def add(values):
        point = dict(spec.fixed)
        for item, value, (_, _, unit, factor) in zip(spec.ranges, values, bounds):
            text = str(int(value)) if item.kind == "integer" else format(value / factor, ".17g")
            point[item.name] = text + (f"[{unit}]" if unit and item.kind != "integer" else "")
        key = tuple(sorted(point.items()))
        if key not in seen and _radius_ok(point, spec.radius_constraint):
            seen.add(key)
            points.append(point)

    if discrete:
        domains = [range(int(low), int(high) + 1) if item.kind == "integer" else [low]
                   for item, (low, high, _, _) in zip(spec.ranges, bounds)]
        candidates = list(itertools.product(*domains))
        rng.shuffle(candidates)
        for values in candidates:
            add(values)
            if len(points) == spec.budget:
                break
    else:
        for _ in range(MAX_ATTEMPTS // spec.budget):
            columns = []
            for item, (low, high, _, _) in zip(spec.ranges, bounds):
                strata = list(range(spec.budget))
                rng.shuffle(strata)
                values = [low + (high - low) * ((s + rng.random()) / spec.budget) for s in strata]
                if item.kind == "integer":
                    values = [min(high, math.floor(low + (high - low + 1) * ((s + rng.random()) / spec.budget)))
                              for s in strata]
                columns.append(values)
            for values in zip(*columns):
                add(values)
                if len(points) == spec.budget:
                    break
            if len(points) == spec.budget:
                break
    if not points:
        raise ValueError("No feasible unique experiments found; check ranges and constraints")
    if contract is not None:
        validate_contract_parameters(contract, points)
    return ExperimentDesign(spec, tuple(points))


def build_experiment_campaign(design: ExperimentDesign, *, run_context: Mapping[str, Any],
                              output_formulas: Mapping[str, str], existing_jobs: Iterable[Job]) -> CampaignPlan:
    """Classify exact persisted points against current scientific job evidence."""
    current_jobs = (job for job in existing_jobs if job.adapter == "comsol"
                    and job.run_context == dict(run_context) and job.output_formulas == dict(output_formulas)
                    and job.run_signature == build_run_signature(job.adapter, job.parameters, job.output_formulas, job.run_context))
    return build_campaign_plan(design.points, adapter="comsol", run_context=run_context,
                               output_formulas=output_formulas, existing_jobs=current_jobs)
