from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree

from simulation_assistant.adapters.base import SimulationAdapter, SimulationCancelled
from simulation_assistant.model_contract import (
    apply_output_bindings,
    column_unit,
    evaluate_model_contract,
    load_model_contract,
    validate_contract_parameters,
)
from simulation_assistant.process_control import run_cancellable_process
from simulation_assistant.types import SimulationResult


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
CancellableProcessRunner = Callable[..., subprocess.CompletedProcess[str]]
PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
FEATURE_TAG = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_SELECTED_PLOTS = 12
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PLOT_EXPORTER_CLASS = "SimulationAssistantPlotExport"
PLOT_EXPORTER_SOURCE = r"""import com.comsol.model.Model;
import com.comsol.model.util.ModelUtil;

public class SimulationAssistantPlotExport {
    public static void main(String[] args) throws Exception {
        if (args.length < 1 || (args.length - 1) % 2 != 0) {
            throw new IllegalArgumentException(
                "Expected model path and plot/output pairs"
            );
        }
        Model model = ModelUtil.load("SimulationAssistantModel", args[0]);
        StringBuilder errors = new StringBuilder();
        try {
            for (int index = 1; index < args.length; index += 2) {
                String plotTag = args[index];
                String outputPath = args[index + 1];
                String exportTag = "simulationAssistantImage" + ((index - 1) / 2);
                try {
                    model.result().export().create(exportTag, plotTag, "Image");
                    model.result().export(exportTag).set("imagetype", "png");
                    model.result().export(exportTag).set("pngfilename", outputPath);
                    model.result().export(exportTag).run();
                } catch (Exception error) {
                    String message = String.valueOf(error.getMessage())
                        .replace('\t', ' ').replace('\r', ' ').replace('\n', ' ');
                    errors.append("SIMULATION_ASSISTANT_PLOT_ERROR\t")
                        .append(plotTag).append('\t').append(message).append('\n');
                }
            }
        } finally {
            ModelUtil.remove("SimulationAssistantModel");
        }
        if (errors.length() > 0) {
            throw new RuntimeException(errors.toString());
        }
    }
}
"""


