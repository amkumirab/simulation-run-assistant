from __future__ import annotations

import json
from html import escape
from pathlib import Path

from simulation_assistant.types import Job, SimulationResult


def write_artifacts(
    artifact_root: str | Path,
    job: Job,
    result: SimulationResult,
) -> Path:
    output_dir = Path(artifact_root) / f"job-{job.id:06d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "job_id": job.id,
        "batch_name": job.batch_name,
        "adapter": job.adapter,
        "parameters": job.parameters,
        "output_formulas": job.output_formulas,
        "run_signature": job.run_signature,
        "run_context": job.run_context,
        "result": result.to_dict(),
    }
    (output_dir / "result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    if result.series:
        (output_dir / "response.svg").write_text(
            _render_svg(result.series), encoding="utf-8"
        )
    return output_dir


def _render_svg(series: list[dict[str, float]]) -> str:
    x_key, y_key = _axis_keys(series[0])
    points = [(float(item[x_key]), float(item[y_key])) for item in series]
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    if x_min == x_max:
        x_max += 1
    if y_min == y_max:
        y_max += 1

    width, height = 900, 480
    left, right, top, bottom = 84, 28, 42, 68
    plot_width = width - left - right
    plot_height = height - top - bottom

    def px(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_width

    def py(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_height

    polyline = " ".join(f"{px(x):.2f},{py(y):.2f}" for x, y in points)
    grid_lines: list[str] = []
    labels: list[str] = []
    for index in range(6):
        x = left + plot_width * index / 5
        x_value = x_min + (x_max - x_min) * index / 5
        grid_lines.append(
            f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{height-bottom}" />'
        )
        labels.append(
            f'<text x="{x:.2f}" y="{height-bottom+26}" text-anchor="middle">{x_value:.2f}</text>'
        )
    for index in range(6):
        y = top + plot_height * index / 5
        y_value = y_max - (y_max - y_min) * index / 5
        grid_lines.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" />'
        )
        labels.append(
            f'<text x="{left-12}" y="{y+5:.2f}" text-anchor="end">{y_value:.2f}</text>'
        )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
  .background {{ fill: #08111f; }}
  .grid {{ stroke: #243449; stroke-width: 1; }}
  .axis {{ stroke: #91a4bd; stroke-width: 1.5; }}
  .line {{ fill: none; stroke: #4fd1c5; stroke-width: 3; stroke-linejoin: round; }}
  text {{ fill: #cbd5e1; font: 14px system-ui, sans-serif; }}
  .title {{ fill: #f8fafc; font-size: 20px; font-weight: 700; }}
</style>
<rect class="background" width="100%" height="100%" rx="14" />
<text class="title" x="{left}" y="28">Simulation response</text>
<g class="grid">{''.join(grid_lines)}</g>
<line class="axis" x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" />
<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" />
<g>{''.join(labels)}</g>
<polyline class="line" points="{polyline}" />
<text x="{left + plot_width/2:.2f}" y="{height-18}" text-anchor="middle">{escape(x_key)}</text>
<text transform="translate(22 {top + plot_height/2:.2f}) rotate(-90)" text-anchor="middle">{escape(y_key)}</text>
</svg>
"""


def _axis_keys(first_point: dict[str, float]) -> tuple[str, str]:
    keys = list(first_point)
    if len(keys) < 2:
        raise ValueError("A chart series needs at least two numeric fields")
    return keys[0], keys[1]
