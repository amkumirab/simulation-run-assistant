from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class PipelineFinding:
    level: str
    code: str
    message: str
    action: str


@dataclass(frozen=True)
class ResultChain:
    study_tag: str | None
    dataset_tag: str | None
    numerical_tag: str
    numerical_label: str
    table_tag: str | None
    table_label: str | None
    state: str
    expressions: tuple[str, ...]
    units: tuple[str, ...]
    table_columns: tuple[str, ...]


@dataclass(frozen=True)
class ResultPipelineReport:
    status: str
    target_kind: str
    target_tag: str | None
    chains: tuple[ResultChain, ...]
    jobs: tuple[dict[str, Any], ...]
    orphan_tables: tuple[str, ...]
    findings: tuple[PipelineFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_result_pipeline(
    model: Mapping[str, Any],
    *,
    selected_study: str | None,
    selected_job: str | None,
) -> ResultPipelineReport:
    """Build a conservative Study-to-Table result lineage from MPH metadata."""
    findings: list[PipelineFinding] = []
    datasets = _index_features(model.get("datasets"))
    tables = _index_features(model.get("tables"))
    numerical_features = _feature_list(model.get("numerical_features"))
    jobs = tuple(dict(item) for item in _feature_list(model.get("jobs")))
    chains: list[ResultChain] = []
    produced_tables: set[str] = set()
    has_incomplete_chain = False

    if not numerical_features:
        has_incomplete_chain = True
        _finding(
            findings,
            "error",
            "no_numerical_features",
            "No Derived Values features were found in the model.",
            "Create the required Derived Values evaluations and bind each one to a result table.",
        )

    for numerical in numerical_features:
        numerical_tag = str(numerical.get("tag") or "")
        numerical_label = str(numerical.get("label") or numerical_tag)
        dataset_tag = _optional_tag(numerical.get("dataset_tag"))
        table_tag = _optional_tag(numerical.get("table_tag"))
        dataset = datasets.get(dataset_tag or "")
        table = tables.get(table_tag or "")
        study_tag = _optional_tag(dataset.get("study_tag")) if dataset else None
        missing: list[str] = []
        if not dataset_tag:
            missing.append("dataset reference")
        elif dataset is None:
            missing.append(f"dataset '{dataset_tag}'")
        if not table_tag:
            missing.append("table binding")
        elif table is None:
            missing.append(f"table '{table_tag}'")
        if table_tag:
            produced_tables.add(table_tag)
        if missing:
            has_incomplete_chain = True
            _finding(
                findings,
                "error",
                "incomplete_result_chain",
                f"Derived Value '{numerical_tag}' is missing " + " and ".join(missing) + ".",
                "Open the Derived Values feature in COMSOL and select both its Dataset and Table.",
            )
        if selected_study and study_tag and study_tag != selected_study:
            has_incomplete_chain = True
            _finding(
                findings,
                "error",
                "study_dataset_mismatch",
                f"Derived Value '{numerical_tag}' reads Study '{study_tag}', not selected Study '{selected_study}'.",
                "Select a Dataset produced by the active Study or choose the matching Study target.",
            )
        chains.append(
            ResultChain(
                study_tag=study_tag,
                dataset_tag=dataset_tag,
                numerical_tag=numerical_tag,
                numerical_label=numerical_label,
                table_tag=table_tag,
                table_label=(str(table.get("label") or table_tag) if table else None),
                state="incomplete" if missing else "linked",
                expressions=tuple(str(value) for value in numerical.get("expressions", [])),
                units=tuple(str(value) for value in numerical.get("units", [])),
                table_columns=(
                    tuple(str(value) for value in table.get("columns", []))
                    if table
                    else ()
                ),
            )
        )

    orphan_tables = tuple(
        sorted(
            tag
            for tag, table in tables.items()
            if tag not in produced_tables and bool(table.get("has_data"))
        )
    )
    if orphan_tables:
        _finding(
            findings,
            "info",
            "orphan_saved_tables",
            "Saved data exists in table(s) without a discovered Derived Values producer: "
            + ", ".join(orphan_tables)
            + ".",
            "Treat these tables as snapshots unless their producer can be verified.",
        )

    target_kind = "job" if selected_job else "study"
    target_tag = selected_job or selected_study
    status = "incomplete" if has_incomplete_chain else "unknown"
    if selected_job:
        selected = next(
            (job for job in jobs if str(job.get("tag")) == selected_job),
            None,
        )
        if selected is None:
            status = "incomplete"
            _finding(
                findings,
                "error",
                "selected_job_not_discovered",
                f"Selected Job Sequence '{selected_job}' was not discovered in the model.",
                "Create or select a COMSOL Job Sequence that solves the model and evaluates Derived Values.",
            )
        else:
            steps = [
                step
                for step in _feature_list(selected.get("steps"))
                if step.get("active", True) is not False
            ]
            if not steps:
                if status != "incomplete":
                    status = "unknown"
                _finding(
                    findings,
                    "warning",
                    "job_steps_not_discoverable",
                    f"Steps inside Job Sequence '{selected_job}' could not be confirmed.",
                    "Verify that the Job Sequence contains a solve step followed by Evaluate Derived Values.",
                )
            else:
                solve_steps = [step for step in steps if _step_category(step) == "solve"]
                evaluation_steps = [
                    step for step in steps if _step_category(step) == "evaluation"
                ]
                if not solve_steps:
                    status = "incomplete"
                    _finding(
                        findings,
                        "error",
                        "job_missing_solve",
                        f"Job Sequence '{selected_job}' has no discovered solve step.",
                        "Add a Study or Solve step before result evaluation.",
                    )
                if not evaluation_steps:
                    status = "incomplete"
                    _finding(
                        findings,
                        "error",
                        "job_missing_evaluation",
                        f"Job Sequence '{selected_job}' does not reevaluate Derived Values.",
                        "Add an Evaluate Derived Values step after the solve step.",
                    )
                ordered = bool(solve_steps and evaluation_steps) and max(
                    steps.index(step) for step in evaluation_steps
                ) > min(steps.index(step) for step in solve_steps)
                if solve_steps and evaluation_steps and not ordered:
                    status = "incomplete"
                    _finding(
                        findings,
                        "error",
                        "job_step_order_invalid",
                        f"Job Sequence '{selected_job}' has no result evaluation after its discovered solve step.",
                        "Move Evaluate Derived Values after the solve step.",
                    )
                if ordered and not has_incomplete_chain:
                    status = "fresh"
                    _finding(
                        findings,
                        "info",
                        "fresh_pipeline_verified",
                        f"Job Sequence '{selected_job}' contains solve and result-evaluation steps.",
                        "Keep the solve step before evaluation when editing the Job Sequence.",
                    )
    elif selected_study:
        status = "incomplete" if has_incomplete_chain else "stale"
        _finding(
            findings,
            "warning",
            "study_does_not_refresh_tables",
            f"Study-only execution of '{selected_study}' does not reevaluate Derived Values tables.",
            "Create a Job Sequence with Study and Evaluate Derived Values steps for fresh physical outputs.",
        )
    else:
        status = "incomplete" if has_incomplete_chain else "unknown"
        _finding(
            findings,
            "warning",
            "target_not_selected",
            "No Study or Job Sequence target is selected.",
            "Select the target that produces the expected result pipeline.",
        )

    return ResultPipelineReport(
        status=status,
        target_kind=target_kind,
        target_tag=target_tag,
        chains=tuple(chains),
        jobs=jobs,
        orphan_tables=orphan_tables,
        findings=tuple(findings),
    )


def _step_category(step: Mapping[str, Any]) -> str:
    explicit = str(step.get("category") or "").lower()
    if explicit in {"solve", "evaluation", "save", "other"}:
        return explicit
    text = " ".join(
        str(step.get(field) or "") for field in ("type", "label", "tag")
    ).lower()
    if any(token in text for token in ("evaluate", "evaluation", "derived", "numerical")):
        return "evaluation"
    if any(token in text for token in ("study", "solve", "stationary", "frequency", "time dependent")):
        return "solve"
    if "save" in text:
        return "save"
    return "other"


def _feature_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _index_features(value: Any) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["tag"]): item
        for item in _feature_list(value)
        if item.get("tag")
    }


def _optional_tag(value: Any) -> str | None:
    rendered = str(value or "").strip()
    return rendered or None


def _finding(
    findings: list[PipelineFinding],
    level: str,
    code: str,
    message: str,
    action: str,
) -> None:
    findings.append(PipelineFinding(level, code, message, action))
