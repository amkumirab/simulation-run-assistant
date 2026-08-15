from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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
