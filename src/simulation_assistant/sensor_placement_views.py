"""Shared native/vector placement sketches with explicit numeric evidence."""
import json
import math
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from simulation_assistant.geometry_files import _path, _write, snapshot_digest
from simulation_assistant.sensor_placement import layout_digest, project_placement

TEXT, ENVELOPE, SENSOR, SELECTED, GRID = '#233954', '#2459ad', '#142d50', '#9b3f00', '#d7e0e8'
NOTICE = 'Approximate envelopes, not CAD, clearance, field readings or sensor detection approval.'


@dataclass(frozen=True)
class DrawingItem:
    kind: str
    coords: tuple[float, ...]
    text: str = ''
    color: str = TEXT
    width: int = 1
    dashed: bool = False
    anchor: str = 'w'


def placement_items(view, selected_sensor=None):
    items = [DrawingItem('text', (16, 18), view.plane+' | equal physical axis scale | mm'),
             DrawingItem('text', (16, 40), 'Dashed: envelopes. Dot/cross: normal +/-'+view.normal_axis+'.')]
    right, bottom = view.width-40, view.height-50
    for fraction in (0., .25, .5, .75, 1.):
        x, y = 70+fraction*(right-70), bottom-fraction*(bottom-70)
        items.extend((DrawingItem('line', (x, 70, x, bottom), color=GRID),
                      DrawingItem('line', (70, y, right, y), color=GRID),
                      DrawingItem('text', (x, bottom+16), f'{view.xmin_mm+(x-70)/view.scale:.5g}', anchor='e' if fraction == 1 else 'w'),
                      DrawingItem('text', (64, y), f'{view.ymin_mm+(bottom-y)/view.scale:.5g}', anchor='e')))
    items.extend((DrawingItem('line', (70, 70, 70, bottom, right, bottom)),
                  DrawingItem('text', (right, view.height-12), 'X (mm)', anchor='e'),
                  DrawingItem('text', (70, 58), view.plane[1]+' (mm)'),
                  DrawingItem('text', (16, view.height-12), 'Arrows: illustrative projected axes')))
    envelope_groups = {}
    for envelope in view.envelopes:
        envelope_groups.setdefault(envelope.bounds, []).append(envelope.domain)
    for bounds, domains in envelope_groups.items():
        items.append(DrawingItem('rect', bounds, color=ENVELOPE, width=2, dashed=True))
        a, b, c, d = bounds
        label = ', '.join('D'+str(domain) for domain in domains[:3])
        if len(domains) > 3:
            label += ' +'+str(len(domains)-3)+' envelopes'
        items.append(DrawingItem('text', (a+5, b+12), label, color=ENVELOPE))
    groups = {}
    for projected in view.sensors:
        groups.setdefault(projected.point, []).append(projected.sensor.point_id)
    for projected in view.sensors:
        sensor = projected.sensor
        x, y = projected.point
        chosen = sensor.point_id == selected_sensor
        color = SELECTED if chosen else SENSOR
        items.append(DrawingItem('oval', (x-5, y-5, x+5, y+5), color=color, width=2))
        if chosen:
            items.append(DrawingItem('oval', (x-9, y-9, x+9, y+9), color=color, width=3))
        members = groups[projected.point]
        representative = selected_sensor if selected_sensor in members else members[0]
        if sensor.point_id != representative:
            continue
        u, v = projected.axis_uv
        length = math.hypot(u, v)
        if length == 0 and (len(members) == 1 or chosen):
            if projected.normal_component > 0:
                items.append(DrawingItem('oval', (x-1.5, y-1.5, x+1.5, y+1.5), color=color, width=2))
            else:
                items.extend((DrawingItem('line', (x-3, y-3, x+3, y+3), color=color),
                              DrawingItem('line', (x-3, y+3, x+3, y-3), color=color)))
        if length >= 1e-6 and (len(members) == 1 or chosen):
            dx, dy = 28*u, -28*v
            end = (x+dx, y+dy)
            # Only the arrowhead uses a unit screen direction; the shaft keeps 3D projection length.
            hx, hy = dx/(28*length), dy/(28*length)
            head = min(6., 28*length*.4)
            items.extend((DrawingItem('line', (x, y, *end), color=color, width=2),
                          DrawingItem('line', (end[0]-head*hx-head*.5*hy, end[1]-head*hy+head*.5*hx,
                                               *end, end[0]-head*hx+head*.5*hy, end[1]-head*hy-head*.5*hx), color=color, width=2)))
        if chosen or len(view.sensors) <= 12:
            label = sensor.point_id if len(sensor.point_id) <= 20 else sensor.point_id[:17]+'...'
            if len(members) > 1 and not chosen:
                label = f'{len(members)} projected sensors'
            elif length < 1e-6 and chosen:
                label += f' | {"normal" if length == 0 else "near normal"} {view.normal_axis} {projected.normal_component:+.4g}'
            items.append(DrawingItem('text', (x+12, y-14), label, color=color,
                                     anchor='e' if x > view.width*.5 else 'w'))
            if chosen and len(members) > 1:
                items.append(DrawingItem('text', (x+12, y+16), f'{len(members)} projected sensors', color=color,
                                         anchor='e' if x > view.width*.5 else 'w'))
    return tuple(items)


def draw_placement(canvas, view, selected_sensor=None):
    canvas.delete('all')
    if view is None:
        canvas.create_text(20, 40, anchor='nw', text='Load geometry and sensors, select domains, then confirm comparable frames.',
                           width=max(200, canvas.winfo_width()-40), fill=TEXT)
        return
    for item in placement_items(view, selected_sensor):
        if item.kind == 'text':
            canvas.create_text(*item.coords, text=item.text, anchor=item.anchor, fill=item.color, font=('Segoe UI', 9))
        else:
            options = dict(outline=item.color, width=item.width)
            if item.dashed:
                options['dash'] = (5, 3)
            if item.kind == 'line':
                options['fill'] = options.pop('outline')
            getattr(canvas, {'line': 'create_line', 'rect': 'create_rectangle', 'oval': 'create_oval'}[item.kind])(*item.coords, **options)


