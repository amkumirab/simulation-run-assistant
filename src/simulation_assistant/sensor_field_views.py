"""Selected-sensor annotations and auditable saved-field vector exports."""
import json
import cmath
import math
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import asdict

from simulation_assistant.geometry_files import _path, _write
from simulation_assistant.sensor_field_overlay import analyze_overlay, matching_sample
from simulation_assistant.sensor_placement import project_placement
from simulation_assistant.sensor_placement_views import SELECTED, TEXT, placement_svg

NS = 'http://www.w3.org/2000/svg'


def number(value, scale=1., signed=False):
    return 'unavailable' if value is None else format(value*scale, '+.6g' if signed else '.6g')


def overlay_label(row):
    label = row.sensor.point_id[:20]
    return (f'{label}: {number(row.amplitude_t, 1e6)} uT ({row.status})\n'
            f'Delta: {number(row.amplitude_change_t, 1e6, True)} uT | ref {row.reference_status}')


def annotation(view, overlay, selected_sensor):
    projected = next((s for s in view.sensors if s.sensor.point_id == selected_sensor), None)
    row = next((r for r in overlay.readings if r.sensor.point_id == selected_sensor), None)
    if projected is None or row is None:
        return None
    x, y = projected.point
    # Keep a bounded text block inside either panel, independent of axis direction.
    return max(16., min(view.width-355., x-40.)), max(80., min(view.height-95., y+32.)), overlay_label(row)


def draw_overlay(canvas, view, overlay, selected_sensor):
    item = annotation(view, overlay, selected_sensor)
    if item:
        x, y, text = item
        canvas.create_rectangle(x-4, y-4, x+346, y+36, fill='white', outline=SELECTED, tags='field-overlay')
        canvas.create_text(x, y, text=text, anchor='nw', fill=SELECTED, font=('Segoe UI', 9), tags='field-overlay')


def _components(sample):
    return None if sample is None else [[v.real, v.imag] for v in sample.field]


def reading_record(overlay, row):
    return dict(sensor_id=row.sensor.point_id, status=row.status, reference_status=row.reference_status,
                amplitude_t=row.amplitude_t, amplitude_change_t=row.amplitude_change_t,
                reference_amplitude_t=None if row.reference_t is None else abs(row.reference_t),
                phase_deg=row.phase_deg, phase_change_deg=row.phase_change_deg,
                projected_t=None if row.projected_t is None else [row.projected_t.real, row.projected_t.imag],
                reference_t=None if row.reference_t is None else [row.reference_t.real, row.reference_t.imag],
                current_components_t=_components(matching_sample(overlay, row.sensor.point_id)),
                reference_components_t=_components(matching_sample(overlay, row.sensor.point_id, reference=True)))


def source_text(source):
    state = source.state
    return (f'{source.scenario} | {state.dataset}/{state.solver} | outer {state.outer}, inner {state.inner} | '
            f'{state.frequency_hz:g} Hz | parameters: {state.parameters}\nModel SHA: {source.model_sha256}')


def detail_text(overlay, sensor_id):
    row = next(r for r in overlay.readings if r.sensor.point_id == sensor_id)
    lines = [f'{sensor_id} | ideal-axis projection, not calibrated sensor output',
             f'Current phase: {number(row.phase_deg)} deg | phase change: {number(row.phase_change_deg)} deg']
    for label, source, ref, value, status in (
        ('Current', overlay.current_source, False, row.projected_t, row.status),
        ('Reference', overlay.reference_source, True, row.reference_t, row.reference_status),
    ):
        amplitude = None if value is None else abs(value)
        phase = math.degrees(cmath.phase(value)) if value else None
        lines.extend((label+': '+source_text(source),
                      f'Status: {status} | amplitude: {number(amplitude, 1e6)} uT | phase: {number(phase)} deg',
                      'Axis phasor (T): '+str(value)))
        sample = matching_sample(overlay, sensor_id, reference=ref)
        if sample is not None:
            for name, field in zip(('Bx', 'By', 'Bz'), sample.field):
                lines.append(f'{name} (T): real={field.real!r}, imag={field.imag!r}')
    return '\n'.join(lines).encode('ascii', 'backslashreplace').decode('ascii')


