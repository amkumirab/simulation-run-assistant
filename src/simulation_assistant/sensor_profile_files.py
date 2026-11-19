"""Portable profile declarations with corruption checks, never imported approval."""
import json
from dataclasses import asdict

from simulation_assistant.geometry_files import _digest, _path, _write
from simulation_assistant.model_briefs import _object
from simulation_assistant.sensor_profiles import SensorProfile, StatedRange, StatedValue, validate_profile

SCHEMA = 'wpt.sensor-profile.v1'
MAX_BYTES = 262144


def profile_digest(profile: SensorProfile) -> str:
    validate_profile(profile)
    return _digest({'schema': SCHEMA, **asdict(profile)})


def profile_document(profile: SensorProfile) -> dict:
    validate_profile(profile)
    return {'schema': SCHEMA, **asdict(profile), 'profile_sha256': profile_digest(profile)}


def read_profile_document(document: dict) -> SensorProfile:
    try:
        if (not isinstance(document, dict) or document.get('schema') != SCHEMA
                or set(document) != {'schema', 'profile_sha256', *SensorProfile.__dataclass_fields__}):
            raise ValueError('Unsupported sensor profile document')
        fields = {k: v for k, v in document.items() if k != 'profile_sha256'}
        if _digest(fields) != document['profile_sha256']:
            raise ValueError('Sensor profile failed integrity check')
        fields.pop('schema')
        for name in ('frequency', 'field', 'sensitivity', 'noise'):
            row = fields[name]
            if row is None:
                continue
            cls = StatedRange if name in ('frequency', 'field') else StatedValue
            if not isinstance(row, dict) or set(row) != set(cls.__dataclass_fields__):
                raise ValueError('Invalid specification fields: '+name)
            fields[name] = cls(**row)
        result = SensorProfile(**fields)
        validate_profile(result)
        return result
    except (TypeError, KeyError, OverflowError, RecursionError, AttributeError) as exc:
        raise ValueError('Invalid sensor profile') from exc


def load_sensor_profile(path) -> SensorProfile:
    target = _path(path, '.json')
    if not target.is_file():
        raise ValueError('Select a regular sensor profile JSON file')
    with target.open('rb') as stream:
        raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Sensor profile exceeds 256 KiB')
    try:
        return read_profile_document(json.loads(raw.decode('utf8'), object_pairs_hook=_object))
    except (UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError('Invalid sensor profile JSON') from exc


def save_sensor_profile(path, profile: SensorProfile):
    text = json.dumps(profile_document(profile), indent=2, allow_nan=False)+'\n'
    if len(text.encode('utf8')) > MAX_BYTES:
        raise ValueError('Sensor profile exceeds 256 KiB')
    return _write(_path(path, '.json'), text)