@dataclass(frozen=True)
class ComsolConfig:
    executable: Path
    model_path: Path
    study_tag: str | None = None
    job_tag: str | None = None
    timeout_seconds: int = 3600
    cores: int | None = None
    plot_tags: tuple[str, ...] = ()
    contract_path: Path | None = None

    @classmethod
    def from_environment(
        cls,
        *,
        executable: str | Path | None = None,
        model_path: str | Path | None = None,
        study_tag: str | None = None,
        job_tag: str | None = None,
        timeout_seconds: int | None = None,
        cores: int | None = None,
        plot_tags: tuple[str, ...] | list[str] | None = None,
        contract_path: str | Path | None = None,
    ) -> "ComsolConfig":
        executable_value = executable or os.getenv("COMSOL_EXECUTABLE")
        resolved_executable = (
            Path(executable_value) if executable_value else discover_comsol_executable()
        )
        model_value = model_path or os.getenv("COMSOL_MODEL_PATH")
        if not model_value:
            raise ValueError(
                "COMSOL model path is required; set COMSOL_MODEL_PATH or use --model"
            )

        timeout_value = timeout_seconds
        if timeout_value is None:
            timeout_value = _positive_int(
                os.getenv("COMSOL_TIMEOUT_SECONDS", "3600"),
                "COMSOL_TIMEOUT_SECONDS",
            )
        core_value = cores
        if core_value is None and os.getenv("COMSOL_CORES"):
            core_value = _positive_int(os.environ["COMSOL_CORES"], "COMSOL_CORES")

        config = cls(
            executable=resolved_executable,
            model_path=Path(model_value),
            study_tag=study_tag or os.getenv("COMSOL_STUDY_TAG"),
            job_tag=job_tag or os.getenv("COMSOL_JOB_TAG"),
            timeout_seconds=timeout_value,
            cores=core_value,
            plot_tags=tuple(plot_tags or ()),
            contract_path=(
                Path(contract_path or os.getenv("COMSOL_CONTRACT_PATH"))
                if contract_path or os.getenv("COMSOL_CONTRACT_PATH")
                else None
            ),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.executable.is_file():
            raise ValueError(f"COMSOL executable was not found: {self.executable}")
        if not self.model_path.is_file():
            raise ValueError(f"COMSOL model was not found: {self.model_path}")
        if self.model_path.suffix.lower() != ".mph":
            raise ValueError("COMSOL model must have the .mph extension")
        if self.study_tag and self.job_tag:
            raise ValueError("Configure either COMSOL_STUDY_TAG or COMSOL_JOB_TAG, not both")
        if self.timeout_seconds < 1:
            raise ValueError("COMSOL timeout must be greater than zero")
        if self.cores is not None and self.cores < 1:
            raise ValueError("COMSOL core count must be greater than zero")
        _validate_plot_tag_syntax(self.plot_tags)
        if self.contract_path is not None:
            if not self.contract_path.is_file():
                raise ValueError(
                    f"Model contract was not found: {self.contract_path}"
                )
            if self.contract_path.suffix.lower() != ".json":
                raise ValueError("Model contract must be a JSON file")


@dataclass(frozen=True)
class ComsolModelInfo:
    filename: str
    comsol_version: str | None
    model_type: str | None
    runnable: bool | None
    physics: list[str]
    required_products: list[str]
    parameters: dict[str, str]
    studies: list[dict[str, str]]
    jobs: list[dict[str, str]]
    datasets: list[dict[str, str]]
    numerical_features: list[dict[str, str]]
    plot_groups: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComsolAdapter(SimulationAdapter):
    """Run a copied MPH model through the official COMSOL batch executable."""

    name = "comsol"

    def __init__(
        self,
        config: ComsolConfig | None = None,
        process_runner: ProcessRunner = subprocess.run,
        cancellable_process_runner: CancellableProcessRunner = run_cancellable_process,
    ) -> None:
        self.config = config
        self.process_runner = process_runner
        self.cancellable_process_runner = cancellable_process_runner

    def run(
        self,
        parameters: dict[str, Any],
        *,
        work_dir: Path | None = None,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> SimulationResult:
        _raise_if_cancelled(cancel_requested)
        config = self.config or ComsolConfig.from_environment()
        config.validate()
        model_info = inspect_mph(config.model_path)
        selected_study = _select_study(config.study_tag, config.job_tag, model_info)
        selected_plots = validate_plot_selection(config.plot_tags, model_info.plot_groups)
        contract_report = None
        if config.contract_path is not None:
            contract = load_model_contract(config.contract_path)
            try:
                output_symbols = catalog_mph_output_symbols(config.model_path)
            except ValueError:
                output_symbols = []
            contract_report = evaluate_model_contract(
                contract,
                model_info.to_dict(),
                output_symbols,
                selected_study=selected_study,
                selected_job=config.job_tag,
            )
            if contract_report.blocked:
                details = "; ".join(
                    issue.message
                    for issue in contract_report.issues
                    if issue.level == "error"
                )
                raise ValueError(f"Model contract blocked the run: {details}")
            validate_contract_parameters(contract, [parameters])

        if work_dir is None:
            work_dir = Path(".sim-assistant") / "comsol-runs" / uuid.uuid4().hex
        work_dir.mkdir(parents=True, exist_ok=True)
        input_model = work_dir / "input.mph"
        output_model = work_dir / "output.mph"
        batch_log = work_dir / "comsol.log"
        shutil.copy2(config.model_path, input_model)

        command = _build_batch_command(
            config,
            input_model=input_model,
            output_model=output_model,
            batch_log=batch_log,
            parameters=parameters,
            selected_study=selected_study,
        )
        started = time.monotonic()
        try:
            if cancel_requested is None:
                completed = self.process_runner(
                    command,
                    cwd=work_dir,
                    capture_output=True,
                    text=True,
                    timeout=config.timeout_seconds + 60,
                    check=False,
                )
            else:
                completed = self.cancellable_process_runner(
                    command,
                    cwd=work_dir,
                    timeout=config.timeout_seconds + 60,
                    cancel_requested=cancel_requested,
                )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"COMSOL exceeded the {config.timeout_seconds}-second timeout"
            ) from exc
        duration_seconds = time.monotonic() - started

        if completed.returncode != 0:
            details = _log_tail(batch_log) or completed.stderr.strip()
            suffix = f": {details}" if details else ""
            raise RuntimeError(
                f"COMSOL batch exited with code {completed.returncode}{suffix}"
            )
        if not output_model.is_file():
            raise RuntimeError("COMSOL completed without creating output.mph")

        _raise_if_cancelled(cancel_requested)
        tables = extract_mph_tables(output_model)
        tables_are_fresh = config.job_tag is not None
        metrics = _table_metrics(tables) if tables_are_fresh else {}
        if contract_report is not None and tables_are_fresh:
            metrics = apply_output_bindings(metrics, contract_report)
        metrics.update(_solver_log_metrics(batch_log))
        metrics["comsol_duration_seconds"] = round(duration_seconds, 6)
        metrics["output_model_bytes"] = float(output_model.stat().st_size)
        series = _first_series(tables) if tables_are_fresh else []
        output_info = inspect_mph(output_model)
        try:
            plot_export_metadata = _export_selected_plots(
                config,
                output_model=output_model,
                selected_plots=selected_plots,
                work_dir=work_dir,
                process_runner=self.process_runner,
                cancellable_process_runner=self.cancellable_process_runner,
                cancel_requested=cancel_requested,
            )
        except OSError as exc:
            plot_export_metadata = {
                "plot_export_status": "failed",
                "plot_exports": [],
                "plot_export_errors": {
                    plot["tag"]: f"Unable to prepare COMSOL plot artifacts: {exc}"
                    for plot in selected_plots
                },
                "plot_export_log": None,
            }
        _raise_if_cancelled(cancel_requested)
        return SimulationResult(
            metrics=metrics,
            series=series,
            metadata={
                "engine": "COMSOL Multiphysics batch",
                "comsol_version": output_info.comsol_version,
                "source_model_name": config.model_path.name,
                "study_tag": selected_study if not config.job_tag else None,
                "job_tag": config.job_tag,
                "parameters": {
                    key: _parameter_value(value) for key, value in parameters.items()
                },
                "output_model_parameters": output_info.parameters,
                "required_products": output_info.required_products,
                "output_model": str(output_model.resolve()),
                "batch_log": str(batch_log.resolve()),
                "tables": tables,
                "model_contract": (
                    contract_report.to_dict() if contract_report is not None else None
                ),
                "selected_plot_groups": selected_plots,
                **plot_export_metadata,
                "table_results_status": (
                    "fresh_by_job_contract"
                    if tables_are_fresh
                    else "saved_not_recomputed_by_study_command"
                ),
                "table_freshness_note": (
                    "Study-only runs do not automatically reevaluate Derived Values. "
                    "Saved tables remain available in metadata but are excluded from "
                    "metrics and plots. Configure a COMSOL job sequence containing "
                    "numerical evaluation tasks and set COMSOL_JOB_TAG to treat its "
                    "tables as fresh results."
                ),
            },
        )


def discover_comsol_executable() -> Path:
    candidates: list[Path] = []
    program_files = os.getenv("ProgramFiles")
    if program_files:
        root = Path(program_files) / "COMSOL"
        if root.is_dir():
            candidates.extend(
                root.glob("COMSOL*/Multiphysics/bin/win64/comsolbatch.exe")
            )
    path_match = shutil.which("comsolbatch") or shutil.which("comsolbatch.exe")
    if path_match:
        candidates.append(Path(path_match))
    existing = sorted({path.resolve() for path in candidates if path.is_file()})
    if not existing:
        raise ValueError(
            "COMSOL batch executable was not found; set COMSOL_EXECUTABLE"
        )
    return existing[-1]


def inspect_mph(model_path: str | Path) -> ComsolModelInfo:
    path = Path(model_path)
    try:
        with zipfile.ZipFile(path) as archive:
            model_info_root = ElementTree.fromstring(archive.read("modelinfo.xml"))
            smodel = json.loads(archive.read("smodel.json"))
            licenses = archive.read("usedlicenses.txt").decode("utf-8").splitlines()
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Unable to inspect COMSOL model: {path}") from exc

    parameters: dict[str, str] = {}
    studies: list[dict[str, str]] = []
    jobs: list[dict[str, str]] = []
    datasets: list[dict[str, str]] = []
    numerical_features: list[dict[str, str]] = []
    plot_groups: list[dict[str, str]] = []
    for node in _walk_json(smodel):
        api_class = str(node.get("apiClass", ""))
        if api_class == "ModelParamGroup":
            for setting in node.get("settings", []):
                if isinstance(setting, dict) and setting.get("name"):
                    parameters[str(setting["name"])] = str(setting.get("value", ""))
        elif api_class == "Study":
            studies.append(
                {
                    "tag": str(node.get("tag", "")),
                    "label": str(node.get("label", "")),
                }
            )
        elif api_class in {"Job", "JobSequence"}:
            jobs.append(
                {
                    "tag": str(node.get("tag", "")),
                    "label": str(node.get("label", "")),
                    "type": str(node.get("apiType", "")),
                }
            )
        elif api_class in {"Data", "Dataset", "DatasetFeature"}:
            datasets.append(
                {
                    "tag": str(node.get("tag", "")),
                    "label": str(node.get("label", "")),
                    "type": str(node.get("apiType", "")),
                }
            )
        elif api_class == "NumericalFeature":
            numerical_features.append(
                {
                    "tag": str(node.get("tag", "")),
                    "label": str(node.get("label", "")),
                    "type": str(node.get("apiType", "")),
                }
            )
        elif api_class == "ResultFeature" and str(node.get("apiType", "")).startswith(
            "PlotGroup"
        ):
            plot_type = str(node.get("apiType", ""))
            plot_groups.append(
                {
                    "tag": str(node.get("tag", "")),
                    "label": str(node.get("label", "")),
                    "type": plot_type,
                    "dimension": plot_type.removeprefix("PlotGroup"),
                }
            )

    physics_value = model_info_root.get("physics", "")
    physics_node = model_info_root.find("physicsInfo")
    if physics_node is not None:
        physics_value = physics_node.get("physics", physics_value)
    return ComsolModelInfo(
        filename=path.name,
        comsol_version=model_info_root.get("comsolVersion"),
        model_type=model_info_root.get("modelType"),
        runnable=_optional_bool(model_info_root.get("isRunnable")),
        physics=[value for value in physics_value.split("##") if value],
        required_products=[line.strip() for line in licenses if line.strip()],
        parameters=parameters,
        studies=studies,
        jobs=jobs,
        datasets=datasets,
        numerical_features=numerical_features,
        plot_groups=plot_groups,
    )


def check_comsol(
    config: ComsolConfig,
    process_runner: ProcessRunner = subprocess.run,
) -> dict[str, Any]:
    config.validate()
    info = inspect_mph(config.model_path)
    version = process_runner(
        [str(config.executable), "-version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if version.returncode != 0:
        raise RuntimeError("COMSOL version check failed")
    licenses = process_runner(
        [str(config.executable), "-checklicense", str(config.model_path.resolve())],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if licenses.returncode != 0:
        raise RuntimeError("COMSOL license check failed")
    selected_study = _select_study(config.study_tag, config.job_tag, info)
    selected_plots = validate_plot_selection(config.plot_tags, info.plot_groups)
    try:
        output_symbols = catalog_mph_output_symbols(config.model_path)
    except ValueError:
        output_symbols = []
    contract_report = None
    if config.contract_path is not None:
        contract_report = evaluate_model_contract(
            load_model_contract(config.contract_path),
            info.to_dict(),
            output_symbols,
            selected_study=selected_study,
            selected_job=config.job_tag,
        )
    return {
        "status": contract_report.status if contract_report is not None else "ok",
        "executable": str(config.executable.resolve()),
        "installed_version": version.stdout.strip(),
        "model": info.to_dict(),
        "selected_study": selected_study if not config.job_tag else None,
        "selected_job": config.job_tag,
        "selected_plot_groups": selected_plots,
        "license_requirements": [
            line.strip() for line in licenses.stdout.splitlines() if line.strip()
        ],
        "output_symbols": output_symbols,
        "contract": contract_report.to_dict() if contract_report is not None else None,
        "output_symbols_note": (
            "These symbols come from saved single-row COMSOL tables. They become "
            "fresh run metrics only when a configured job sequence reevaluates "
            "Derived Values."
        ),
        "timeout_seconds": config.timeout_seconds,
        "cores": config.cores,
    }


def validate_plot_selection(
    selected_tags: tuple[str, ...] | list[str],
    available_plot_groups: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Resolve requested plot tags against the inspected MPH model contract."""
    tags = _validate_plot_tag_syntax(selected_tags)
    available = {
        plot["tag"]: plot
        for plot in available_plot_groups
        if plot.get("tag")
    }
    missing = [tag for tag in tags if tag not in available]
    if missing:
        available_text = ", ".join(available) or "none"
        raise ValueError(
            f"Plot group(s) not found: {', '.join(missing)}; available: {available_text}"
        )
    return [dict(available[tag]) for tag in tags]


def _export_selected_plots(
    config: ComsolConfig,
    *,
    output_model: Path,
    selected_plots: list[dict[str, str]],
    work_dir: Path,
    process_runner: ProcessRunner,
    cancellable_process_runner: CancellableProcessRunner,
    cancel_requested: Callable[[], bool] | None,
) -> dict[str, Any]:
    if not selected_plots:
        return {
            "plot_export_status": "not_requested",
            "plot_exports": [],
            "plot_export_errors": {},
            "plot_export_log": None,
        }

    plot_dir = work_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    export_log = work_dir / "plot-export.log"
    support_dir = work_dir / ".plot-export"
    support_dir.mkdir(parents=True, exist_ok=True)
    source_path = support_dir / f"{PLOT_EXPORTER_CLASS}.java"
    class_path = support_dir / f"{PLOT_EXPORTER_CLASS}.class"
    source_path.write_text(PLOT_EXPORTER_SOURCE, encoding="utf-8", newline="\n")

    requested: list[tuple[dict[str, str], Path]] = []
    for plot in selected_plots:
        filename = _plot_filename(plot)
        requested.append((plot, plot_dir / filename))

    compiler = _find_comsol_compiler(config.executable)
    if compiler is None:
        return _failed_plot_exports(
            requested,
            "COMSOL Java compiler was not found beside the batch executable",
            export_log,
        )

    try:
        compiled = process_runner(
            [str(compiler.resolve()), str(source_path.resolve())],
            cwd=support_dir,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed_plot_exports(
            requested,
            f"COMSOL plot exporter compilation failed: {exc}",
            export_log,
        )
    if compiled.returncode != 0 or not class_path.is_file():
        details = (compiled.stderr or compiled.stdout).strip()
        message = "COMSOL plot exporter compilation failed"
        if details:
            message += f": {details[-500:]}"
        return _failed_plot_exports(requested, message, export_log)

    command = [
        str(config.executable.resolve()),
        "-3drend",
        "sw",
        "-graphics",
        "-inputfile",
        str(class_path.resolve()),
        "-batchlog",
        str(export_log.resolve()),
        "-nosave",
        "-prodargs",
        str(output_model.resolve()),
    ]
    for plot, output_path in requested:
        command.extend([plot["tag"], str(output_path.resolve())])

    try:
        if cancel_requested is None:
            completed = process_runner(
                command,
                cwd=support_dir,
                capture_output=True,
                text=True,
                timeout=config.timeout_seconds + 60,
                check=False,
            )
        else:
            completed = cancellable_process_runner(
                command,
                cwd=support_dir,
                timeout=config.timeout_seconds + 60,
                cancel_requested=cancel_requested,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _failed_plot_exports(
            requested,
            f"COMSOL plot export failed: {exc}",
            export_log,
        )

    reported_errors = _read_plot_export_errors(
        export_log,
        completed.stdout,
        completed.stderr,
    )
    fallback_error = _log_tail(export_log) or completed.stderr.strip()
    exports: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for plot, output_path in requested:
        tag = plot["tag"]
        if _is_png(output_path):
            exports.append(
                {
                    "tag": tag,
                    "label": plot.get("label", tag),
                    "dimension": plot.get("dimension", ""),
                    "filename": output_path.name,
                    "path": str(output_path.resolve()),
                    "bytes": output_path.stat().st_size,
                }
            )
            continue
        error = reported_errors.get(tag)
        if not error and completed.returncode != 0:
            error = fallback_error or (
                f"COMSOL plot process exited with code {completed.returncode}"
            )
        errors[tag] = error or "COMSOL did not create a valid PNG image"

    if exports and errors:
        status = "partial"
    elif exports:
        status = "succeeded"
    else:
        status = "failed"
    return {
        "plot_export_status": status,
        "plot_exports": exports,
        "plot_export_errors": errors,
        "plot_export_log": (
            str(export_log.resolve()) if export_log.is_file() else None
        ),
    }


def _raise_if_cancelled(cancel_requested: Callable[[], bool] | None) -> None:
    if cancel_requested and cancel_requested():
        raise SimulationCancelled("Stop requested by user")


def _find_comsol_compiler(executable: Path) -> Path | None:
    candidate = executable.with_name(f"comsolcompile{executable.suffix}")
    if candidate.is_file():
        return candidate
    match = shutil.which(candidate.name) or shutil.which("comsolcompile")
    return Path(match) if match else None


def _plot_filename(plot: dict[str, str]) -> str:
    label = str(plot.get("label") or plot["tag"])
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:64]
    return f"{plot['tag']}-{slug or 'plot'}.png"


def _is_png(path: Path) -> bool:
    try:
        with path.open("rb") as image:
            return image.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE
    except OSError:
        return False


def _read_plot_export_errors(
    export_log: Path,
    *process_output: str,
) -> dict[str, str]:
    try:
        log_text = export_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        log_text = ""
    lines = log_text.splitlines()
    for output in process_output:
        lines.extend((output or "").splitlines())
    errors: dict[str, str] = {}
    marker = "SIMULATION_ASSISTANT_PLOT_ERROR\t"
    for line in lines:
        if marker not in line:
            continue
        parts = line.split(marker, 1)[1].split("\t", 1)
        if parts:
            errors[parts[0]] = (
                parts[1] if len(parts) == 2 else "COMSOL image export failed"
            )
    return errors


def _failed_plot_exports(
    requested: list[tuple[dict[str, str], Path]],
    message: str,
    export_log: Path,
) -> dict[str, Any]:
    return {
        "plot_export_status": "failed",
        "plot_exports": [],
        "plot_export_errors": {plot["tag"]: message for plot, _ in requested},
        "plot_export_log": (
            str(export_log.resolve()) if export_log.is_file() else None
        ),
    }


def _validate_plot_tag_syntax(selected_tags: tuple[str, ...] | list[str]) -> list[str]:
    tags = [str(tag).strip() for tag in selected_tags]
    if any(not tag or not FEATURE_TAG.fullmatch(tag) for tag in tags):
        raise ValueError("COMSOL plot tags must contain only letters, numbers, and underscores")
    if len(tags) != len(set(tags)):
        raise ValueError("COMSOL plot tags cannot be duplicated")
    if len(tags) > MAX_SELECTED_PLOTS:
        raise ValueError(f"Select no more than {MAX_SELECTED_PLOTS} COMSOL plot groups")
    return tags


def extract_mph_tables(model_path: str | Path, max_rows: int = 1000) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(model_path) as archive:
            root = ElementTree.fromstring(archive.read("dmodel.xml"))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Unable to extract COMSOL tables from {model_path}") from exc

    tables: list[dict[str, Any]] = []
    for table in root.iter("TableFeature"):
        real_data = table.find("realData")
        columns_node = table.find("columnHeaders")
        if real_data is None or not real_data.text or columns_node is None:
            continue
        columns = _parse_comsol_headers(columns_node.text or "")
        if not columns:
            continue
        values = [float(item) for item in real_data.text.split(",") if item.strip()]
        rows = [
            values[index : index + len(columns)]
            for index in range(0, len(values), len(columns))
            if len(values[index : index + len(columns)]) == len(columns)
        ]
        tables.append(
            {
                "tag": table.get("tag", ""),
                "label": table.get("name", ""),
                "columns": columns,
                "rows": rows[:max_rows],
                "row_count": len(rows),
                "truncated": len(rows) > max_rows,
            }
        )
    return tables


def catalog_mph_output_symbols(model_path: str | Path) -> list[dict[str, Any]]:
    """Describe formula symbols represented by saved single-row MPH tables."""
    symbols: list[dict[str, Any]] = []
    for table in extract_mph_tables(model_path):
        if len(table["rows"]) != 1:
            continue
        for index, (column, value) in enumerate(
            zip(table["columns"], table["rows"][0]), 1
        ):
            symbols.append(
                {
                    "key": _metric_key(f"{table['tag']}_{index}_{column}"),
                    "column": column,
                    "table_tag": table["tag"],
                    "table_label": table["label"],
                    "saved_value": float(value),
                    "unit": column_unit(column),
                }
            )
    return symbols


def _build_batch_command(
    config: ComsolConfig,
    *,
    input_model: Path,
    output_model: Path,
    batch_log: Path,
    parameters: dict[str, Any],
    selected_study: str | None,
) -> list[str]:
    command = [
        str(config.executable.resolve()),
        "-inputfile",
        str(input_model.resolve()),
        "-outputfile",
        str(output_model.resolve()),
        "-batchlog",
        str(batch_log.resolve()),
        "-error",
        "on",
        "-stoptime",
        str(config.timeout_seconds),
    ]
    if config.cores is not None:
        command.extend(["-np", str(config.cores)])
    if config.job_tag:
        command.extend(["-job", config.job_tag])
    elif selected_study:
        command.extend(["-study", selected_study])
    if parameters:
        names: list[str] = []
        values: list[str] = []
        for name, value in parameters.items():
            if not PARAMETER_NAME.fullmatch(name):
                raise ValueError(f"Invalid COMSOL parameter name: {name}")
            rendered = _parameter_value(value)
            if any(character in rendered for character in (",", "\r", "\n")):
                raise ValueError(
                    f"COMSOL parameter {name} contains a comma or newline"
                )
            names.append(name)
            values.append(rendered)
        command.extend(["-pname", ",".join(names), "-plist", ",".join(values)])
    return command


def _select_study(
    study_tag: str | None,
    job_tag: str | None,
    model_info: ComsolModelInfo,
) -> str | None:
    if job_tag:
        available_jobs = [job["tag"] for job in model_info.jobs if job["tag"]]
        if available_jobs and job_tag not in available_jobs:
            raise ValueError(
                f"Job sequence '{job_tag}' not found; available jobs: "
                + ", ".join(available_jobs)
            )
        return None
    available = [study["tag"] for study in model_info.studies if study["tag"]]
    if study_tag:
        if available and study_tag not in available:
            raise ValueError(
                f"Study '{study_tag}' not found; available studies: {', '.join(available)}"
            )
        return study_tag
    if len(available) == 1:
        return available[0]
    if not available:
        raise ValueError("No COMSOL study was found in the model")
    raise ValueError(
        "Multiple COMSOL studies found; set COMSOL_STUDY_TAG to one of: "
        + ", ".join(available)
    )


def _table_metrics(tables: list[dict[str, Any]]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for table in tables:
        rows = table["rows"]
        if len(rows) != 1:
            continue
        for index, (column, value) in enumerate(zip(table["columns"], rows[0]), 1):
            key = _metric_key(f"{table['tag']}_{index}_{column}")
            metrics[key] = float(value)
    return metrics


def _first_series(tables: list[dict[str, Any]]) -> list[dict[str, float]]:
    for table in tables:
        if len(table["columns"]) < 2 or len(table["rows"]) < 2:
            continue
        x_key = _metric_key(table["columns"][0])
        y_key = _metric_key(table["columns"][1])
        return [
            {x_key: float(row[0]), y_key: float(row[1])}
            for row in table["rows"]
        ]
    return []


def _parse_comsol_headers(value: str) -> list[str]:
    parsed = next(csv.reader([value], quotechar="'", skipinitialspace=True), [])
    if not parsed:
        return []
    try:
        count = int(parsed[0])
    except ValueError:
        return []
    return [item.strip() for item in parsed[1 : count + 1]]


def _metric_key(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return cleaned or "value"


def _parameter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("COMSOL parameters must be finite")
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError("COMSOL parameters must be numbers or non-empty strings")


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _log_tail(path: Path, lines: int = 20) -> str:
    if not path.is_file():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return " | ".join(content[-lines:])[-3000:]


def _solver_log_metrics(path: Path) -> dict[str, float]:
    if not path.is_file():
        return {}
    content = path.read_text(encoding="utf-8", errors="replace")
    patterns = {
        "degrees_of_freedom": r"Number of degrees of freedom solved for:\s*([0-9]+)",
        "comsol_reported_run_seconds": r"Run time:\s*([0-9.]+)\s*s\.",
        "comsol_reported_total_seconds": r"Total time:\s*([0-9.]+)\s*s\.",
    }
    metrics: dict[str, float] = {}
    for key, pattern in patterns.items():
        matches = re.findall(pattern, content)
        if matches:
            metrics[key] = float(matches[-1])
    return metrics


def _positive_int(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() == "true"
