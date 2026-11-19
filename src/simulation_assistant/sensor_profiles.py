"""Declared sensor/design limits, not an authenticated datasheet or calibration."""
import math
from dataclasses import dataclass

from simulation_assistant.field_samples import FIELD_UNITS
from simulation_assistant.model_briefs import _text

FREQUENCY_UNITS = {'Hz': 1., 'kHz': 1e3, 'MHz': 1e6}
BASES = ('hypothetical', 'documented')
FIELD_PURPOSES = ('unknown', 'charging-coil-ac', 'vehicle-signature')


@dataclass(frozen=True)
class StatedRange:
    low: float
    high: float
    unit: str
    source: str
    conditions: str


@dataclass(frozen=True)
class StatedValue:
    value: float
    unit: str
    source: str
    conditions: str


@dataclass(frozen=True)
class SensorProfile:
    name: str
    device: str = ''
    basis: str = 'hypothetical'
    target_field: str = 'unknown'
    frequency: StatedRange | None = None
    field: StatedRange | None = None
    sensitivity: StatedValue | None = None
    noise: StatedValue | None = None
    notes: str = ''


def finite_number(value, limit=1e100):
    if type(value) not in (int, float) or abs(value) > limit or not math.isfinite(value):
        raise ValueError('Use finite literal numbers within the supported limits, not booleans')


def range_si(spec):
    units = FREQUENCY_UNITS if spec.unit in FREQUENCY_UNITS else FIELD_UNITS
    return spec.low*units[spec.unit], spec.high*units[spec.unit]


def validate_profile(profile: SensorProfile) -> None:
    if not isinstance(profile, SensorProfile):
        raise ValueError('Expected a sensor profile')
    for name, maximum in (('name', 120), ('device', 160), ('basis', 20), ('target_field', 30), ('notes', 1000)):
        _text(getattr(profile, name), name, maximum, name in ('name', 'basis', 'target_field'))
    if profile.basis not in BASES or profile.target_field not in FIELD_PURPOSES:
        raise ValueError('Choose a supported profile basis and field purpose')
    if profile.basis == 'documented' and not profile.device:
        raise ValueError('A documented profile requires a named device/model; sources are user-recorded, not authenticated')
    for name in ('frequency', 'field', 'sensitivity', 'noise'):
        spec = getattr(profile, name)
        if spec is None:
            continue
        expected = StatedRange if name in ('frequency', 'field') else StatedValue
        if not isinstance(spec, expected):
            raise ValueError('Invalid specification: '+name)
        for key, maximum in (('unit', 40), ('source', 400), ('conditions', 400)):
            _text(getattr(spec, key), name+' '+key, maximum, True)
        if expected is StatedValue:
            finite_number(spec.value)
            if spec.value <= 0:
                raise ValueError('Known sensitivity/noise must be positive; leave unknown values blank')
        else:
            finite_number(spec.low)
            finite_number(spec.high)
            units = FREQUENCY_UNITS if name == 'frequency' else FIELD_UNITS
            if spec.unit not in units or spec.low > spec.high:
                raise ValueError('Invalid ordered range or unsupported '+name+' unit')
            low, high = range_si(spec)
            if name == 'frequency' and (low < 0 or high > 1e12):
                raise ValueError('Frequency bounds must be in 0..1e12 Hz')
            if name == 'field' and max(abs(low), abs(high)) > 1e6:
                raise ValueError('Field bounds exceed 1e6 T')