def overlay_svg(overlay, domains, *, layout_label, selected_sensor=None):
    checked = analyze_overlay(overlay.snapshot, overlay.sensors, overlay.bundle, overlay.current_source.scenario,
                              overlay.reference_source.scenario, comparable_frames=True, geometry_matches_state=True)
    if checked != overlay:
        raise ValueError('Overlay changed; analyze the approved inputs again')
    root = ET.fromstring(placement_svg(overlay.snapshot, overlay.sensors, domains, comparable_frames=True,
                                     layout_label=layout_label, selected_sensor=selected_sensor))
    metadata_node = root.find('{'+NS+'}metadata')
    metadata = json.loads(metadata_node.text)
    metadata.update(schema='wpt.sensor-field-overlay.v1', geometry_matches_state=True,
                    current=asdict(overlay.current_source), reference=asdict(overlay.reference_source),
                    field_metadata=asdict(overlay.bundle.data.metadata), workspace_sha256=overlay.bundle.workspace_sha256,
                    evidence_sha256=overlay.bundle.evidence_sha256, csv_sha256=overlay.bundle.data.source_sha256,
                    readings=[reading_record(overlay, row) for row in overlay.readings])
    metadata_node.text = json.dumps(metadata, sort_keys=True, allow_nan=False)
    root.find('{'+NS+'}title').text = 'Sensor Field Overlay'
    root.find('{'+NS+'}text').text = 'Sensor Field Overlay'
    root.find('{'+NS+'}desc').text += ' Selected-sensor ideal-axis field annotation; complete numeric comparison follows. Current geometry only.'
    for group, plane in zip(root.findall('{'+NS+'}g'), ('XY', 'XZ')):
        view = project_placement(overlay.snapshot, overlay.sensors, domains, plane, comparable_frames=True)
        item = annotation(view, overlay, selected_sensor)
        if item:
            x, y, label = item
            ET.SubElement(group, '{'+NS+'}rect', x=str(x-4), y=str(y-4), width='350', height='42', fill='white', stroke=SELECTED)
            for i, line in enumerate(label.splitlines()):
                ET.SubElement(group, '{'+NS+'}text', x=str(x), y=str(y+10+17*i), fill=SELECTED).text = line
    meta = overlay.bundle.data.metadata
    notes = ['SAVED FIELD OVERLAY | Current geometry only; no reference geometry is inferred.',
             'Geometry-state correspondence and comparable frames are user-declared, not automatically proven.',
             'Ideal-axis phasor amplitude (uT), signed current minus reference amplitude; not vector-difference magnitude.',
             f'{meta.frequency_hz:g} Hz | {meta.phasor_convention} | {meta.excitation} | {meta.phase_reference}',
             'Not calibrated MTJ voltage, vehicle signature or detection approval. No interpolation or new solve.',
             'Current: '+source_text(overlay.current_source), 'Reference: '+source_text(overlay.reference_source),
             'Workspace SHA: '+overlay.bundle.workspace_sha256, 'Evidence SHA: '+overlay.bundle.evidence_sha256]
    for row in overlay.readings:
        notes.extend((overlay_label(row), detail_text(overlay, row.sensor.point_id)))
    lines = [part for note in notes for line in note.splitlines()
             for part in textwrap.wrap(line.encode('ascii', 'backslashreplace').decode('ascii'), 125)]
    top = int(root.get('height'))+24
    height = top+18*len(lines)+20
    root.set('height', str(height))
    root.set('viewBox', f'0 0 1200 {height}')
    root.find('{'+NS+'}rect').set('height', str(height))
    for i, line in enumerate(lines):
        ET.SubElement(root, '{'+NS+'}text', x='20', y=str(top+18*i), fill=TEXT).text = line
    ET.register_namespace('', NS)
    return ET.tostring(root, encoding='unicode')+'\n'


def save_overlay_svg(path, overlay, domains, **options):
    return _write(_path(path, '.svg'), overlay_svg(overlay, domains, **options))
