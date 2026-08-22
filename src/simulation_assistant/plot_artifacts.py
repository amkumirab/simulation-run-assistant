from __future__ import annotations

import base64
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Iterable, Mapping

from simulation_assistant.types import Job, JobStatus


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class PlotComparisonArtifact:
    job: Job
    plot: dict[str, Any]
    path: Path


def resolve_plot_artifact(
    artifact_dir: str | Path | None,
    plot: Mapping[str, Any],
) -> Path:
    """Resolve a recorded PNG while keeping access inside one job directory."""
    if not artifact_dir:
        raise ValueError("This job does not have an artifact directory")

    root = Path(artifact_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"Artifact directory was not found: {root}")

    candidates: list[Path] = []
    filename = str(plot.get("filename") or "").strip()
    if filename:
        if Path(filename).name != filename:
            raise ValueError("Plot filename must not contain directory components")
        candidates.append(root / "plots" / filename)

    recorded_path = str(plot.get("path") or "").strip()
    if recorded_path:
        path = Path(recorded_path)
        candidates.append(path if path.is_absolute() else root / path)

    if not candidates:
        raise ValueError("Plot metadata does not contain a file location")

    for candidate in candidates:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            continue
        if resolved.suffix.lower() == ".png" and resolved.is_file():
            try:
                with resolved.open("rb") as image:
                    if image.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE:
                        return resolved
            except OSError:
                continue
    raise ValueError("The PNG artifact is missing or outside this job directory")


def preview_subsample_factor(
    width: int,
    height: int,
    *,
    max_width: int = 620,
    max_height: int = 410,
) -> int:
    """Return an integer Tk subsample factor that fits a preview area."""
    if width < 1 or height < 1:
        raise ValueError("Image dimensions must be positive")
    if max_width < 1 or max_height < 1:
        raise ValueError("Preview dimensions must be positive")
    width_factor = (width + max_width - 1) // max_width
    height_factor = (height + max_height - 1) // max_height
    return max(1, width_factor, height_factor)


def matching_plot_artifacts(
    jobs: Iterable[Job],
    *,
    batch_name: str,
    plot_tag: str,
    limit: int = 12,
    include_job_id: int | None = None,
) -> list[PlotComparisonArtifact]:
    """Find valid matching Plot Group images from successful jobs in one batch."""
    if not plot_tag:
        raise ValueError("Plot tag is required")
    if limit < 2:
        raise ValueError("Plot comparison limit must be at least two")

    matches: list[PlotComparisonArtifact] = []
    for job in jobs:
        if job.status != JobStatus.SUCCEEDED or job.batch_name != batch_name:
            continue
        metadata = (job.result or {}).get("metadata", {})
        exports = metadata.get("plot_exports", [])
        if not isinstance(exports, list):
            continue
        plot = next(
            (
                item
                for item in exports
                if isinstance(item, dict) and str(item.get("tag") or "") == plot_tag
            ),
            None,
        )
        if plot is None:
            continue
        try:
            path = resolve_plot_artifact(job.artifact_dir, plot)
        except ValueError:
            continue
        matches.append(
            PlotComparisonArtifact(
                job=job,
                plot=dict(plot),
                path=path,
            )
        )
    matches.sort(key=lambda item: item.job.id)
    selected = matches[-limit:]
    if include_job_id is None or any(
        item.job.id == include_job_id for item in selected
    ):
        return selected
    included = next(
        (item for item in matches if item.job.id == include_job_id),
        None,
    )
    if included is None:
        return selected
    return sorted([included, *selected[1:]], key=lambda item: item.job.id)


def parameter_summary(parameters: Mapping[str, Any], limit: int = 4) -> str:
    if limit < 1:
        raise ValueError("Parameter summary limit must be positive")
    items = sorted((str(name), str(value)) for name, value in parameters.items())
    visible = items[:limit]
    summary = "  ·  ".join(f"{name}={value}" for name, value in visible)
    remaining = len(items) - len(visible)
    if remaining:
        summary += f"  ·  +{remaining} more"
    return summary or "No recorded parameters"


