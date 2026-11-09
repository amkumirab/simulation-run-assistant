"""Independent, read-only placement review. No model or field evaluation."""
import tkinter as tk
from tkinter import filedialog

from simulation_assistant.field_sample_files import load_field_workspace
from simulation_assistant.field_samples import validate_layout
from simulation_assistant.geometry_files import load_snapshot, snapshot_digest
from simulation_assistant.geometry_inspector import validate_snapshot
from simulation_assistant.sensor_placement import layout_digest, project_placement, projected_hits, unit_axis
from simulation_assistant.sensor_placement_views import draw_placement, save_placement_svg
from simulation_assistant.sensor_placement_widgets import build_placement_widgets


class SensorPlacementDialog:
    def __init__(self, parent):
        self.snapshot, self.sensors, self.layout_label = None, (), ''
        self.selected_sensor, self.accepted, self.views, self._domains = None, None, {}, ()
        self.closed = False
        self.window = tk.Toplevel(parent)
        self.window.title('Sensor Placement Preview')
        self.window.geometry('1240x850')
        self.window.minsize(1000, 760)
        self.window.transient(parent)
        self.window.bind('<Escape>', lambda _e: self.window.destroy())
        self.window.bind('<Destroy>', self.destroyed)
        self.frames = tk.BooleanVar(value=False)
        self.geometry_info = tk.StringVar(value='No geometry snapshot loaded.')
        self.layout_info = tk.StringVar(value='No sensor layout loaded. Load a field workspace or open from the sensor editor.')
        self.preview_note = tk.StringVar(value='No copied sensor layout loaded. No field data is displayed.')
        self.details = tk.StringVar(value='No sensor selected. The table is authoritative when markers overlap.')
        self.status = tk.StringVar(value='Load sources, explicitly select geometry domains and review coordinate frames.')
        build_placement_widgets(self)
        self.trace = self.frames.trace_add('write', lambda *_: self.invalidate())
        self.redraw()

    def domains(self):
        return tuple(int(d) for d in self.domains_tree.selection())

    def signature(self):
        return self.snapshot, self.sensors, self.domains(), self.frames.get()

    def invalidate(self, reset_frames=False):
        self.accepted, self.views = None, {}
        if reset_frames:
            self.frames.set(False)
        self.redraw()
        self.status.set('Preview cleared. Review selected domains and frames, then choose Preview selected domains.')

    def domains_changed(self, _event=None):
        current = self.domains()
        if current != self._domains:
            self._domains = current
            self.invalidate(reset_frames=True)

    def set_snapshot(self, snapshot):
        validate_snapshot(snapshot)
        self.snapshot = snapshot
        self.domains_tree.delete(*self.domains_tree.get_children())
        for part in snapshot.parts:
            self.domains_tree.insert('', 'end', iid=str(part.domain), values=(part.domain, part.selections))
        self._domains = ()
        self.geometry_info.set(f'{snapshot.component}/{snapshot.geometry} | {len(snapshot.parts)} domains | original unit {snapshot.length_unit}\n'
                               f'Model SHA: {snapshot.source_sha256}\nSnapshot SHA: {snapshot_digest(snapshot)}')
        self.invalidate(reset_frames=True)

    def set_layout(self, sensors, label):
        validate_layout(sensors)
        if (not isinstance(label, str) or not 1 <= len(label) <= 160
                or any(not 32 <= ord(c) < 127 for c in label)):
            raise ValueError('Layout description needs 1-160 printable English characters')
        self.sensors, self.layout_label = sensors, label
        self.preview_note.set(label+' | positions only, no field data')
        self.sensor_tree.delete(*self.sensor_tree.get_children())
        for sensor in sensors:
            axis = unit_axis(sensor)
            self.sensor_tree.insert('', 'end', iid=sensor.point_id, values=(sensor.point_id,
                                    *(format(v*1000, '.12g') for v in sensor.position_m), *(format(a, '.12g') for a in axis)))
        self.layout_info.set(f'{label} | {len(sensors)} sensors | positions only, no field values\nLayout input SHA: {layout_digest(sensors)}')
        self.sensor_tree.selection_set(sensors[0].point_id)
        self.sensor_selected()
        self.invalidate(reset_frames=True)

    def load_geometry(self):
        path = filedialog.askopenfilename(parent=self.window, title='Load saved geometry snapshot', filetypes=[('Geometry JSON', '*.json')])
        if not path:
            return False
        try:
            self.set_snapshot(load_snapshot(path))
            self.tabs.select(0)
            return True
        except (OSError, ValueError) as exc:
            self.status.set('Geometry load failed; current work kept: '+str(exc)[-350:])
            return False

    def load_layout(self):
        path = filedialog.askopenfilename(parent=self.window, title='Load sensor layout from field workspace', filetypes=[('Field workspace JSON', '*.json')])
        if not path:
            return False
        try:
            data, sensors = load_field_workspace(path)
            self.set_layout(sensors, 'Workspace layout only | '+data.metadata.coordinate_frame)
            self.tabs.select(1)
            return True
        except (OSError, ValueError) as exc:
            self.status.set('Layout load failed; current work kept: '+str(exc)[-350:])
            return False

    def preview(self):
        try:
            project_placement(self.snapshot, self.sensors, self.domains(), 'XY', comparable_frames=self.frames.get())
            self.accepted = self.signature()
            self.tabs.select(2)
            self.redraw()
            self.status.set('Placement preview only. Panels fit independently; projected overlap is not physical intersection. Use the table for coincident markers.')
            return True
        except ValueError as exc:
            self.accepted, self.views = None, {}
            self.redraw()
            self.status.set('Preview blocked: '+str(exc))
            return False

    def redraw(self, _event=None):
        if self.closed:
            return
        valid = self.accepted is not None and self.accepted == self.signature()
        self.views = {}
        for plane, canvas in self.canvases.items():
            view = None
            if valid:
                view = project_placement(self.snapshot, self.sensors, self.domains(), plane, comparable_frames=self.frames.get(),
                                         width=max(400, min(4000, canvas.winfo_width())), height=max(300, min(4000, canvas.winfo_height())))
                self.views[plane] = view
            draw_placement(canvas, view, self.selected_sensor)

    def sensor_selected(self, _event=None):
        selected = self.sensor_tree.selection()
        sensor = next((s for s in self.sensors if selected and s.point_id == selected[0]), None)
        if sensor is not None:
            self.selected_sensor = sensor.point_id
            axis = unit_axis(sensor)
            self.details.set(sensor.point_id+' | position (mm): '+', '.join(format(v*1000, '.12g') for v in sensor.position_m)
                             +'\nNormalized sensitivity axis (X, Y, Z): '+', '.join(format(a, '.12g') for a in axis))
            self.redraw()

    def pick_sensor(self, plane, x, y):
        if plane in self.views:
            hits = projected_hits(self.views[plane], x, y)
            if hits:
                self.sensor_tree.selection_set(hits[0])
                self.sensor_tree.see(hits[0])
                self.sensor_selected()
                if len(hits) > 1:
                    self.status.set(f'{len(hits)} markers overlap within picking distance. Select an exact ID in Sensor coordinates; no intersection is inferred.')

    def export(self):
        try:
            if self.accepted is None or self.signature() != self.accepted:
                raise ValueError('Preview the current approved inputs before export')
            path = filedialog.asksaveasfilename(parent=self.window, title='Export placement sketch',
                                               defaultextension='.svg', filetypes=[('Placement SVG', '*.svg')])
            if not path:
                return False
            save_placement_svg(path, self.snapshot, self.sensors, self.domains(), comparable_frames=self.frames.get(),
                               layout_label=self.layout_label, selected_sensor=self.selected_sensor)
            self.status.set('SVG saved with both views, full-precision SI sensor table, source hashes and frame declaration. No fields or model paths included.')
            return True
        except (OSError, ValueError) as exc:
            self.status.set('Export blocked; current work kept: '+str(exc)[-350:])
            return False

    def destroyed(self, event):
        if event.widget is self.window:
            self.closed = True
            self.frames.trace_remove('write', self.trace)
