from __future__ import annotations

from typing import Any

from simulation_assistant.adapters.base import SimulationAdapter
from simulation_assistant.types import SimulationResult


class ComsolAdapter(SimulationAdapter):
    """Extension point for a future COMSOL Java API or LiveLink integration."""

    name = "comsol"

    def run(self, parameters: dict[str, Any]) -> SimulationResult:
        raise NotImplementedError(
            "The COMSOL adapter is intentionally left for the next milestone. "
            "See docs/COMSOL_INTEGRATION.md."
        )
