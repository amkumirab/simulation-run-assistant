from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable, Sequence

from simulation_assistant.types import SimulationCancelled


ProcessFactory = Callable[..., subprocess.Popen[str]]


def run_cancellable_process(
    command: Sequence[str | Path],
    *,
    cwd: str | Path,
    timeout: float,
    cancel_requested: Callable[[], bool],
    poll_interval: float = 0.25,
    process_factory: ProcessFactory = subprocess.Popen,
) -> subprocess.CompletedProcess[str]:
    """Run one child process while polling a persistent stop request."""
    if timeout <= 0:
        raise ValueError("Process timeout must be greater than zero")
    if poll_interval <= 0:
        raise ValueError("Process poll interval must be greater than zero")
    if cancel_requested():
        raise SimulationCancelled("Stop requested by user")

    normalized_command = [str(value) for value in command]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = process_factory(
        normalized_command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
    )
    deadline = time.monotonic() + timeout

    while True:
        if cancel_requested():
            _stop_process(process)
            raise SimulationCancelled("Stop requested by user")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _stop_process(process)
            raise subprocess.TimeoutExpired(normalized_command, timeout)

        try:
            stdout, stderr = process.communicate(
                timeout=min(poll_interval, remaining)
            )
        except subprocess.TimeoutExpired:
            continue
        return subprocess.CompletedProcess(
            normalized_command,
            int(process.returncode or 0),
            stdout,
            stderr,
        )


def _stop_process(process: subprocess.Popen[str], grace_seconds: float = 5.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
