"""Single-axis declared-limit screening; never a calibrated sensor response."""
import math
from dataclasses import dataclass

from simulation_assistant.sensor_field_overlay import SensorFieldOverlay, analyze_overlay
from simulation_assistant.sensor_placement import unit_axis
from simulation_assistant.sensor_profile_files import profile_digest
from simulation_assistant.sensor_profiles import FIELD_PURPOSES, SensorProfile, finite_number, range_si, validate_profile

WITHIN = 'within declared limits'
OUTSIDE = 'outside declared limits'
UNKNOWN = 'insufficient information'


@dataclass(frozen=True)
class LimitCheck:
    status: str
    reason: str


@dataclass(frozen=True)
class SensorLimitRow:
    sensor_id: str
    scenario: str
    sample_status: str
    peak_axis_t: float | None
    dc_axis_t: float | None
    minimum_t: float | None
    maximum_t: float | None
    frequency: LimitCheck
    field: LimitCheck

    @property
    def status(self):
        statuses = (self.frequency.status, self.field.status)
        return OUTSIDE if OUTSIDE in statuses else UNKNOWN if UNKNOWN in statuses else WITHIN


@dataclass(frozen=True)
class SensorAssessment:
    profile: SensorProfile
    profile_sha256: str
    overlay: SensorFieldOverlay
    sampled_field: str
    dc_bias_t: tuple[float, float, float] | None
    conditions_confirmed: bool
    context: LimitCheck
    rows: tuple[SensorLimitRow, ...]

    @property
    def scope(self):
        if self.profile.basis == 'hypothetical':
            return 'ASSUMPTION-BASED SCREENING - no physical sensor implied'
        return 'USER-RECORDED DOCUMENTED LIMITS - sources not authenticated; no hardware validation'


def _range_check(spec, low, high, label):
    if spec is None:
        return LimitCheck(UNKNOWN, 'No declared '+label+' range')
    allowed_low, allowed_high = range_si(spec)
    status = WITHIN if allowed_low <= low and high <= allowed_high else OUTSIDE
    return LimitCheck(status, f'{label}: [{low!r}, {high!r}] vs [{allowed_low!r}, {allowed_high!r}] in SI')


def assess_sensor_limits(profile: SensorProfile, overlay: SensorFieldOverlay, *, sampled_field: str,
                         dc_bias_t: tuple[float, float, float] | None,
                         conditions_confirmed: bool) -> SensorAssessment:
    """Screen known limits only. Bias is a declared uniform global B vector.

    Unknown bias, conditions, limits and sampled fields never receive defaults.
    A known numeric violation wins over other unavailable checks in a row.
    """
    validate_profile(profile)
    if not isinstance(overlay, SensorFieldOverlay):
        raise ValueError('Analyze an approved saved-field overlay first')
    checked = analyze_overlay(overlay.snapshot, overlay.sensors, overlay.bundle, overlay.current_source.scenario,
                              overlay.reference_source.scenario, comparable_frames=True, geometry_matches_state=True)
    if checked != overlay:
        raise ValueError('Overlay changed; analyze the current approved inputs again')
    if not isinstance(sampled_field, str) or sampled_field not in FIELD_PURPOSES or type(conditions_confirmed) is not bool:
        raise ValueError('Declare a supported sampled-field purpose and explicit boolean confirmation')
    if dc_bias_t is not None:
        if not isinstance(dc_bias_t, tuple) or len(dc_bias_t) != 3:
            raise ValueError('DC bias must be an explicit three-component global B tuple, or unknown')
        for value in dc_bias_t:
            finite_number(value, 1e6)
    reasons = []
    if not conditions_confirmed:
        reasons.append('Confirm supplied profile conditions and uniform DC bias applicability')
    if 'unknown' in (sampled_field, profile.target_field):
        reasons.append('Declare both intended and sampled field purposes')
    elif sampled_field != profile.target_field:
        reasons.append('Field purposes differ; charging fields are not inferred vehicle signatures')
    context = LimitCheck(UNKNOWN, '; '.join(reasons)) if reasons else LimitCheck(WITHIN, 'User-declared comparable conditions and field purpose')
    frequency = (context if reasons else _range_check(profile.frequency, overlay.bundle.data.metadata.frequency_hz,
                                                    overlay.bundle.data.metadata.frequency_hz, 'frequency (Hz)'))
    factor = math.sqrt(2.) if overlay.bundle.data.metadata.phasor_convention == 'rms' else 1.
    rows = []
    for reading in overlay.readings:
        axis = unit_axis(reading.sensor)
        bias = None if dc_bias_t is None else sum(n*b for n, b in zip(axis, dc_bias_t))
        for source, value, sample_status in (
            (overlay.current_source, reading.projected_t, reading.status),
            (overlay.reference_source, reading.reference_t, reading.reference_status),
        ):
            peak = None if value is None else factor*abs(value)
            low = None if peak is None or bias is None else bias-peak
            high = None if peak is None or bias is None else bias+peak
            if reasons:
                field = context
            elif value is None:
                field = LimitCheck(UNKNOWN, 'Saved sample unavailable: '+sample_status)
            elif dc_bias_t is None:
                field = LimitCheck(UNKNOWN, 'Uniform DC bias unknown; AC phasors do not establish zero bias')
            else:
                field = _range_check(profile.field, low, high, 'axis B (T)')
            rows.append(SensorLimitRow(reading.sensor.point_id, source.scenario, sample_status,
                                       peak, bias, low, high, frequency, field))
    return SensorAssessment(profile, profile_digest(profile), overlay, sampled_field, dc_bias_t,
                            conditions_confirmed, context, tuple(rows))
