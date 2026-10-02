"""Campaign configuration and path-free engineering evidence reports."""
from __future__ import annotations

import csv
import html
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from simulation_assistant.design_campaigns import (
    DesignCandidate, DesignCampaignPlan, DesignCampaignReport, Scenario, build_design_campaign,
)
from simulation_assistant.types import Job
from simulation_assistant.wpt_circuit import CircuitLimits, SeriesSeriesSettings, TwoPortMetricMap


def save_design_campaign(
    path: str | Path, plan: DesignCampaignPlan, mapping: TwoPortMetricMap, *,
    settings: SeriesSeriesSettings | None = None, limits: CircuitLimits | None = None,
) -> Path:
    destination = _path(path, ".json")
    document = {
        "schema": "wpt.design-campaign.v1",
        "designs": [asdict(item) for item in plan.designs],
        "scenarios": [asdict(item) for item in plan.scenarios],
        "run_context": plan.campaign.run_context,
        "output_formulas": plan.campaign.output_formulas,
        "mapping": asdict(mapping),
        "settings": asdict(settings or SeriesSeriesSettings()),
        "limits": asdict(limits or CircuitLimits()),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         delete=False, suffix=".tmp") as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return destination.resolve()


def load_design_campaign(
    path: str | Path, existing_jobs: Iterable[Job],
) -> tuple[DesignCampaignPlan, TwoPortMetricMap, SeriesSeriesSettings, CircuitLimits]:
    source = _path(path, ".json")
    if source.stat().st_size > 2_000_000:
        raise ValueError("Campaign configuration exceeds 2 MB")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("schema") != "wpt.design-campaign.v1":
            raise ValueError("Unsupported design campaign configuration")
        designs = tuple(DesignCandidate(**item) for item in document["designs"])
        scenarios = tuple(Scenario(**item) for item in document["scenarios"])
        if (not isinstance(document["run_context"], dict)
                or not isinstance(document["output_formulas"], dict)
                or any(not isinstance(key, str) or not isinstance(value, str)
                       for key, value in document["output_formulas"].items())):
            raise ValueError("Invalid model/formula identity")
        for item in designs:
            if (not isinstance(item.name, str) or not isinstance(item.parameters, dict)
                    or type(item.source_job_id) is not int or item.source_job_id < 1):
                raise ValueError("Invalid design candidate")
        for item in scenarios:
            if not isinstance(item.name, str) or not isinstance(item.overrides, dict):
                raise ValueError("Invalid scenario")
        mapping = TwoPortMetricMap(**document["mapping"])
        settings = SeriesSeriesSettings(**document["settings"])
        limits = CircuitLimits(**document["limits"])
        plan = build_design_campaign(designs, scenarios, run_context=document["run_context"],
                                     output_formulas=document["output_formulas"], existing_jobs=existing_jobs)
        return plan, mapping, settings, limits
    except (TypeError, KeyError, AttributeError, OverflowError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid design campaign configuration") from exc


def design_campaign_rows(report: DesignCampaignReport) -> list[dict[str, Any]]:
    rows = []
    for index, evaluation in enumerate(report.designs):
        study = evaluation.study
        circuits = {item.job_id: item for item in study.scenarios} if study else {}
        controls = asdict(study.controls) if study else {}
        for scenario, state in zip(report.plan.scenarios, report.plan.states_for_design(index)):
            circuit = circuits.get(state.job_id)
            point = circuit.operating_point if circuit else None
            row = {
                "design": evaluation.design.name,
                "source_job_id": evaluation.design.source_job_id,
                "design_status": evaluation.status,
                "accepted_scenarios": evaluation.accepted_count,
                "required_scenarios": evaluation.required_count,
                "scenario": scenario.name,
                "job_id": state.job_id or "",
                "run_signature": state.signature,
                "solve_status": state.status,
                "validation_status": state.validation_status,
                "circuit_status": circuit.status if circuit else "not evaluated",
                "message": circuit.message if circuit else evaluation.message,
                "load_ac_w": point.load_ac_w if point else "",
                "ac_efficiency": point.ac_efficiency if point else "",
                "max_current_rms_a": point.max_coil_current_rms_a if point else "",
                "max_capacitor_rms_v": point.max_capacitor_voltage_rms_v if point else "",
                "power_retention": circuit.load_power_retention if circuit else "",
                **{f"fixed_{name}": value for name, value in controls.items()},
                **{f"limit_{name}": value for name, value in asdict(report.limits).items()},
                **{f"setting_{name}": value for name, value in asdict(report.settings).items()},
                **{f"metric_{name}": value for name, value in asdict(report.mapping).items()},
                **{f"twoport_{field}": state.metrics.get(name, "")
                   for field, name in asdict(report.mapping).items()},
                **{f"input_{name}": value for name, value in state.parameters.items()},
                **{f"check_{name}": value for name, value in (circuit.checks if circuit else {}).items()},
            }
            rows.append(row)
    return rows


def write_design_campaign_csv(path: str | Path, report: DesignCampaignReport) -> Path:
    destination = _path(path, ".csv")
    rows = design_campaign_rows(report)
    columns = list(dict.fromkeys(name for row in rows for name in row))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _safe_cell(value) for key, value in row.items()})
    return destination.resolve()


def write_design_campaign_html(path: str | Path, report: DesignCampaignReport) -> Path:
    destination = _path(path, ".html")
    columns = ("design", "design_status", "accepted_scenarios", "required_scenarios", "scenario",
               "job_id", "solve_status", "circuit_status", "load_ac_w", "ac_efficiency",
               "max_current_rms_a", "max_capacitor_rms_v", "power_retention", "message")
    rows = design_campaign_rows(report)
    headings = "".join(f"<th>{html.escape(name)}</th>" for name in columns)
    table = "".join("<tr>" + "".join(f"<td>{html.escape(str(row.get(name, '')))}</td>"
                                   for name in columns) + "</tr>" for row in rows)
    evidence = html.escape(json.dumps({
        "settings": asdict(report.settings), "limits": asdict(report.limits),
        "mapping": asdict(report.mapping),
        "nominal_controls": {item.design.name: asdict(item.study.controls)
                             for item in report.designs if item.study},
    }, indent=2))
    records = html.escape(json.dumps(rows, indent=2, allow_nan=False))
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WPT Design Scenario Campaign</title><style>
body {{font:14px system-ui,sans-serif;margin:24px;color:#172630}}
.table {{overflow-x:auto}} table {{border-collapse:collapse;width:100%;font-size:12px}}
td,th {{border:1px solid #dce4e8;padding:8px;text-align:left}} th {{background:#16324a;color:white}}
pre {{white-space:pre-wrap;background:#f3f6f8;padding:16px}}
</style></head><body><h1>WPT Design Scenario Campaign</h1>
<p>Independent nominal controls for each geometry. Incomplete coverage is not a pass.</p>
<p>Efficiency is modeled AC resonant-stage efficiency, not total charger efficiency.
Limits and component assumptions are provisional; this is not hardware or thermal qualification.</p>
<div class="table"><table><thead><tr>{headings}</tr></thead><tbody>{table}</tbody></table></div>
<h2>Controls, mapping and evaluation limits</h2><pre>{evidence}</pre>
<details><summary>Complete per-scenario evidence: inputs, signatures and checks</summary>
<pre>{records}</pre></details></body></html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination.resolve()


def _safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _path(path: str | Path, suffix: str) -> Path:
    destination = Path(path)
    if destination.suffix.casefold() != suffix:
        raise ValueError(f"Use the {suffix} extension")
    return destination
