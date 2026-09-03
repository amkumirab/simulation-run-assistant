from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_QUANTITY_PATTERN = re.compile(
    rf"^\s*(?P<value>{_NUMBER})\s*(?:\[\s*(?P<bracket>[^\[\]]+)\s*\]|"
    rf"(?P<plain>[^\s\[\]]+))?\s*$"
)


@dataclass(frozen=True)
class UnitDefinition:
    dimension: str
    factor: float
    canonical: str


@dataclass(frozen=True)
class Quantity:
    value: float
    si_value: float
    dimension: str | None
    unit: str | None


def _unit(dimension: str, factor: float, canonical: str) -> UnitDefinition:
    return UnitDefinition(dimension, factor, canonical)


UNITS: dict[str, UnitDefinition] = {
    "1": _unit("dimensionless", 1.0, "1"),
    "%": _unit("ratio", 0.01, "%"),
    "m": _unit("length", 1.0, "m"),
    "cm": _unit("length", 1e-2, "cm"),
    "mm": _unit("length", 1e-3, "mm"),
    "um": _unit("length", 1e-6, "um"),
    "nm": _unit("length", 1e-9, "nm"),
    "Hz": _unit("frequency", 1.0, "Hz"),
    "hz": _unit("frequency", 1.0, "Hz"),
    "kHz": _unit("frequency", 1e3, "kHz"),
    "khz": _unit("frequency", 1e3, "kHz"),
    "MHz": _unit("frequency", 1e6, "MHz"),
    "mhz": _unit("frequency", 1e6, "MHz"),
    "GHz": _unit("frequency", 1e9, "GHz"),
    "ghz": _unit("frequency", 1e9, "GHz"),
    "rad": _unit("angle", 1.0, "rad"),
    "deg": _unit("angle", math.pi / 180.0, "deg"),
    "degree": _unit("angle", math.pi / 180.0, "deg"),
    "degrees": _unit("angle", math.pi / 180.0, "deg"),
    "s": _unit("time", 1.0, "s"),
    "ms": _unit("time", 1e-3, "ms"),
    "us": _unit("time", 1e-6, "us"),
    "min": _unit("time", 60.0, "min"),
    "A": _unit("current", 1.0, "A"),
    "mA": _unit("current", 1e-3, "mA"),
    "kA": _unit("current", 1e3, "kA"),
    "V": _unit("voltage", 1.0, "V"),
    "mV": _unit("voltage", 1e-3, "mV"),
    "kV": _unit("voltage", 1e3, "kV"),
    "W": _unit("power", 1.0, "W"),
    "mW": _unit("power", 1e-3, "mW"),
    "kW": _unit("power", 1e3, "kW"),
    "H": _unit("inductance", 1.0, "H"),
    "mH": _unit("inductance", 1e-3, "mH"),
    "uH": _unit("inductance", 1e-6, "uH"),
    "nH": _unit("inductance", 1e-9, "nH"),
    "ohm": _unit("resistance", 1.0, "ohm"),
    "Ohm": _unit("resistance", 1.0, "ohm"),
    "mOhm": _unit("resistance", 1e-3, "mOhm"),
    "mohm": _unit("resistance", 1e-3, "mOhm"),
    "kOhm": _unit("resistance", 1e3, "kOhm"),
    "kohm": _unit("resistance", 1e3, "kOhm"),
    "T": _unit("magnetic_flux_density", 1.0, "T"),
    "mT": _unit("magnetic_flux_density", 1e-3, "mT"),
    "uT": _unit("magnetic_flux_density", 1e-6, "uT"),
    "F": _unit("capacitance", 1.0, "F"),
    "mF": _unit("capacitance", 1e-3, "mF"),
    "uF": _unit("capacitance", 1e-6, "uF"),
    "nF": _unit("capacitance", 1e-9, "nF"),
    "pF": _unit("capacitance", 1e-12, "pF"),
    "S/m": _unit("conductivity", 1.0, "S/m"),
    "MS/m": _unit("conductivity", 1e6, "MS/m"),
}

REFERENCE_UNITS = {
    "dimensionless": "1",
    "ratio": "1",
    "length": "m",
    "frequency": "Hz",
    "angle": "rad",
    "time": "s",
    "current": "A",
    "voltage": "V",
    "power": "W",
    "inductance": "H",
    "resistance": "ohm",
    "magnetic_flux_density": "T",
    "capacitance": "F",
    "conductivity": "S/m",
}


def parse_quantity(value: Any) -> Quantity | None:
    """Parse one finite scalar and normalize supported units to SI."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        if not math.isfinite(parsed):
            return None
        return Quantity(parsed, parsed, None, None)

    match = _QUANTITY_PATTERN.fullmatch(str(value))
    if not match:
        return None
    try:
        parsed = float(match.group("value"))
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    unit_text = match.group("bracket") or match.group("plain")
    if unit_text is None:
        return Quantity(parsed, parsed, None, None)
    normalized = _normalize_unit(unit_text)
    definition = UNITS.get(normalized)
    if definition is None:
        return None
    dimension = None if definition.dimension == "dimensionless" else definition.dimension
    return Quantity(
        value=parsed,
        si_value=parsed * definition.factor,
        dimension=dimension,
        unit=definition.canonical,
    )


def numeric_quantity_value(value: Any, *, dimension: str | None = None) -> float | None:
    quantity = parse_quantity(value)
    if quantity is None:
        return None
    if quantity.dimension != dimension and dimension is not None:
        return None
    return quantity.si_value


def common_quantity_dimension(values: Iterable[Any]) -> str | None:
    """Return the shared dimension, rejecting invalid or mixed-unit values."""
    parsed = [parse_quantity(value) for value in values]
    if not parsed or any(quantity is None for quantity in parsed):
        raise ValueError("Values must be finite quantities with supported units")
    dimensions = {quantity.dimension for quantity in parsed if quantity is not None}
    if len(dimensions) != 1:
        raise ValueError("Values use incompatible physical dimensions")
    return next(iter(dimensions))


def reference_unit(dimension: str | None) -> str | None:
    return REFERENCE_UNITS.get(dimension) if dimension else None


def _normalize_unit(value: str) -> str:
    return (
        value.strip()
        .replace(" ", "")
        .replace("μ", "u")
        .replace("µ", "u")
        .replace("Ω", "ohm")
        .replace("°", "deg")
    )
