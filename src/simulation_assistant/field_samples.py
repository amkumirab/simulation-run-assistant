"""Offline magnetic-field phasors; projections are not calibrated sensor signals."""
from __future__ import annotations

import cmath
import math
import re
from dataclasses import dataclass

MAX_SAMPLES, MAX_SENSORS, MAX_SCENARIOS = 10_000, 256, 100
POSITION_TOLERANCE_M = 1e-9
POSITION_UNITS = {"m": 1., "cm": .01, "mm": .001}
FIELD_UNITS = {"T": 1., "mT": .001, "uT": 1e-6}
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}\Z")


@dataclass(frozen=True)
class FieldMetadata:
    name: str
    source_kind: str
    model_revision: str
    solution_id: str
    coordinate_frame: str
    coordinate_unit: str
    field_unit: str
    frequency_hz: float
    phasor_convention: str
    excitation: str
    phase_reference: str


@dataclass(frozen=True)
class FieldSample:
    scenario: str
    point_id: str
    position_m: tuple[float, float, float]
    field: tuple[complex, complex, complex]


@dataclass(frozen=True)
class FieldDataset:
    metadata: FieldMetadata
    samples: tuple[FieldSample, ...]
    source_sha256: str

    @property
    def scenarios(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(sample.scenario for sample in self.samples))


@dataclass(frozen=True)
class Sensor:
    point_id: str
    position_m: tuple[float, float, float]
    axis: tuple[float, float, float]


@dataclass(frozen=True)
class FieldReading:
    sensor: Sensor
    status: str
    reference_status: str
    projected_t: complex | None
    reference_t: complex | None

    @property
    def amplitude_t(self):
        return abs(self.projected_t) if self.projected_t is not None else None

    @property
    def phase_deg(self):
        return math.degrees(cmath.phase(self.projected_t)) if self.projected_t else None

    @property
    def amplitude_change_t(self):
        if self.projected_t is not None and self.reference_t is not None:
            return abs(self.projected_t) - abs(self.reference_t)
        return None

    @property
    def phase_change_deg(self):
        if self.projected_t and self.reference_t:
            difference = math.degrees(cmath.phase(self.projected_t) - cmath.phase(self.reference_t))
            return (difference + 180.) % 360. - 180.
        return None


def validate_label(value: str) -> None:
    if not isinstance(value, str) or not LABEL.fullmatch(value):
        raise ValueError("Labels need 1-80 ASCII letters/numbers, spaces, underscores, dots or hyphens")


def _number(value, limit=1e100):
    if type(value) not in (int, float) or abs(value) > limit or not math.isfinite(value):
        raise ValueError("Numeric values must be finite and within supported limits")


def _vector(value, limit):
    if not isinstance(value, tuple) or len(value) != 3:
        raise ValueError("Expected a three-component tuple")
    for component in value:
        _number(component, limit)


def validate_metadata(meta: FieldMetadata) -> None:
    if not isinstance(meta, FieldMetadata):
        raise ValueError("Missing field metadata")
    for value in (meta.name, meta.model_revision, meta.solution_id, meta.coordinate_frame,
                  meta.excitation, meta.phase_reference):
        validate_label(value)
    if any(not isinstance(value, str) for value in (meta.source_kind, meta.coordinate_unit, meta.field_unit, meta.phasor_convention)):
        raise ValueError("Metadata kinds, units and conventions must be text")
    if meta.source_kind not in ("synthetic", "comsol-export"):
        raise ValueError("Source must be synthetic or comsol-export (user-declared, not verified)")
    if meta.coordinate_unit not in POSITION_UNITS or meta.field_unit not in FIELD_UNITS:
        raise ValueError("Unsupported coordinate or field unit")
    if meta.phasor_convention not in ("peak", "rms"):
        raise ValueError("Declare peak or rms phasors explicitly")
    _number(meta.frequency_hz, 1e12)
    if meta.frequency_hz <= 0:
        raise ValueError("Frequency must be positive in Hz")


