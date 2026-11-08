"""Portable comparison inputs only; never persist frame approval or results."""
import json
from dataclasses import asdict, dataclass

from simulation_assistant.geometry_comparison import DomainPair, validate_pairs, validate_tolerance_mm
from simulation_assistant.geometry_files import (
    _digest, _object, _path, _write, read_snapshot_document, snapshot_document,
)
from simulation_assistant.geometry_inspector import GeometrySnapshot, validate_snapshot

SCHEMA = 'wpt.geometry-comparison-session.v1'
MAX_BYTES = 2_100_000


@dataclass(frozen=True)
class GeometryComparisonSession:
    baseline: GeometrySnapshot
    candidate: GeometrySnapshot
    pairs: tuple[DomainPair, ...]
    tolerance_mm: float = .01


def validate_session(session: GeometryComparisonSession) -> None:
    if not isinstance(session, GeometryComparisonSession):
        raise ValueError('Expected a geometry comparison session')
    for source in (session.baseline, session.candidate):
        if not isinstance(source, GeometrySnapshot):
            raise ValueError('A session needs two geometry snapshots')
        validate_snapshot(source)
    if not isinstance(session.pairs, tuple) or len(session.pairs) > 256:
        raise ValueError('Save 0-256 explicit corresponding domain pairs')
    if session.pairs:
        validate_pairs(session.baseline, session.candidate, session.pairs)
    validate_tolerance_mm(session.tolerance_mm)


def save_session(path, session: GeometryComparisonSession):
    """Validate first, then atomically write a user-selected JSON target."""
    validate_session(session)
    document = {
        'schema': SCHEMA,
        'baseline': snapshot_document(session.baseline),
        'candidate': snapshot_document(session.candidate),
        'pairs': [asdict(pair) for pair in session.pairs],
        'tolerance_mm': session.tolerance_mm,
    }
    document['session_sha256'] = _digest(document)
    text = json.dumps(document, indent=2, allow_nan=False)+'\n'
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Comparison session exceeds 2,100,000 bytes')
    return _write(_path(path, '.json'), text)


def load_session(path) -> GeometryComparisonSession:
    """Read bounded untrusted input; no imported approval or computed data exist."""
    with _path(path, '.json').open('rb') as stream:
        raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Comparison session exceeds 2,100,000 bytes')
    try:
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=_object)
        if (not isinstance(document, dict)
                or set(document) != {'schema', 'baseline', 'candidate', 'pairs', 'tolerance_mm', 'session_sha256'}
                or document['schema'] != SCHEMA):
            raise ValueError('Unsupported geometry comparison session')
        checksum = document.pop('session_sha256')
        if _digest(document) != checksum:
            raise ValueError('Comparison session failed integrity check')
        rows = document['pairs']
        if not isinstance(rows, list) or len(rows) > 256:
            raise ValueError('Save 0-256 explicit corresponding domain pairs')
        pairs = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(DomainPair.__dataclass_fields__):
                raise ValueError('Invalid pair fields')
            pairs.append(DomainPair(**row))
        session = GeometryComparisonSession(
            read_snapshot_document(document['baseline']), read_snapshot_document(document['candidate']),
            tuple(pairs), document['tolerance_mm'],
        )
        validate_session(session)
        return session
    except (UnicodeError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        raise ValueError('Invalid geometry comparison session') from exc
