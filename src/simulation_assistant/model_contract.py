from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from simulation_assistant.quantities import parse_quantity, reference_unit


CONTRACT_SCHEMA_VERSION = 1
MAX_CONTRACT_BYTES = 1_000_000
NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TAG_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
UNIT_SUFFIX = re.compile(r"(?:\((?P<round>[^()]*)\)|\[(?P<bracket>[^\[\]]+)\])\s*$")


@dataclass(frozen=True)
class ContractInput:
    name: str
    unit: str | None = None
    minimum: str | None = None
    maximum: str | None = None
    required: bool = True


@dataclass(frozen=True)
class ContractOutput:
    name: str
    table_tag: str
    column: str
    unit: str | None = None
    required: bool = True
    fresh: bool = True


@dataclass(frozen=True)
class ModelContract:
    name: str
    version: str
    required_physics: tuple[str, ...]
    require_runnable: bool
    target_kind: str | None
    target_tag: str | None
    dataset_tag: str | None
    inputs: tuple[ContractInput, ...]
    internal_parameters: tuple[str, ...]
    outputs: tuple[ContractOutput, ...]
    schema_version: int = CONTRACT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContractIssue:
    level: str
    code: str
    message: str


@dataclass(frozen=True)
class ContractCheckReport:
    status: str
    contract_name: str
    contract_version: str
    issues: tuple[ContractIssue, ...]
    design_inputs: tuple[str, ...]
    internal_parameters: tuple[str, ...]
    output_bindings: dict[str, str]

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_model_contract(path: str | Path) -> ModelContract:
    contract_path = Path(path)
    try:
        if contract_path.stat().st_size > MAX_CONTRACT_BYTES:
            raise ValueError("Model contract is larger than 1 MB")
        data = json.loads(contract_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read model contract: {contract_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model contract is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Model contract must contain a JSON object")
    return parse_model_contract(data)


def parse_model_contract(data: Mapping[str, Any]) -> ModelContract:
    schema_version = _integer(data.get("schema_version"), "schema_version")
    if schema_version != CONTRACT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported model contract schema version: {schema_version}"
        )
    name = _non_empty_string(data.get("name"), "name")
    version = _non_empty_string(data.get("version"), "version")
    require_runnable = data.get("require_runnable", True)
    if not isinstance(require_runnable, bool):
        raise ValueError("Model contract 'require_runnable' must be true or false")

    target_kind: str | None = None
    target_tag: str | None = None
    target = data.get("target")
    if target is not None:
        if not isinstance(target, dict):
            raise ValueError("Model contract 'target' must be an object")
        target_kind = _non_empty_string(target.get("kind"), "target.kind").lower()
        if target_kind not in {"study", "job"}:
            raise ValueError("Model contract target kind must be 'study' or 'job'")
        target_tag = _feature_tag(target.get("tag"), "target.tag")

    dataset_tag = data.get("dataset_tag")
    if dataset_tag is not None:
        dataset_tag = _feature_tag(dataset_tag, "dataset_tag")

    required_physics = _unique_strings(data.get("required_physics", []), "required_physics")
    inputs = tuple(_parse_input(item, index) for index, item in enumerate(_list(data, "inputs")))
    input_names = [item.name for item in inputs]
    if len(input_names) != len(set(input_names)):
        raise ValueError("Model contract input names must be unique")

    internal_parameters = tuple(
        _parameter_name(value, f"internal_parameters[{index}]")
        for index, value in enumerate(_list(data, "internal_parameters"))
    )
    if len(internal_parameters) != len(set(internal_parameters)):
        raise ValueError("Model contract internal parameter names must be unique")
    overlap = set(input_names).intersection(internal_parameters)
    if overlap:
        raise ValueError(
            "Model contract parameters cannot be both design inputs and internal: "
            + ", ".join(sorted(overlap))
        )

    outputs = tuple(
        _parse_output(item, index) for index, item in enumerate(_list(data, "outputs"))
    )
    output_names = [item.name for item in outputs]
    if len(output_names) != len(set(output_names)):
        raise ValueError("Model contract output names must be unique")

    return ModelContract(
        name=name,
        version=version,
        required_physics=required_physics,
        require_runnable=require_runnable,
        target_kind=target_kind,
        target_tag=target_tag,
        dataset_tag=dataset_tag,
        inputs=inputs,
        internal_parameters=internal_parameters,
        outputs=outputs,
        schema_version=schema_version,
    )


def evaluate_model_contract(
    contract: ModelContract,
    model: Mapping[str, Any],
    output_symbols: Iterable[Mapping[str, Any]],
    *,
    selected_study: str | None,
    selected_job: str | None,
) -> ContractCheckReport:
    issues: list[ContractIssue] = []
    parameters = dict(model.get("parameters", {}))
    physics = {str(value).casefold() for value in model.get("physics", [])}
    studies = _available_tags(model.get("studies", []))
    jobs = _available_tags(model.get("jobs", []))
    datasets = _available_tags(model.get("datasets", []))

    if contract.require_runnable and model.get("runnable") is False:
        _issue(issues, "error", "model_not_runnable", "The MPH model is not marked as runnable.")
    for required in contract.required_physics:
        if required.casefold() not in physics:
            _issue(
                issues,
                "error",
                "missing_physics",
                f"Required physics '{required}' was not found in the model.",
            )

    actual_kind = "job" if selected_job else "study"
    actual_tag = selected_job or selected_study
    if contract.target_kind and contract.target_kind != actual_kind:
        _issue(
            issues,
            "error",
            "target_kind_mismatch",
            f"Contract requires a {contract.target_kind} target, but "
            f"{actual_kind} mode is selected.",
        )
    if contract.target_tag and contract.target_tag != actual_tag:
        _issue(
            issues,
            "error",
            "target_tag_mismatch",
            f"Contract requires target '{contract.target_tag}', but "
            f"'{actual_tag or 'none'}' is selected.",
        )
    if selected_study and studies and selected_study not in studies:
        _issue(issues, "error", "study_not_found", f"Study '{selected_study}' was not found.")
    if selected_job and jobs and selected_job not in jobs:
        _issue(issues, "error", "job_not_found", f"Job sequence '{selected_job}' was not found.")
    if selected_job and not jobs:
        _issue(
            issues,
            "warning",
            "job_not_discoverable",
            "The selected job sequence could not be confirmed from the MPH metadata.",
        )
    if contract.dataset_tag and contract.dataset_tag not in datasets:
        _issue(
            issues,
            "error",
            "dataset_not_found",
            f"Required dataset '{contract.dataset_tag}' was not found.",
        )

    for item in contract.inputs:
        if item.name not in parameters:
            if item.required:
                _issue(
                    issues,
                    "error",
                    "missing_input",
                    f"Required design input '{item.name}' was not found.",
                )
            else:
                _issue(
                    issues,
                    "warning",
                    "optional_input_missing",
                    f"Optional design input '{item.name}' was not found.",
                )
            continue
        _check_default_unit(item, parameters[item.name], issues)
    for name in contract.internal_parameters:
        if name not in parameters:
            _issue(
                issues,
                "error",
                "missing_internal_parameter",
                f"Internal parameter '{name}' was not found.",
            )

    symbols = list(output_symbols)
    bindings: dict[str, str] = {}
    for output in contract.outputs:
        matches = [
            symbol
            for symbol in symbols
            if str(symbol.get("table_tag", "")) == output.table_tag
            and str(symbol.get("column", "")) == output.column
        ]
        if not matches:
            level = "error" if output.required else "warning"
            _issue(
                issues,
                level,
                "missing_output",
                f"Output '{output.name}' was not found in table "
                f"'{output.table_tag}' column '{output.column}'.",
            )
            continue
        symbol = matches[0]
        bindings[output.name] = str(symbol.get("key", ""))
        _check_output_unit(output, symbol, issues)
        if output.fresh and not selected_job:
            _issue(
                issues,
                "error" if output.required else "warning",
                "fresh_output_requires_job",
                f"Output '{output.name}' requires a job sequence that reevaluates Derived Values.",
            )

    status = (
        "blocked"
        if any(issue.level == "error" for issue in issues)
        else "warning"
        if issues
        else "ready"
    )
    return ContractCheckReport(
        status=status,
        contract_name=contract.name,
        contract_version=contract.version,
        issues=tuple(issues),
        design_inputs=tuple(item.name for item in contract.inputs if item.name in parameters),
        internal_parameters=contract.internal_parameters,
        output_bindings=bindings,
    )


def validate_contract_parameters(
    contract: ModelContract,
    parameter_sets: Iterable[Mapping[str, Any]],
) -> None:
    allowed = {item.name for item in contract.inputs}
    internal = set(contract.internal_parameters)
    definitions = {item.name: item for item in contract.inputs}
    errors: list[str] = []
    for state_index, parameters in enumerate(parameter_sets, 1):
        unknown = set(parameters).difference(allowed)
        internal_overrides = unknown.intersection(internal)
        if internal_overrides:
            errors.append(
                f"State {state_index} overrides internal parameter(s): "
                + ", ".join(sorted(internal_overrides))
            )
        other_unknown = unknown.difference(internal)
        if other_unknown:
            errors.append(
                f"State {state_index} contains undeclared input(s): "
                + ", ".join(sorted(other_unknown))
            )
        for name, value in parameters.items():
            definition = definitions.get(name)
            if definition is None:
                continue
            error = _validate_input_value(definition, value)
            if error:
                errors.append(f"State {state_index}, input '{name}': {error}")
        if len(errors) >= 10:
            break
    if errors:
        suffix = "\nAdditional errors were omitted." if len(errors) >= 10 else ""
        raise ValueError("Model contract rejected the run:\n" + "\n".join(errors[:10]) + suffix)


def apply_output_bindings(
    metrics: Mapping[str, float], report: ContractCheckReport
) -> dict[str, float]:
    bound = dict(metrics)
    for name, source_key in report.output_bindings.items():
        if source_key in metrics:
            bound[name] = float(metrics[source_key])
    return bound


def _parse_input(value: Any, index: int) -> ContractInput:
    label = f"inputs[{index}]"
    if not isinstance(value, dict):
        raise ValueError(f"Model contract '{label}' must be an object")
    name = _parameter_name(value.get("name"), f"{label}.name")
    unit = _optional_string(value.get("unit"), f"{label}.unit")
    minimum = _optional_string(value.get("min"), f"{label}.min")
    maximum = _optional_string(value.get("max"), f"{label}.max")
    required = value.get("required", True)
    if not isinstance(required, bool):
        raise ValueError(f"Model contract '{label}.required' must be true or false")
    item = ContractInput(name, unit, minimum, maximum, required)
    _validate_input_definition(item, label)
    return item


def _parse_output(value: Any, index: int) -> ContractOutput:
    label = f"outputs[{index}]"
    if not isinstance(value, dict):
        raise ValueError(f"Model contract '{label}' must be an object")
    name = _parameter_name(value.get("name"), f"{label}.name")
    table_tag = _feature_tag(value.get("table_tag"), f"{label}.table_tag")
    column = _non_empty_string(value.get("column"), f"{label}.column")
    unit = _optional_string(value.get("unit"), f"{label}.unit")
    required = value.get("required", True)
    fresh = value.get("fresh", True)
    if not isinstance(required, bool) or not isinstance(fresh, bool):
        raise ValueError(f"Model contract '{label}' flags must be true or false")
    if unit and parse_quantity(f"1[{unit}]") is None:
        raise ValueError(f"Model contract '{label}.unit' is not a supported unit")
    return ContractOutput(name, table_tag, column, unit, required, fresh)


def _validate_input_definition(item: ContractInput, label: str) -> None:
    unit_quantity = parse_quantity(f"1[{item.unit}]") if item.unit else None
    if item.unit and unit_quantity is None:
        raise ValueError(f"Model contract '{label}.unit' is not a supported unit")
    limits = (item.minimum, item.maximum)
    bounds = [
        parse_quantity(value) if value is not None else None for value in limits
    ]
    if any(
        value is not None and parsed is None
        for value, parsed in zip(limits, bounds)
    ):
        raise ValueError(f"Model contract '{label}' contains an invalid limit")
    expected_dimension = unit_quantity.dimension if unit_quantity else None
    for parsed in bounds:
        if parsed is not None and parsed.dimension != expected_dimension:
            raise ValueError(f"Model contract '{label}' limits use incompatible units")
    if bounds[0] is not None and bounds[1] is not None:
        if bounds[0].si_value > bounds[1].si_value:
            raise ValueError(f"Model contract '{label}.min' cannot exceed max")


def _check_default_unit(item: ContractInput, value: Any, issues: list[ContractIssue]) -> None:
    if not item.unit:
        return
    expected = parse_quantity(f"1[{item.unit}]")
    actual = parse_quantity(value)
    if actual is None:
        _issue(
            issues,
            "warning",
            "input_unit_not_verifiable",
            f"Default value for '{item.name}' is an expression; its unit could not be verified.",
        )
    elif expected is not None and actual.dimension != expected.dimension:
        _issue(
            issues,
            "error",
            "input_unit_mismatch",
            f"Input '{item.name}' must use "
            f"{reference_unit(expected.dimension) or item.unit} compatible units.",
        )


def _check_output_unit(
    output: ContractOutput,
    symbol: Mapping[str, Any],
    issues: list[ContractIssue],
) -> None:
    if not output.unit:
        return
    expected = parse_quantity(f"1[{output.unit}]")
    level = "error" if output.required else "warning"
    actual_unit = str(symbol.get("unit") or "")
    actual = parse_quantity(f"1[{actual_unit}]") if actual_unit else None
    if actual is None:
        _issue(
            issues,
            level,
            "output_unit_missing",
            f"Output '{output.name}' does not expose a supported unit in its column header.",
        )
    elif expected is not None and actual.unit != expected.unit:
        _issue(
            issues,
            level,
            "output_unit_mismatch",
            f"Output '{output.name}' uses '{actual_unit}', expected '{output.unit}'.",
        )


def _validate_input_value(item: ContractInput, value: Any) -> str | None:
    quantity = parse_quantity(value)
    if quantity is None:
        return "value must be a finite scalar with a supported unit"
    expected = parse_quantity(f"1[{item.unit}]") if item.unit else None
    if expected is not None and quantity.dimension != expected.dimension:
        return f"unit must be compatible with {item.unit}"
    minimum = parse_quantity(item.minimum) if item.minimum else None
    maximum = parse_quantity(item.maximum) if item.maximum else None
    if minimum is not None and quantity.si_value < minimum.si_value:
        return f"value is below the minimum {item.minimum}"
    if maximum is not None and quantity.si_value > maximum.si_value:
        return f"value exceeds the maximum {item.maximum}"
    return None


def column_unit(column: str) -> str | None:
    match = UNIT_SUFFIX.search(column)
    if not match:
        return None
    value = (match.group("round") or match.group("bracket") or "").strip()
    return value or None


def _available_tags(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        str(item.get("tag"))
        for item in value
        if isinstance(item, dict) and item.get("tag")
    }


def _issue(issues: list[ContractIssue], level: str, code: str, message: str) -> None:
    issues.append(ContractIssue(level, code, message))


def _list(data: Mapping[str, Any], name: str) -> list[Any]:
    value = data.get(name, [])
    if not isinstance(value, list):
        raise ValueError(f"Model contract '{name}' must be a list")
    return value


def _unique_strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"Model contract '{label}' must be a list")
    items = tuple(_non_empty_string(item, f"{label}[]") for item in value)
    if len(items) != len(set(items)):
        raise ValueError(f"Model contract '{label}' values must be unique")
    return items


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Model contract '{label}' must be an integer")
    return value


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Model contract '{label}' must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, label)


def _parameter_name(value: Any, label: str) -> str:
    name = _non_empty_string(value, label)
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Model contract '{label}' is not a valid parameter name")
    return name


def _feature_tag(value: Any, label: str) -> str:
    tag = _non_empty_string(value, label)
    if not TAG_PATTERN.fullmatch(tag):
        raise ValueError(f"Model contract '{label}' is not a valid COMSOL tag")
    return tag