def validate_dataset(data: FieldDataset) -> None:
    if not isinstance(data, FieldDataset):
        raise ValueError("Missing field dataset")
    validate_metadata(data.metadata)
    if not isinstance(data.source_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", data.source_sha256):
        raise ValueError("Missing source CSV SHA-256")
    if not isinstance(data.samples, tuple) or not 1 <= len(data.samples) <= MAX_SAMPLES:
        raise ValueError("Dataset needs 1-10000 samples")
    seen, counts = set(), {}
    for sample in data.samples:
        if not isinstance(sample, FieldSample):
            raise ValueError("Invalid field sample")
        validate_label(sample.scenario)
        validate_label(sample.point_id)
        _vector(sample.position_m, 1e6)
        if not isinstance(sample.field, tuple) or len(sample.field) != 3:
            raise ValueError("Expected three complex field components")
        for field in sample.field:
            if not isinstance(field, complex):
                raise ValueError("Field components must preserve complex phasors")
            _number(field.real)
            _number(field.imag)
        key = sample.scenario, sample.point_id
        if key in seen:
            raise ValueError("Duplicate scenario/point ID")
        seen.add(key)
        counts[sample.scenario] = counts.get(sample.scenario, 0) + 1
    if len(counts) > MAX_SCENARIOS or max(counts.values()) > MAX_SENSORS:
        raise ValueError("Limit: 100 scenarios and 256 points per scenario")


def validate_layout(sensors: tuple[Sensor, ...]) -> None:
    if not isinstance(sensors, tuple) or not 1 <= len(sensors) <= MAX_SENSORS:
        raise ValueError("Layout needs 1-256 sensors")
    seen = set()
    for sensor in sensors:
        if not isinstance(sensor, Sensor):
            raise ValueError("Invalid sensor")
        validate_label(sensor.point_id)
        _vector(sensor.position_m, 1e6)
        _vector(sensor.axis, 1e100)
        if math.hypot(*sensor.axis) == 0:
            raise ValueError("Sensor direction must be nonzero")
        if sensor.point_id in seen:
            raise ValueError("Duplicate sensor ID")
        seen.add(sensor.point_id)


def analyze_field_samples(data: FieldDataset, sensors: tuple[Sensor, ...],
                          scenario: str, reference: str) -> tuple[FieldReading, ...]:
    """Only exact IDs and matching fixed positions; never fill missing fields."""
    validate_dataset(data)
    validate_layout(sensors)
    if scenario not in data.scenarios or reference not in data.scenarios:
        raise ValueError("Select existing scenario and reference labels")
    index = {(sample.scenario, sample.point_id): sample for sample in data.samples}

    def project(sensor, state):
        sample = index.get((state, sensor.point_id))
        if sample is None:
            return "missing point", None
        if any(abs(a-b) > POSITION_TOLERANCE_M for a, b in zip(sample.position_m, sensor.position_m)):
            return "position mismatch", None
        length = math.hypot(*sensor.axis)
        return "available", sum((direction/length)*field for direction, field in zip(sensor.axis, sample.field))

    readings = []
    for sensor in sensors:
        status, field = project(sensor, scenario)
        reference_status, reference_field = project(sensor, reference)
        readings.append(FieldReading(sensor, status, reference_status, field, reference_field))
    return tuple(readings)


def make_sensor_grid(rows: int, columns: int, spacing_m: float, z_m: float,
                     axis: tuple[float, float, float]) -> tuple[Sensor, ...]:
    if type(rows) is not int or type(columns) is not int or min(rows, columns) < 1 or rows*columns > MAX_SENSORS:
        raise ValueError("Grid needs positive integer dimensions and at most 256 sensors")
    _number(spacing_m, 1e6)
    if spacing_m <= 0:
        raise ValueError("Grid spacing must be positive")
    sensors = tuple(Sensor(f"S{row*columns+column+1}",
        ((column-(columns-1)/2)*spacing_m, (row-(rows-1)/2)*spacing_m, z_m), axis)
        for row in range(rows) for column in range(columns))
    validate_layout(sensors)
    return sensors
