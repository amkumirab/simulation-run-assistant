"""User-declared model specifications; never a model or safety certification."""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from simulation_assistant.quantities import parse_quantity

SCHEMA = 'wpt.model-brief.v1'
MAX_BYTES = 262144
MAX_ENTRIES = 128
SECTIONS = ('Geometry', 'Layer stack', 'Materials', 'Excitation', 'Battery', 'Limits', 'Other')
STATUSES = ('unknown', 'assumed', 'proposed', 'confirmed')


@dataclass(frozen=True)
class BriefEntry:
    section: str
    name: str
    value: str = ''
    unit: str = ''
    status: str = 'unknown'
    source: str = ''
    reviewed_on: str = ''


@dataclass(frozen=True)
class ModelBrief:
    name: str
    revision: str
    model_sha256: str = ''
    entries: tuple[BriefEntry, ...] = ()


def _text(value, label, maximum, required=False):
    if (not isinstance(value, str) or len(value) > maximum
            or any(not 32 <= ord(char) <= 126 for char in value)
            or value != value.strip() or (required and not value)):
        raise ValueError(f'{label}: use {"1" if required else "0"}-{maximum} printable ASCII characters without edge spaces')


def validate_entry(entry: BriefEntry) -> None:
    """Validate declared provenance and literal units, not physical suitability."""
    if not isinstance(entry, BriefEntry):
        raise ValueError('Invalid brief entry')
    for name, maximum in (('section', 24), ('name', 80), ('value', 400), ('unit', 24),
                          ('status', 16), ('source', 400), ('reviewed_on', 10)):
        _text(getattr(entry, name), name, maximum, name in ('section', 'name', 'status'))
    if entry.section not in SECTIONS or entry.status not in STATUSES:
        raise ValueError('Choose a supported section and status')
    if entry.status == 'unknown':
        if entry.value:
            raise ValueError('Unknown entries must have an empty value')
    elif not entry.value or not entry.source:
        raise ValueError('Assumed, proposed and confirmed entries need a value and source')
    if entry.status == 'confirmed' and not entry.reviewed_on:
        raise ValueError('Confirmed entries need a review date')
    if entry.reviewed_on:
        try:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', entry.reviewed_on):
                raise ValueError()
            date.fromisoformat(entry.reviewed_on)
        except ValueError as exc:
            raise ValueError('Review date must be a real YYYY-MM-DD date') from exc
    if entry.unit:
        quantity = parse_quantity(f'{entry.value or "0"}[{entry.unit}]')
        if quantity is None or not math.isfinite(quantity.si_value):
            raise ValueError('Numeric values need a finite literal and supported unit; use 1 for counts')


def validate_brief(brief: ModelBrief) -> None:
    if not isinstance(brief, ModelBrief):
        raise ValueError('Invalid model brief')
    _text(brief.name, 'Model name', 120, True)
    _text(brief.revision, 'Revision', 80, True)
    _text(brief.model_sha256, 'Model SHA-256', 64)
    if brief.model_sha256 and not re.fullmatch('[0-9a-f]{64}', brief.model_sha256):
        raise ValueError('Model SHA-256 must be 64 lowercase hexadecimal characters or empty')
    if not isinstance(brief.entries, tuple) or len(brief.entries) > MAX_ENTRIES:
        raise ValueError('Use at most 128 entries')
    names = set()
    for entry in brief.entries:
        validate_entry(entry)
        key = (entry.section, entry.name.casefold())
        if key in names:
            raise ValueError('Entry names must be unique within their section')
        names.add(key)


def _json_path(path):
    target = Path(path)
    if target.suffix.lower() != '.json':
        raise ValueError('Choose a .json file, not a model or result file')
    return target


def save_model_brief(path: str | Path, brief: ModelBrief) -> Path:
    """Validate first; replace only the explicitly selected JSON destination."""
    validate_brief(brief)
    raw = (json.dumps({'schema': SCHEMA, **asdict(brief)}, indent=2, allow_nan=False)+'\n').encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('Model brief exceeds 256 KB')
    target = _json_path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target.resolve()


def _object(pairs):
    document = {}
    for key, value in pairs:
        if key in document:
            raise ValueError('Duplicate JSON field')
        document[key] = value
    return document


def load_model_brief(path: str | Path) -> ModelBrief:
    """Read a bounded exact schema; imported source text is never executed."""
    with _json_path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Model brief exceeds 256 KB')
    try:
        document = json.loads(raw.decode('utf-8'), object_pairs_hook=_object)
        if (not isinstance(document, dict) or set(document) != {'schema', *ModelBrief.__dataclass_fields__}
                or document['schema'] != SCHEMA):
            raise ValueError('Unsupported model brief schema or fields')
        entries = document['entries']
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            raise ValueError('Use at most 128 entries')
        parsed = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != set(BriefEntry.__dataclass_fields__):
                raise ValueError('Invalid entry fields')
            parsed.append(BriefEntry(**entry))
        brief = ModelBrief(document['name'], document['revision'], document['model_sha256'], tuple(parsed))
        validate_brief(brief)
        return brief
    except (UnicodeError, RecursionError, TypeError, KeyError, OverflowError) as exc:
        raise ValueError('Invalid model brief JSON') from exc
