from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

from simulation_assistant.adapters.base import SimulationAdapter
from simulation_assistant.types import SimulationResult


class MockElectromagneticAdapter(SimulationAdapter):
    """Deterministic waveguide-like model used for demos and CI."""

    name = "mock-em"

    def run(
        self,
        parameters: dict[str, Any],
        *,
        work_dir: Path | None = None,
    ) -> SimulationResult:
        if parameters.get("force_failure"):
            raise RuntimeError("Intentional demo failure requested by force_failure")

        frequency = _positive_float(parameters, "frequency_ghz", 10.0)
        width = _positive_float(parameters, "width_mm", 20.0)
        length = _positive_float(parameters, "length_mm", 50.0)
        relative_permittivity = _positive_float(parameters, "relative_permittivity", 1.0)

        # A simple deterministic approximation for demonstration purposes only.
        cutoff = 150.0 / (width * math.sqrt(relative_permittivity))
        propagation = 1.0 / (1.0 + math.exp(-1.6 * (frequency - cutoff)))
        attenuation = math.exp(-0.0025 * length * math.sqrt(relative_permittivity))
        transmission = min(max(propagation * attenuation, 1e-6), 0.999999)
        s21_db = 20.0 * math.log10(transmission)
        reflection = math.sqrt(max(0.0, 1.0 - transmission**2))
        s11_db = 20.0 * math.log10(max(reflection, 1e-6))

        start = max(0.1, frequency * 0.55)
        stop = frequency * 1.45
        series: list[dict[str, float]] = []
        for index in range(61):
            sample_frequency = start + (stop - start) * index / 60
            sample_propagation = 1.0 / (
                1.0 + math.exp(-1.6 * (sample_frequency - cutoff))
            )
            sample_transmission = max(sample_propagation * attenuation, 1e-6)
            series.append(
                {
                    "frequency_ghz": round(sample_frequency, 6),
                    "s21_db": round(20.0 * math.log10(sample_transmission), 6),
                }
            )

        delay_ms = min(max(float(parameters.get("demo_delay_ms", 0)), 0), 500)
        if delay_ms:
            time.sleep(delay_ms / 1000)

        return SimulationResult(
            metrics={
                "cutoff_frequency_ghz": round(cutoff, 6),
                "s11_db": round(s11_db, 6),
                "s21_db": round(s21_db, 6),
            },
            series=series,
            metadata={
                "model": "deterministic mock rectangular-waveguide approximation",
                "disclaimer": "Demo output; not a replacement for a validated solver.",
            },
        )


def _positive_float(parameters: dict[str, Any], key: str, default: float) -> float:
    try:
        value = float(parameters.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{key} must be greater than zero")
    return value
