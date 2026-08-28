from simulation_assistant.adapters.base import SimulationAdapter, SimulationCancelled
from simulation_assistant.adapters.comsol import ComsolAdapter
from simulation_assistant.adapters.mock import MockElectromagneticAdapter

__all__ = [
    "ComsolAdapter",
    "MockElectromagneticAdapter",
    "SimulationAdapter",
    "SimulationCancelled",
]
