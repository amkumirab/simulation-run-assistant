"""Opt-in saved-field controls attached to an independent placement workspace."""
import tkinter as tk
from tkinter import filedialog

from simulation_assistant.saved_field_bundles import load_saved_field_bundle
from simulation_assistant.sensor_field_overlay import analyze_overlay
from simulation_assistant.sensor_field_views import detail_text, number, save_overlay_svg, source_text
from simulation_assistant.sensor_field_widgets import build_field_widgets
from simulation_assistant.sensor_placement import project_placement


def set_text(widget, text):
    widget.configure(state='normal')
    widget.delete('1.0', 'end')
    widget.insert('1.0', text)
    widget.configure(state='disabled')


class SensorFieldOverlayControls:
    def __init__(self, owner):
        self.owner = owner
        self.bundle, self.result, self.accepted = None, None, None
        self.profile_window = None
        self.current = tk.StringVar(master=owner.window)
        self.reference = tk.StringVar(master=owner.window)
        self.state_matches = tk.BooleanVar(master=owner.window, value=False)
        build_field_widgets(self)
        self.traces = [(v, v.trace_add('write', self.scenario_changed)) for v in (self.current, self.reference)]
        self.traces.append((self.state_matches, self.state_matches.trace_add('write', self.approval_changed)))
        self.update_sources()
        set_text(self.detail, 'Load a complete saved-field bundle; a bare workspace does not establish source evidence.')

    def signature(self):
        return self.owner.signature(), self.bundle, self.current.get(), self.reference.get(), self.state_matches.get()

    def valid_result(self):
        return self.result if self.accepted is not None and self.accepted == self.signature() else None

    def invalidate(self, reset_state=False):
        self.result, self.accepted = None, None
        self.tree.delete(*self.tree.get_children())
        set_text(self.detail, 'No accepted field overlay. Review sources and declarations, then Analyze overlay.')
        self.owner.preview_note.set((self.owner.layout_label or 'No copied sensor layout')+' | positions only, no field data')
        if reset_state and self.state_matches.get():
            self.state_matches.set(False)
        if self.profile_window is not None and not self.profile_window.closed:
            self.profile_window.source_changed()

    def approval_changed(self, *_):
        self.invalidate()
        self.owner.redraw()

    def scenario_changed(self, *_):
        self.invalidate(reset_state=True)
        self.update_sources()
        self.owner.redraw()

    def update_sources(self):
        if self.bundle is None:
            set_text(self.source_info, 'No saved-field evidence bundle loaded. Existing copied sensor layout will be preserved.')
            return
        meta = self.bundle.data.metadata
        lines = [f'{meta.coordinate_frame} | {meta.frequency_hz:g} Hz | {meta.phasor_convention} | '
                 f'{meta.excitation} | {meta.phase_reference}']
        for label, name in (('CURRENT', self.current.get()), ('REFERENCE', self.reference.get())):
            source = next((s for s in self.bundle.sources if s.scenario == name), None)
            if source:
                lines.append(label+': '+source_text(source))
        lines.append('Matching hashes establish consistency, not authenticity or historical solution geometry.')
        set_text(self.source_info, '\n'.join(lines).encode('ascii', 'backslashreplace').decode('ascii'))

    def load(self):
        path = filedialog.askdirectory(parent=self.owner.window, title='Load complete saved-field bundle')
        if not path:
            return False
        try:
            bundle = load_saved_field_bundle(path)
        except (OSError, ValueError) as exc:
            self.owner.status.set('Field bundle rejected; current work kept: '+str(exc)[-350:])
            return False
        self.set_bundle(bundle)
        return True

    def set_bundle(self, bundle):
        """Accept an immutable bundle already validated by load_saved_field_bundle."""
        self.bundle = bundle
        self.current.set(bundle.data.scenarios[0])
        self.reference.set(bundle.data.scenarios[-1])
        for box in self.boxes.values():
            box.configure(values=bundle.data.scenarios)
        self.owner.invalidate(reset_frames=True)
        self.update_sources()
        self.owner.tabs.select(self.tab)
        self.owner.status.set('Bundle verified. Copied layout kept; choose Use bundle layout if needed. Review exact source states before approval.')

    def use_layout(self):
        if self.bundle is None:
            self.owner.status.set('Load a complete saved-field bundle first.')
            return False
        self.owner.set_layout(self.bundle.sensors, 'Saved-field bundle layout | '+self.bundle.data.metadata.coordinate_frame)
        self.owner.status.set('Bundle layout copied. Select geometry domains, review frames and current solution state, then Analyze overlay.')
        return True

    def analyze(self):
        try:
            project_placement(self.owner.snapshot, self.owner.sensors, self.owner.domains(), 'XY',
                              comparable_frames=self.owner.frames.get())
            result = analyze_overlay(self.owner.snapshot, self.owner.sensors, self.bundle, self.current.get(), self.reference.get(),
                                     comparable_frames=self.owner.frames.get(), geometry_matches_state=self.state_matches.get())
        except ValueError as exc:
            self.invalidate()
            self.owner.redraw()
            self.owner.status.set('Field overlay blocked: '+str(exc))
            return False
        self.result, self.accepted = result, self.signature()
        self.owner.accepted = self.owner.signature()
        self.tree.delete(*self.tree.get_children())
        for row in result.readings:
            self.tree.insert('', 'end', iid=row.sensor.point_id, values=(row.sensor.point_id, row.status,
                number(row.amplitude_t, 1e6), row.reference_status,
                number(None if row.reference_t is None else abs(row.reference_t), 1e6),
                number(row.amplitude_change_t, 1e6, True), number(row.phase_deg), number(row.phase_change_deg, signed=True)))
        self.owner.preview_note.set(f'FIELD OVERLAY | {self.current.get()} vs {self.reference.get()} | Current geometry only | '
                                    'ideal-axis amplitude (uT); arrows remain sensitivity axes, not field vectors')
        self.sync_selection()
        self.owner.redraw()
        self.owner.status.set('Saved fields only. State geometry is user-declared; selected-sensor labels are in Placement views. Not calibrated MTJ output.')
        if self.profile_window is not None and not self.profile_window.closed:
            self.profile_window.source_changed()
        return True

    def open_sensor_profiles(self):
        if self.profile_window is None or self.profile_window.closed:
            from simulation_assistant.sensor_profile_ui import SensorProfileDialog
            self.profile_window = SensorProfileDialog(self)
        else:
            self.profile_window.window.lift()
        return self.profile_window

    def can_close(self):
        return self.profile_window is None or self.profile_window.can_close()

    def selected(self, _event=None):
        selected = self.tree.selection()
        if selected and self.valid_result() is not None and self.owner.sensor_tree.selection() != selected:
            self.owner.sensor_tree.selection_set(selected[0])
            self.owner.sensor_tree.see(selected[0])
            self.owner.sensor_selected()

    def sync_selection(self):
        result = self.valid_result()
        sensor_id = self.owner.selected_sensor
        if result is not None and self.tree.exists(sensor_id):
            if self.tree.selection() != (sensor_id,):
                self.tree.selection_set(sensor_id)
                self.tree.see(sensor_id)
            set_text(self.detail, detail_text(result, sensor_id))

    def export(self):
        try:
            result = self.valid_result()
            if result is None:
                raise ValueError('Analyze the current approved inputs before field export')
            path = filedialog.asksaveasfilename(parent=self.owner.window, title='Export saved-field overlay',
                                               defaultextension='.svg', filetypes=[('Field overlay SVG', '*.svg')])
            if not path:
                return False
            save_overlay_svg(path, result, self.owner.domains(), layout_label=self.owner.layout_label,
                             selected_sensor=self.owner.selected_sensor)
            self.owner.status.set('Field SVG saved with exact states, source hashes, complex components and unavailable statuses. Review labels before sharing.')
            return True
        except (OSError, ValueError) as exc:
            self.owner.status.set('Field export blocked; current work kept: '+str(exc)[-350:])
            return False

    def close(self):
        for variable, trace in self.traces:
            variable.trace_remove('write', trace)
