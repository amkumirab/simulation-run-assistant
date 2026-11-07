"""Portable saved-geometry snapshots and explicitly proposed brief drafts."""
import csv
import hashlib
import io
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from simulation_assistant.csv_export import safe_csv_cell
from simulation_assistant.geometry_inspector import GeometryPart, GeometrySnapshot, validate_snapshot
from simulation_assistant.model_briefs import BriefEntry, ModelBrief, validate_brief

SCHEMA = 'wpt.geometry-snapshot.v1'
BOUND_NAMES = ('xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax')


def selected_parts(data, domains, maximum=256):
    validate_snapshot(data)
    if (not isinstance(domains, tuple) or not 1 <= len(domains) <= maximum
            or any(type(d) is not int for d in domains) or len(domains) != len(set(domains))):
        raise ValueError(f'Explicitly select 1-{maximum} unique domains')
    index = {part.domain: part for part in data.parts}
    if any(d not in index for d in domains):
        raise ValueError('Selected domain is missing from this snapshot')
    return tuple(index[d] for d in domains)


def _path(path, suffix):
    target = Path(path)
    if target.suffix.lower() != suffix:
        raise ValueError('Choose a '+suffix+' file')
    return target


def _write(path, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=path.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return path.resolve()


def _digest(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def snapshot_digest(data: GeometrySnapshot) -> str:
    """Canonical portable content identity, distinct from the source MPH hash."""
    validate_snapshot(data)
    return _digest({'schema': SCHEMA, **asdict(data)})


def save_snapshot(path, data):
    validate_snapshot(data)
    document = {'schema': SCHEMA, **asdict(data)}
    document['snapshot_sha256'] = snapshot_digest(data)
    text = json.dumps(document, indent=2, allow_nan=False)+'\n'
    if len(text.encode('utf-8')) > 1_000_000:
        raise ValueError('Snapshot exceeds 1 MB')
    return _write(_path(path, '.json'), text)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def load_snapshot(path):
    with _path(path, '.json').open('rb') as stream:
        raw = stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError('Snapshot exceeds 1 MB')
    try:
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=_object)
        if (not isinstance(document, dict) or set(document) != {'schema', 'snapshot_sha256', *GeometrySnapshot.__dataclass_fields__}
                or document['schema'] != SCHEMA):
            raise ValueError('Unsupported geometry snapshot')
        digest = document.pop('snapshot_sha256')
        if _digest(document) != digest:
            raise ValueError('Geometry snapshot failed integrity check')
        rows = document['parts']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
            raise ValueError('Use 1-256 saved domains')
        parts = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(GeometryPart.__dataclass_fields__) or not isinstance(row['bounds_m'], list):
                raise ValueError('Invalid domain fields')
            parts.append(GeometryPart(row['domain'], row['selections'], tuple(row['bounds_m'])))
        data = GeometrySnapshot(document['source_sha256'], document['component'], document['geometry'],
                                document['length_unit'], document['engine_version'], tuple(parts))
        validate_snapshot(data)
        return data
    except (UnicodeError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        raise ValueError('Invalid geometry snapshot') from exc


def brief_from_geometry(data, domains, name, revision):
    entries = []
    for part in selected_parts(data, domains, 16):
        source = f'COMSOL geometry {data.source_sha256} {data.component}/{data.geometry}, domain {part.domain}; approximate envelope'
        for bound, value in zip(BOUND_NAMES, part.bounds_m):
            entries.append(BriefEntry('Geometry', f'Domain {part.domain} {bound}', format(value*1000, '.12g'), 'mm',
                                      'proposed', source, ''))
    brief = ModelBrief(name, revision, data.source_sha256, tuple(entries))
    validate_brief(brief)
    return brief


def export_geometry_csv(path, data, domains):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(('domain', 'selections', *(name+'_mm' for name in BOUND_NAMES), 'source_sha256', 'quantity'))
    for part in selected_parts(data, domains):
        writer.writerow((part.domain, safe_csv_cell(part.selections), *(v*1000 for v in part.bounds_m),
                         data.source_sha256, 'approximate global axis-aligned bounds; not solid geometry or clearance'))
    return _write(_path(path, '.csv'), stream.getvalue())