def _svg_items(parent, view, selected_sensor):
    for item in placement_items(view, selected_sensor):
        values = dict(stroke=item.color, fill='none', **{'stroke-width': str(item.width)})
        if item.dashed:
            values['stroke-dasharray'] = '5 3'
        if item.kind == 'text':
            ET.SubElement(parent, 'text', x=str(item.coords[0]), y=str(item.coords[1]), fill=item.color,
                          **{'text-anchor': 'end' if item.anchor == 'e' else 'start', 'dominant-baseline': 'middle'}).text = item.text
        elif item.kind == 'line':
            points = ' '.join(f'{item.coords[i]},{item.coords[i+1]}' for i in range(0, len(item.coords), 2))
            ET.SubElement(parent, 'polyline', points=points, **values)
        else:
            x, y, right, bottom = item.coords
            if item.kind == 'rect':
                ET.SubElement(parent, 'rect', x=str(x), y=str(y), width=str(right-x), height=str(bottom-y), **values)
            else:
                ET.SubElement(parent, 'ellipse', cx=str((x+right)/2), cy=str((y+bottom)/2),
                              rx=str((right-x)/2), ry=str((bottom-y)/2), **values)


def placement_svg(snapshot, sensors, domains, *, comparable_frames, layout_label, selected_sensor=None):
    if (not isinstance(layout_label, str) or not 1 <= len(layout_label) <= 160
            or any(not 32 <= ord(c) < 127 for c in layout_label)):
        raise ValueError('Layout description needs 1-160 printable English characters')
    views = [project_placement(snapshot, sensors, domains, plane, comparable_frames=comparable_frames) for plane in ('XY', 'XZ')]
    if selected_sensor is not None and selected_sensor not in {s.point_id for s in sensors}:
        raise ValueError('Choose an existing sensor ID')
    metadata = dict(schema='wpt.sensor-placement-image.v1', source_sha256=snapshot.source_sha256,
                    snapshot_sha256=snapshot_digest(snapshot), layout_sha256=layout_digest(sensors),
                    domains=domains, comparable_frames=True, layout_label=layout_label, selected_sensor=selected_sensor,
                    sensors=[dict(point_id=p.sensor.point_id, position_m=p.sensor.position_m,
                                  axis_input=p.sensor.axis, axis_normalized=p.axis_xyz) for p in views[0].sensors])
    notes = [NOTICE, 'Frame declaration: comparable global Cartesian frames (user-declared, not registration).',
             'Panels fit independently; marker/arrow sizes are illustrative. Overlap in projection is not intersection.',
             'Geometry source SHA-256: '+metadata['source_sha256'], 'Snapshot SHA-256: '+metadata['snapshot_sha256'],
             'Layout input SHA-256: '+metadata['layout_sha256'], 'Selected sensor: '+(selected_sensor or 'none'),
             'Selected domains: '+', '.join(str(d) for d in domains)]
    lines = [line for note in notes for line in textwrap.wrap(note, 130)]
    table_top = 550+20*len(lines)
    height = table_top+50+42*len(sensors)
    root = ET.Element('svg', xmlns='http://www.w3.org/2000/svg', width='1200', height=str(height),
                      viewBox=f'0 0 1200 {height}', role='img', **{'aria-labelledby': 'title description',
                      'font-family': 'Segoe UI, sans-serif', 'font-size': '12'})
    ET.SubElement(root, 'title', id='title').text = 'Sensor Placement Preview'
    ET.SubElement(root, 'desc', id='description').text = 'XY and XZ sketches, dashed domain envelopes and sensor axis projections. '+NOTICE+' Numeric source data follows.'
    ET.SubElement(root, 'metadata').text = json.dumps(metadata, sort_keys=True, allow_nan=False)
    ET.SubElement(root, 'rect', width='1200', height=str(height), fill='white')
    ET.SubElement(root, 'text', x='20', y='28', fill=TEXT, **{'font-size': '20'}).text = 'Sensor Placement Preview'
    for i, line in enumerate(textwrap.wrap(layout_label, 130)):
        ET.SubElement(root, 'text', x='20', y=str(52+i*17), fill=TEXT).text = line
    for x, view in zip((10, 610), views):
        _svg_items(ET.SubElement(root, 'g', transform=f'translate({x},85)'), view, selected_sensor)
    for i, line in enumerate(lines):
        ET.SubElement(root, 'text', x='20', y=str(530+20*i), fill=TEXT).text = line
    columns = (20, 210, 400, 590, 780, 970)
    for x, label in zip(columns, ('x_m', 'y_m', 'z_m', 'nX', 'nY', 'nZ')):
        ET.SubElement(root, 'text', x=str(x), y=str(table_top), fill=TEXT).text = label
    for i, projected in enumerate(views[0].sensors):
        y = table_top+24+42*i
        ET.SubElement(root, 'text', x='20', y=str(y), fill=TEXT).text = projected.sensor.point_id
        for x, value in zip(columns, (*projected.sensor.position_m, *projected.axis_xyz)):
            ET.SubElement(root, 'text', x=str(x), y=str(y+18), fill=TEXT).text = repr(value)
    return ET.tostring(root, encoding='unicode')+'\n'


def save_placement_svg(path, snapshot, sensors, domains, **options):
    target = _path(path, '.svg')
    text = placement_svg(snapshot, sensors, domains, **options)
    return _write(target, text)
