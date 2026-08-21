from __future__ import annotations

from dataclasses import dataclass
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
