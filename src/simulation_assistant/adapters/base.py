from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from simulation_assistant.types import SimulationResult


class SimulationAdapter(ABC):
    """Boundary between queue orchestration and a simulation engine."""

    name: str

    @abstractmethod
    def run(
        self,
        parameters: dict[str, Any],
        *,
        work_dir: Path | None = None,
    ) -> SimulationResult:
        """Run one parameter set and return normalized results."""
