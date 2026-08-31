from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from simulation_assistant.types import Job, JobStatus


PROGRESS_LINE = re.compile(
    r"Current Progress:\s*(?P<percent>\d{1,3})\s*%\s*-\s*(?P<label>.+?)\s*$",
    re.IGNORECASE,
)
OPEN_STAGE_LINE = re.compile(r"^<----\s*(?P<label>.+?)\s+-{3,}\s*$")
CLOSE_STAGE_LINE = re.compile(r"^-{3,}\s*(?P<label>.+?)\s+-{3,}>\s*$")
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
DEFAULT_STALE_SECONDS = 300
DEFAULT_TAIL_BYTES = 64 * 1024
DEFAULT_TAIL_LINES = 80


@dataclass(frozen=True)
class RunProgress:
    stage: str
    percent: int | None
    message: str
    elapsed_seconds: int
    idle_seconds: int | None
    stale: bool
    log_exists: bool
    log_updated_at: str | None
    log_path: str | None
    log_tail: list[str]

    @property
    def summary(self) -> str:
        value = f"{self.percent}% · {self.stage}" if self.percent is not None else self.stage
        return f"No recent activity · {value}" if self.stale else value

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "summary": self.summary}


def inspect_job_progress(
    job: Job,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = DEFAULT_STALE_SECONDS,
    max_tail_bytes: int = DEFAULT_TAIL_BYTES,
    max_tail_lines: int = DEFAULT_TAIL_LINES,
) -> RunProgress:
    """Inspect a job's current COMSOL log without loading the full file."""
    if stale_after_seconds < 1:
        raise ValueError("Stale activity threshold must be positive")
    if max_tail_bytes < 1:
        raise ValueError("Log tail byte limit must be positive")
    if max_tail_lines < 0:
        raise ValueError("Log tail line limit cannot be negative")

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    started_at = _parse_timestamp(job.started_at)
    elapsed_seconds = _elapsed_seconds(started_at, current_time)
    log_path = Path(job.artifact_dir) / "comsol.log" if job.artifact_dir else None

    if log_path is None or not log_path.is_file():
        idle_seconds = elapsed_seconds if job.status == JobStatus.RUNNING else None
        stale = bool(
            job.status == JobStatus.RUNNING
            and idle_seconds is not None
            and idle_seconds >= stale_after_seconds
        )
        return RunProgress(
            stage=_status_stage(job),
            percent=None,
            message="Waiting for solver log output",
            elapsed_seconds=elapsed_seconds,
            idle_seconds=idle_seconds,
            stale=stale,
            log_exists=False,
            log_updated_at=None,
            log_path=str(log_path.resolve()) if log_path else None,
            log_tail=[],
        )

    modified_at = datetime.fromtimestamp(log_path.stat().st_mtime, timezone.utc)
    if started_at and modified_at < started_at:
        return RunProgress(
            stage=_status_stage(job),
            percent=None,
            message="Waiting for current-attempt log output",
            elapsed_seconds=elapsed_seconds,
            idle_seconds=elapsed_seconds if job.status == JobStatus.RUNNING else None,
            stale=bool(
                job.status == JobStatus.RUNNING
                and elapsed_seconds >= stale_after_seconds
            ),
            log_exists=False,
            log_updated_at=None,
            log_path=str(log_path.resolve()),
            log_tail=[],
        )

    lines = _read_log_tail(log_path, max_tail_bytes, max_tail_lines)
    stage, percent, message = _parse_progress(lines, job)
    idle_seconds = max(0, int((current_time - modified_at).total_seconds()))
    stale = job.status == JobStatus.RUNNING and idle_seconds >= stale_after_seconds
    return RunProgress(
        stage=stage,
        percent=percent,
        message=message,
        elapsed_seconds=elapsed_seconds,
        idle_seconds=idle_seconds,
        stale=stale,
        log_exists=True,
        log_updated_at=modified_at.isoformat(timespec="seconds"),
        log_path=str(log_path.resolve()),
        log_tail=lines,
    )


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "Not available"
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {remaining_seconds}s"
    if minutes:
        return f"{minutes}m {remaining_seconds}s"
    return f"{remaining_seconds}s"


def _read_log_tail(path: Path, max_bytes: int, max_lines: int) -> list[str]:
    if max_lines == 0:
        return []
    size = path.stat().st_size
    start = max(0, size - max_bytes)
    with path.open("rb") as handle:
        handle.seek(start)
        raw = handle.read(max_bytes)
    text = raw.decode("utf-8", errors="replace")
    if start:
        text = text.split("\n", 1)[1] if "\n" in text else ""
    lines = [CONTROL_CHARACTERS.sub("", line).rstrip() for line in text.splitlines()]
    return lines[-max_lines:]


def _parse_progress(lines: list[str], job: Job) -> tuple[str, int | None, str]:
    stage = _status_stage(job)
    percent: int | None = None
    message = "Waiting for solver activity"
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        progress_match = PROGRESS_LINE.search(line)
        if progress_match:
            percent = min(100, int(progress_match.group("percent")))
            label = _clean_stage(progress_match.group("label"))
            stage = "Completed" if label.casefold() == "done" else label
            message = label
            continue
        if line.casefold().startswith("saving model:"):
            stage = "Saving results"
            message = "Saving the output model"
            continue
        stage_match = OPEN_STAGE_LINE.match(line) or CLOSE_STAGE_LINE.match(line)
        if stage_match:
            stage = _clean_stage(stage_match.group("label"))
            message = stage
            continue
        if line.casefold().startswith("loading model:"):
            stage = "Loading model"
            message = "Loading the input model"
    return stage, percent, message


def _clean_stage(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" -")[:160] or "Running solver"


def _status_stage(job: Job) -> str:
    if job.stop_requested_at and job.status == JobStatus.RUNNING:
        return "Stopping solver"
    return {
        JobStatus.QUEUED: "Waiting in queue",
        JobStatus.RUNNING: "Starting solver",
        JobStatus.SUCCEEDED: "Completed",
        JobStatus.FAILED: "Run failed",
        JobStatus.CANCELLED: "Run cancelled",
    }[job.status]


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _elapsed_seconds(started_at: datetime | None, now: datetime) -> int:
    if started_at is None:
        return 0
    return max(0, int((now - started_at).total_seconds()))
