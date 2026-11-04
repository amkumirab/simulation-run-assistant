"""Saved geometry envelopes, not reconstructed solids or certified clearances."""
from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from simulation_assistant.comsol_readonly import model_digest, run_helper

TAG = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,79}\Z')
SCALES = {'m': 1., 'cm': .01, 'mm': .001, 'um': 1e-6, 'nm': 1e-9}
COLUMNS = ('domain', 'selections', 'xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax')


@dataclass(frozen=True)
class GeometryPart:
    domain: int
    selections: str
    bounds_m: tuple[float, ...]


@dataclass(frozen=True)
class GeometrySnapshot:
    source_sha256: str
    component: str
    geometry: str
    length_unit: str
    engine_version: str
    parts: tuple[GeometryPart, ...]


def validate_snapshot(data: GeometrySnapshot) -> None:
    if not isinstance(data, GeometrySnapshot) or not isinstance(data.source_sha256, str) or not re.fullmatch('[0-9a-f]{64}', data.source_sha256):
        raise ValueError('Geometry snapshot requires a source SHA-256')
    if any(not isinstance(tag, str) or not TAG.fullmatch(tag) for tag in (data.component, data.geometry)):
        raise ValueError('Invalid component or geometry tag')
    if not isinstance(data.length_unit, str) or data.length_unit not in SCALES:
        raise ValueError('Unsupported geometry unit')
    if (not isinstance(data.engine_version, str) or not 1 <= len(data.engine_version) <= 80
            or any(not 32 <= ord(c) < 127 for c in data.engine_version)):
        raise ValueError('Invalid engine version')
    if not isinstance(data.parts, tuple) or not 1 <= len(data.parts) <= 256:
        raise ValueError('Use 1-256 saved domains')
    seen = set()
    for part in data.parts:
        if not isinstance(part, GeometryPart) or type(part.domain) is not int or not 1 <= part.domain <= 100000 or part.domain in seen:
            raise ValueError('Domain IDs must be unique positive integers')
        seen.add(part.domain)
        if (not isinstance(part.selections, str) or len(part.selections) > 400
                or any(not 32 <= ord(c) < 127 for c in part.selections)):
            raise ValueError('Invalid selection tags')
        box = part.bounds_m
        if (not isinstance(box, tuple) or len(box) != 6 or any(type(v) not in (int, float) or abs(v) > 1e6 or not math.isfinite(v) for v in box)
                or any(box[i] >= box[i+1] for i in (0, 2, 4))):
            raise ValueError('Each 3D domain needs six finite strictly ordered bounds in m')


def read_geometry(raw: bytes, digest: str) -> GeometrySnapshot:
    if not isinstance(raw, bytes) or len(raw) > 1_000_000:
        raise ValueError('Geometry output exceeds 1 MB')
    try:
        rows = list(csv.reader(io.StringIO(raw.decode('utf-8')), delimiter='\t', strict=True))
        if len(rows) < 3 or len(rows) > 258 or len(rows[0]) != 5 or rows[0][0] != 'geometry' or tuple(rows[1]) != COLUMNS:
            raise ValueError('Invalid geometry protocol')
        _, component, geometry, unit, version = rows[0]
        if unit not in SCALES:
            raise ValueError('Unsupported geometry unit')
        parts = []
        for row in rows[2:]:
            if len(row) != 8:
                raise ValueError('Invalid domain row')
            parts.append(GeometryPart(int(row[0]), row[1], tuple(float(v)*SCALES[unit] for v in row[2:])))
        data = GeometrySnapshot(digest, component, geometry, unit, version, tuple(parts))
        validate_snapshot(data)
        return data
    except (UnicodeError, csv.Error, TypeError, OverflowError) as exc:
        raise ValueError('Invalid saved geometry data') from exc


def z_separation(lower: GeometryPart, upper: GeometryPart, declared_parallel: bool) -> float | None:
    """Global Z envelope separation only; not minimum distance or collision proof."""
    if declared_parallel is not True or lower.domain == upper.domain:
        return None
    a, b = lower.bounds_m, upper.bounds_m
    if b[4] < a[5] or any(max(a[i], b[i]) >= min(a[i+1], b[i+1]) for i in (0, 2)):
        return None
    return b[4]-a[5]


def inspect_geometry(model, executable, *, cancel_requested=lambda: False) -> GeometrySnapshot:
    digest = model_digest(model)
    raw = run_helper(model, executable, 'SavedGeometryInspector', 'geometry',
                     expected_sha256=digest, cancel_requested=cancel_requested)
    if model_digest(model) != digest:
        raise ValueError('Source model changed during geometry inspection; results rejected')
    return read_geometry(raw, digest)