def write_plot_comparison_report(
    output_path: str | Path,
    comparisons: Iterable[PlotComparisonArtifact],
    *,
    title: str,
    batch_name: str,
    current_job_id: int | None = None,
) -> Path:
    """Write a portable HTML report with every PNG embedded as a data URI."""
    destination = Path(output_path)
    if destination.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("Plot comparison report must use the .html extension")
    items = list(comparisons)
    if len(items) < 2:
        raise ValueError("Plot comparison report requires at least two states")
    if not destination.parent.is_dir():
        raise ValueError(f"Report directory was not found: {destination.parent}")

    plot_tag = str(items[0].plot.get("tag") or "plot")
    cards: list[str] = []
    for item in items:
        encoded = base64.b64encode(item.path.read_bytes()).decode("ascii")
        parameter_rows = "".join(
            "<tr><th>"
            + escape(str(name))
            + "</th><td>"
            + escape(str(value))
            + "</td></tr>"
            for name, value in sorted(
                item.job.parameters.items(), key=lambda pair: str(pair[0])
            )
        )
        if not parameter_rows:
            parameter_rows = (
                '<tr><td colspan="2" class="empty">'
                "No recorded parameters</td></tr>"
            )
        current_badge = (
            '<span class="badge">Current selection</span>'
            if item.job.id == current_job_id
            else ""
        )
        cards.append(
            f"""<article class="card{' current' if item.job.id == current_job_id else ''}">
  <header><h2>Job #{item.job.id}</h2>{current_badge}</header>
  <img src="data:image/png;base64,{encoded}" alt="{escape(title)} for job {item.job.id}">
  <table><tbody>{parameter_rows}</tbody></table>
  <footer>{escape(item.path.name)} · {format_file_size(item.path.stat().st_size)}</footer>
</article>"""
        )

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} comparison</title>
<style>
:root {{ color-scheme: light; font-family: "Segoe UI", Arial, sans-serif; color: #172630; background: #f3f6f8; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 32px; }}
.page {{ max-width: 1500px; margin: 0 auto; }}
.eyebrow {{ color: #246bfe; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }}
h1 {{ margin: 6px 0; font-size: 28px; }}
.summary {{ margin: 0 0 24px; color: #667681; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; align-items: start; }}
.card {{ overflow: hidden; border: 1px solid #dce4e8; border-radius: 14px; background: #fff; box-shadow: 0 8px 24px rgba(22, 50, 74, .08); }}
.card.current {{ border: 2px solid #246bfe; }}
.card header {{ display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; }}
.card h2 {{ margin: 0; font-size: 17px; }}
.badge {{ border-radius: 999px; padding: 4px 9px; color: #246bfe; background: #eaf1ff; font-size: 11px; font-weight: 700; }}
.card img {{ display: block; width: 100%; height: auto; border-block: 1px solid #dce4e8; background: #f7f9fb; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ padding: 8px 16px; border-bottom: 1px solid #edf1f3; text-align: left; vertical-align: top; }}
th {{ width: 42%; color: #667681; font-weight: 600; }}
.empty {{ color: #667681; text-align: center; }}
.card footer {{ padding: 11px 16px; color: #667681; font-size: 12px; }}
@media print {{ body {{ padding: 0; }} .grid {{ grid-template-columns: repeat(2, 1fr); }} .card {{ break-inside: avoid; box-shadow: none; }} }}
</style>
</head>
<body>
<main class="page">
  <div class="eyebrow">Simulation comparison</div>
  <h1>{escape(title)} · {escape(plot_tag)}</h1>
  <p class="summary">Batch: {escape(batch_name)} · {len(items)} successful states · images embedded in this file</p>
  <section class="grid">{''.join(cards)}</section>
</main>
</body>
</html>
"""
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_text(document, encoding="utf-8", newline="\n")
        temporary.replace(destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return destination.resolve()


def format_file_size(byte_count: Any) -> str:
    try:
        size = max(0, int(byte_count))
    except (TypeError, ValueError):
        return "size unavailable"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"
