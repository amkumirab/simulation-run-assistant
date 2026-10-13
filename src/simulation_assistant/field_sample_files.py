"""Bounded, path-free field workspaces and offline evidence exports."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from simulation_assistant.csv_export import safe_csv_cell
from simulation_assistant.field_samples import (
    FIELD_UNITS, POSITION_UNITS, MAX_SAMPLES, FieldDataset, FieldMetadata, FieldSample,
    Sensor, analyze_field_samples, validate_dataset, validate_layout, validate_metadata,
)

FIELD_COLUMNS = ("scenario", "point_id", "x", "y", "z", "bx_real", "bx_imag",
                 "by_real", "by_imag", "bz_real", "bz_imag")
SCHEMA = "wpt.field-samples.v1"


def _path(path, suffix):
    target = Path(path)
    if target.suffix.lower() != suffix:
        raise ValueError(f"Expected a {suffix} file")
    return target


def _read(path, suffix, limit):
    with _path(path, suffix).open("rb") as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError(f"File exceeds {limit // 1_000_000} MB")
    return raw


def load_field_csv(path: str | Path, metadata: FieldMetadata) -> FieldDataset:
    """Normalize a declared schema to SI; no inferred source/phase/units."""
    validate_metadata(metadata)
    raw = _read(path, ".csv", 5_000_000)
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), strict=True)
        if reader.fieldnames is None or len(reader.fieldnames) != len(FIELD_COLUMNS) or set(reader.fieldnames) != set(FIELD_COLUMNS):
            raise ValueError("CSV needs exactly: " + ",".join(FIELD_COLUMNS))
        samples = []
        for row in reader:
            if len(samples) >= MAX_SAMPLES:
                raise ValueError("CSV exceeds 10000 rows")
            if set(row) != set(FIELD_COLUMNS) or any(value is None for value in row.values()):
                raise ValueError("CSV row has missing or extra values")
            position = tuple(float(row[name])*POSITION_UNITS[metadata.coordinate_unit] for name in ("x", "y", "z"))
            field = tuple(complex(float(row[name+"_real"]), float(row[name+"_imag"]))*FIELD_UNITS[metadata.field_unit]
                          for name in ("bx", "by", "bz"))
            samples.append(FieldSample(row["scenario"], row["point_id"], position, field))
        data = FieldDataset(metadata, tuple(samples), hashlib.sha256(raw).hexdigest())
        validate_dataset(data)
        return data
    except (csv.Error, UnicodeError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid field CSV") from exc


def _atomic_text(path, text):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=target.parent,
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target.resolve()


def _digest(document):
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def save_field_workspace(path: str | Path, data: FieldDataset, sensors: tuple[Sensor, ...]) -> Path:
    validate_dataset(data)
    validate_layout(sensors)
    document = {"schema": SCHEMA, "metadata": asdict(data.metadata), "source_sha256": data.source_sha256,
                "samples": [{"scenario": sample.scenario, "point_id": sample.point_id,
                             "position_m": sample.position_m,
                             "field": [[field.real, field.imag] for field in sample.field]} for sample in data.samples],
                "sensors": [asdict(sensor) for sensor in sensors]}
    document["workspace_sha256"] = _digest(document)
    encoded = json.dumps(document, indent=2, allow_nan=False) + "\n"
    if len(encoded.encode("utf-8")) > 8_000_000:
        raise ValueError("Workspace exceeds 8 MB")
    return _atomic_text(_path(path, ".json"), encoded)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def load_field_workspace(path: str | Path) -> tuple[FieldDataset, tuple[Sensor, ...]]:
    raw = _read(path, ".json", 8_000_000)
    try:
        document = json.loads(raw, object_pairs_hook=_object)
        if (not isinstance(document, dict) or set(document) != {"schema", "metadata", "source_sha256", "samples", "sensors", "workspace_sha256"}
                or document["schema"] != SCHEMA):
            raise ValueError("Unsupported field workspace")
        digest = document.pop("workspace_sha256")
        if _digest(document) != digest:
            raise ValueError("Workspace failed integrity check")
        if not isinstance(document["samples"], list) or len(document["samples"]) > MAX_SAMPLES:
            raise ValueError("Invalid field samples")
        if not isinstance(document["sensors"], list) or len(document["sensors"]) > 256:
            raise ValueError("Invalid sensor layout")
        samples = []
        for sample in document["samples"]:
            if set(sample) != {"scenario", "point_id", "position_m", "field"}:
                raise ValueError("Invalid sample fields")
            if not isinstance(sample["field"], list) or len(sample["field"]) != 3:
                raise ValueError("Invalid complex field")
            fields = []
            for pair in sample["field"]:
                if not isinstance(pair, list) or len(pair) != 2 or any(type(value) not in (int, float) for value in pair):
                    raise ValueError("Invalid real/imaginary pair")
                fields.append(complex(*pair))
            samples.append(FieldSample(sample["scenario"], sample["point_id"], tuple(sample["position_m"]), tuple(fields)))
        data = FieldDataset(FieldMetadata(**document["metadata"]), tuple(samples), document["source_sha256"])
        sensors = tuple(Sensor(item["point_id"], tuple(item["position_m"]), tuple(item["axis"]))
                        for item in document["sensors"] if set(item) == {"point_id", "position_m", "axis"})
        if len(sensors) != len(document["sensors"]):
            raise ValueError("Invalid sensor fields")
        validate_dataset(data)
        validate_layout(sensors)
        return data, sensors
    except (TypeError, KeyError, AttributeError, OverflowError, RecursionError, UnicodeError) as exc:
        raise ValueError("Invalid field workspace") from exc


def _csv(path, columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([safe_csv_cell(value) if value is not None else "" for value in row])
    return _atomic_text(_path(path, ".csv"), stream.getvalue())


def write_sensor_layout_csv(path: str | Path, sensors: tuple[Sensor, ...]) -> Path:
    validate_layout(sensors)
    return _csv(path, ("point_id", "x_m", "y_m", "z_m", "nx", "ny", "nz"),
                [(sensor.point_id, *sensor.position_m, *(a / math.hypot(*sensor.axis) for a in sensor.axis)) for sensor in sensors])


def write_field_readings_csv(path: str | Path, data: FieldDataset, sensors: tuple[Sensor, ...],
                             scenario: str, reference: str) -> Path:
    readings = analyze_field_samples(data, sensors, scenario, reference)
    meta = asdict(data.metadata)
    meta["import_coordinate_unit"] = meta.pop("coordinate_unit")
    meta["import_field_unit"] = meta.pop("field_unit")
    columns = ("sensor_id", "scenario", "reference", "status", "reference_status", "x_m", "y_m", "z_m",
               "nx", "ny", "nz", "projected_real_t", "projected_imag_t", "amplitude_t", "phase_deg",
               "reference_real_t", "reference_imag_t", "reference_amplitude_t",
               "amplitude_change_t", "phase_change_deg", *meta, "source_csv_sha256", "quantity")
    rows = []
    for reading in readings:
        value, baseline = reading.projected_t, reading.reference_t
        rows.append((reading.sensor.point_id, scenario, reference, reading.status, reading.reference_status,
                     *reading.sensor.position_m, *(a/math.hypot(*reading.sensor.axis) for a in reading.sensor.axis),
                     value.real if value is not None else None,
                     value.imag if value is not None else None, reading.amplitude_t, reading.phase_deg,
                     baseline.real if baseline is not None else None, baseline.imag if baseline is not None else None,
                     abs(baseline) if baseline is not None else None, reading.amplitude_change_t,
                     reading.phase_change_deg, *meta.values(), data.source_sha256,
                     "Ideal-axis field projection, not calibrated MTJ voltage"))
    return _csv(path, columns, rows)
