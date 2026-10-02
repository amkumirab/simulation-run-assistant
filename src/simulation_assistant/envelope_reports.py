"""Portable, escaped evidence for sampled WPT operating envelopes."""
from __future__ import annotations

import csv
import html
import json
from dataclasses import asdict
from pathlib import Path

from simulation_assistant.operating_envelopes import OperatingEnvelope

LIMITATION = ("Linear sinusoidal AC equivalent; source amplitude only. No interpolation or "
              "extrapolation between sampled scenarios. Not hardware or thermal qualification. "
              "AC efficiency excludes inverter, rectifier, DC/DC and battery losses. "
              "Source voltage is fundamental AC RMS, not DC bus voltage.")


def envelope_rows(report: OperatingEnvelope) -> list[dict]:
    designs = {item.name: item for item in report.designs}
    records = []
    for item in report.rows:
        design = designs.get(item.design)
        record = {name: value for name, value in asdict(item).items()
                  if name not in {"operating_point", "parameters", "two_port", "checks", "source_ceilings_rms_v"}}
        record["limiting_constraints"] = "; ".join(item.limiting_constraints)
        record.update({
            "design_status": design.status if design else "",
            "nominal_job_id": design.nominal_job_id if design else None,
            "evaluated_scenarios": design.evaluated_count if design else "",
            "required_scenarios": design.required_count if design else "",
            "worst_case_maximum_load_power_w": design.worst_case_maximum_load_power_w if design else None,
            "target_load_power_w": report.settings.target_load_power_w,
            **{f"limit_{key}": value for key, value in asdict(report.limits).items()},
            **{f"limit_{key}": value for key, value in asdict(report.circuit_limits).items()},
            **{f"setting_{key}": value for key, value in asdict(report.settings).items()},
            **{f"metric_{key}": value for key, value in asdict(report.mapping).items()},
            **({("nominal_source_rms_v" if key == "source_rms_v" else f"fixed_{key}"): value
                for key, value in asdict(design.controls).items()}
               if design and design.controls else {}),
        })
        for prefix, values in (("input", item.parameters), ("twoport", item.two_port or {}),
                               ("check", item.checks or {}),
                               ("operating", asdict(item.operating_point) if item.operating_point else {})):
            record.update({f"{prefix}_{key}": value for key, value in values.items()})
        record.update({f"ceiling_{key}_rms_v": value for key, value in (item.source_ceilings_rms_v or {}).items()})
        records.append(record)
    return records


def write_envelope_csv(path: str | Path, report: OperatingEnvelope) -> Path:
    destination = _path(path, ".csv")
    rows = envelope_rows(report)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _safe_cell(value) for key, value in row.items()})
    return destination.resolve()


def write_envelope_html(path: str | Path, report: OperatingEnvelope) -> Path:
    destination = _path(path, ".html")
    columns = ("design", "scenario", "status", "required_source_rms_v", "maximum_source_rms_v",
               "operating_source_rms_v", "maximum_load_power_w", "operating_load_ac_w", "power_retention", "minimum_retention_met",
               "limiting_constraints", "message")
    rows = envelope_rows(report)
    labels = ("Design", "Scenario", "Status", "Required source (V RMS)", "Ceiling source (V RMS)",
              "Setpoint source (V RMS)", "Capacity (W)", "Setpoint (W)", "Retained target (%)", "Minimum met", "Binding limit", "Message")
    heading = "".join(f"<th>{html.escape(label)}</th>" for label in labels)
    def cell(row, key):
        value = row.get(key)
        if key == "power_retention" and value is not None:
            return f"{value*100:.3f}%"
        if key == "status":
            return str(value).replace("_", " ").title()
        return _display(value)
    table = "".join("<tr>" + "".join(f"<td>{html.escape(cell(row, key))}</td>"
                                   for key in columns) + "</tr>" for row in rows)
    summaries = "".join(f"<li>{html.escape(item.name)}: {item.status}, "
                        f"{item.evaluated_count}/{item.required_count} evaluable samples; "
                        f"worst sampled capacity (W): {_display(item.worst_case_maximum_load_power_w)}</li>"
                        for item in report.designs)
    target = report.settings.target_load_power_w
    chart = []
    for design in report.designs:
        samples = [row for row in report.rows if row.design == design.name]
        scale = max([target] + [row.maximum_load_power_w for row in samples if row.maximum_load_power_w is not None])
        bars = []
        for row in samples:
            capacity = row.maximum_load_power_w
            label = f"{row.scenario}: {_display(capacity)} W ({row.status})"
            bar = (f'<div class="bar" style="width:{100 * capacity / scale:.6f}%"></div>'
                   if capacity is not None else '<span>Unavailable</span>')
            bars.append(f'<div class="sample">{html.escape(label)}<div class="track">{bar}'
                        f'<span class="target" style="left:{100 * target / scale:.6f}%"></span></div></div>')
        chart.append(f"<h3>{html.escape(design.name)}</h3>" + "".join(bars))
    evidence = html.escape(json.dumps(rows, indent=2, allow_nan=False))
    document = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,">
<title>WPT Operating Envelope</title><style>
body {{font:14px system-ui,sans-serif;margin:24px;color:#172630}} .table {{overflow:auto}}
table {{border-collapse:collapse;width:100%;font-size:12px}} td,th {{border:1px solid #dce4e8;padding:8px;text-align:left}}
th {{background:#16324a;color:white}} pre {{white-space:pre-wrap;background:#f3f6f8;padding:16px}}
.sample {{margin:12px 0}} .track {{position:relative;max-width:800px;background:#eef2f5;height:22px}}
.bar {{height:22px;background:#287c87}} .target {{position:absolute;border-left:2px dashed #172630;top:0;height:22px}}
</style></head><body><h1>WPT Operating Envelope</h1>
<p>{html.escape(LIMITATION)}</p>
<p>Target: {target:.6g} W. Source ceiling: {report.limits.max_source_rms_v:.6g} V RMS.
Current ceiling: {report.circuit_limits.max_coil_current_rms_a:.6g} A RMS per coil.
Capacitor ceiling: {report.circuit_limits.max_capacitor_voltage_rms_v:.6g} V RMS per capacitor.</p>
<ul>{summaries}</ul><h2>Maximum modeled load power by sampled scenario</h2>
<p>Bars show capacity, not the recommended setpoint. Dashed markers show the target ({target:.6g} W).</p>
{''.join(chart)}<h2>Source-amplitude recommendations</h2>
<p>Recommended power is capped at the target. Power retention is a fraction of target power.
Stress comparisons allow 1e-10 relative numerical tolerance; no engineering safety margin is implied.</p>
<div class="table"><table><thead><tr>{heading}</tr></thead><tbody>{table}</tbody></table></div>
<details><summary>Full evidence: controls, limits, two-port data, signatures and checks</summary>
<pre>{evidence}</pre></details></body></html>'''
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination.resolve()


def _display(value):
    if value is None:
        return "Unavailable"
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def _safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _path(path, suffix):
    destination = Path(path)
    if destination.suffix.casefold() != suffix:
        raise ValueError(f"Envelope report must use the {suffix} extension")
    return destination
