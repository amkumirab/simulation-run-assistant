"""Versioned exact experiment points and evidence-aware offline review."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from simulation_assistant.campaigns import CampaignPlan
from simulation_assistant.csv_export import safe_csv_cell
from simulation_assistant.experiments import ExperimentDesign, ExperimentSpec, InputRange, validate_spec
from simulation_assistant.formulas import validate_output_formulas
from simulation_assistant.quantities import parse_quantity

SCHEMA = "wpt.experiments.v1"
METHODS = {"bounded-stratified-v1", "stored-points-v1"}


@dataclass(frozen=True)
class SavedExperiment:
    design: ExperimentDesign
    run_context: dict[str, Any]
    output_formulas: dict[str, str]
    method: str = "bounded-stratified-v1"


def _validate_points(design: ExperimentDesign) -> None:
    validate_spec(design.spec)
    if not 1 <= len(design.points) <= design.spec.budget:
        raise ValueError("Experiment point count must be positive and within budget")
    expected = set(design.spec.fixed) | {item.name for item in design.spec.ranges}
    seen = set()
    for point in design.points:
        if not isinstance(point, dict) or set(point) != expected:
            raise ValueError("Experiment point fields do not match the specification")
        if any(not isinstance(value, str) or len(value) > 200 or parse_quantity(value) is None
               or not math.isfinite(parse_quantity(value).si_value) for value in point.values()):
            raise ValueError("Invalid experiment point quantity")
        if any(point[name] != value for name, value in design.spec.fixed.items()):
            raise ValueError("Experiment fixed inputs were changed")
        for item in design.spec.ranges:
            q, low, high = (parse_quantity(value) for value in (point[item.name], item.minimum, item.maximum))
            if q.dimension != low.dimension or not low.si_value <= q.si_value <= high.si_value:
                raise ValueError("Experiment point lies outside its range")
            if item.kind == "integer" and not q.si_value.is_integer():
                raise ValueError("Experiment count must be an integer")
        key = tuple(sorted((name, parse_quantity(value).dimension, parse_quantity(value).si_value)
                           for name, value in point.items()))
        if key in seen:
            raise ValueError("Experiment points must be unique")
        seen.add(key)
        if design.spec.radius_constraint and parse_quantity(point["r_in"]).si_value >= parse_quantity(point["r_out"]).si_value:
            raise ValueError("Experiment radius constraint failed")


def _digest(points) -> str:
    return hashlib.sha256(json.dumps(points, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def save_experiment(path: str | Path, design: ExperimentDesign, run_context: Mapping[str, Any],
                    output_formulas: Mapping[str, str], *, method: str = "bounded-stratified-v1") -> Path:
    """Atomically save exact sampled points, not transient cached job statuses."""
    _validate_points(design)
    if not isinstance(run_context, Mapping) or not run_context:
        raise ValueError("Missing experiment execution identity")
    if method not in METHODS:
        raise ValueError("Unsupported experiment origin method")
    destination = _path(path, ".json")
    formulas = validate_output_formulas(dict(output_formulas))
    document = {"schema": SCHEMA, "method": method, **asdict(design.spec),
                "points": design.points, "points_sha256": _digest(design.points),
                "run_context": dict(run_context), "output_formulas": formulas}
    encoded = json.dumps(document, indent=2, allow_nan=False)
    if len(encoded.encode("utf-8")) > 1_000_000:
        raise ValueError("Experiment file exceeds 1 MB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         delete=False, suffix=".tmp") as stream:
            temporary = Path(stream.name)
            stream.write(encoded + "\n")
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return destination.resolve()


def load_experiment(path: str | Path) -> SavedExperiment:
    """Load bounded local JSON; never execute formulas, paths, or a solver."""
    source = _path(path, ".json")
    try:
        with source.open("rb") as stream:
            raw = stream.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Experiment file exceeds 1 MB")
        document = json.loads(raw)
        fields = {"schema", "method", "ranges", "fixed", "budget", "seed", "radius_constraint",
                  "points", "points_sha256", "run_context", "output_formulas"}
        if (not isinstance(document, dict) or set(document) != fields
                or document["schema"] != SCHEMA or document["method"] not in METHODS):
            raise ValueError("Unsupported experiment configuration")
        if not isinstance(document["ranges"], list) or len(document["ranges"]) > 20:
            raise ValueError("Invalid experiment ranges")
        ranges = tuple(InputRange(**item) for item in document["ranges"])
        spec = ExperimentSpec(ranges, document["fixed"], document["budget"], document["seed"], document["radius_constraint"])
        if not isinstance(document["points"], list) or len(document["points"]) > 500:
            raise ValueError("Invalid experiment points")
        design = ExperimentDesign(spec, tuple(document["points"]))
        _validate_points(design)
        if _digest(design.points) != document["points_sha256"]:
            raise ValueError("Experiment points failed their integrity check")
        if not isinstance(document["run_context"], dict) or not document["run_context"]:
            raise ValueError("Missing experiment execution identity")
        if not isinstance(document["output_formulas"], dict):
            raise ValueError("Experiment formulas must be a name-to-expression object")
        formulas = validate_output_formulas(document["output_formulas"])
        return SavedExperiment(design, document["run_context"], formulas, document["method"])
    except (TypeError, KeyError, AttributeError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid experiment configuration") from exc


def require_experiment_identity(saved: SavedExperiment, context: Mapping[str, Any], formulas: Mapping[str, str]) -> None:
    if saved.run_context != dict(context) or saved.output_formulas != dict(formulas):
        raise ValueError("Model, contract, target, plots or formulas changed; generate a new experiment plan")


def write_experiment_csv(path: str | Path, plan: CampaignPlan) -> Path:
    """Export all states, including missing/failed ones, with exact signatures."""
    destination = _path(path, ".csv")
    inputs = sorted({name for state in plan.states for name in state.parameters})
    metrics = sorted({name for state in plan.states for name in state.metrics})
    columns = ["state", "status", "validation_status", "job_id", "run_signature", "plan_origin",
               *("input_" + name for name in inputs), *("output_" + name for name in metrics)]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[safe_csv_cell(name) for name in columns])
        writer.writeheader()
        for state in plan.states:
            row = {"state": state.index, "status": state.status, "validation_status": state.validation_status,
                   "job_id": state.job_id or "", "run_signature": state.signature,
                   "plan_origin": plan.run_context.get("origin", "Connected COMSOL plan; inspect job evidence for result provenance"),
                   **{"input_" + name: state.parameters.get(name, "") for name in inputs},
                   **{"output_" + name: state.metrics.get(name, "") for name in metrics}}
            writer.writerow({safe_csv_cell(name): safe_csv_cell(value) for name, value in row.items()})
    return destination.resolve()


def _path(path: str | Path, suffix: str) -> Path:
    destination = Path(path)
    if destination.suffix.lower() != suffix:
        raise ValueError(f"Experiment file must use {suffix}")
    return destination
