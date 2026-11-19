"""Portable declared-limit evidence; a report never restores trusted approval."""
import json
from dataclasses import asdict

from simulation_assistant.geometry_files import _digest, _path, _write, snapshot_digest
from simulation_assistant.sensor_field_views import reading_record
from simulation_assistant.sensor_limit_checks import SensorAssessment, assess_sensor_limits
from simulation_assistant.sensor_placement import layout_digest
from simulation_assistant.sensor_profile_files import profile_document


def assessment_document(result: SensorAssessment) -> dict:
    if not isinstance(result, SensorAssessment):
        raise ValueError('Evaluate current profile and field inputs before exporting a report')
    checked = assess_sensor_limits(result.profile, result.overlay, sampled_field=result.sampled_field,
                                   dc_bias_t=result.dc_bias_t, conditions_confirmed=result.conditions_confirmed)
    if checked != result:
        raise ValueError('Assessment changed; evaluate the current inputs again')
    overlay = result.overlay
    document = dict(schema='wpt.sensor-limit-report.v1', scope=result.scope, profile=profile_document(result.profile),
        sources=dict(current=asdict(overlay.current_source), reference=asdict(overlay.reference_source),
                     workspace_sha256=overlay.bundle.workspace_sha256, evidence_sha256=overlay.bundle.evidence_sha256,
                     csv_sha256=overlay.bundle.data.source_sha256, snapshot_sha256=snapshot_digest(overlay.snapshot),
                     layout_sha256=layout_digest(overlay.sensors)),
        field_metadata=asdict(overlay.bundle.data.metadata),
        sensors=[asdict(s) for s in overlay.sensors],
        context=dict(sampled_field=result.sampled_field, dc_bias_t=result.dc_bias_t,
                     conditions_confirmed=result.conditions_confirmed, check=asdict(result.context),
                     geometry_matches_state='user-declared in accepted overlay', comparable_frames='user-declared in accepted overlay'),
        assumptions=dict(waveform='single-frequency sinusoidal AC phasor', dc_bias='user-declared uniform global XYZ vector or unknown',
                         range='signed sensitivity-axis B only; no transverse/vector/saturation check',
                         peak_conversion='AC peak=abs(n.B) for peak phasors; AC peak=sqrt(2)*abs(n.B) for RMS phasors',
                         sensitivity_used=False, noise_used=False,
                         hardware_validation=False, detectability_evaluated=False),
        field_comparison=[reading_record(overlay, r) for r in overlay.readings],
        rows=[{**asdict(row), 'status': row.status} for row in result.rows])
    document['report_sha256'] = _digest(document)
    return document


def save_sensor_assessment(path, result: SensorAssessment):
    text = json.dumps(assessment_document(result), indent=2, allow_nan=False)+'\n'
    if len(text.encode('utf8')) > 2_000_000:
        raise ValueError('Sensor limit report exceeds 2 MB')
    return _write(_path(path, '.json'), text)
