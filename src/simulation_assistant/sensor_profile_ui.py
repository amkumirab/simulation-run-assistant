"""Editable declarations and opt-in screening of the current accepted overlay."""
import tkinter as tk
from tkinter import filedialog, messagebox

from simulation_assistant.sensor_field_ui import set_text
from simulation_assistant.sensor_field_views import number, source_text
from simulation_assistant.sensor_limit_checks import assess_sensor_limits
from simulation_assistant.sensor_limit_reports import save_sensor_assessment
from simulation_assistant.sensor_profile_files import load_sensor_profile, save_sensor_profile
from simulation_assistant.sensor_profile_form import PROFILE_FIELDS, SPEC_FIELDS, read_context, read_form, write_form
from simulation_assistant.sensor_profile_widgets import build_profile_widgets
from simulation_assistant.sensor_profiles import SensorProfile, validate_profile


class SensorProfileDialog:
    def __init__(self, fields):
        self.fields = fields
        self.closed, self.suspend = False, True
        self.result, self.accepted, self.saved_signature = None, None, None
        self.window = tk.Toplevel(fields.owner.window)
        self.window.title('Sensor profiles - declared limits, not hardware validation')
        self.window.geometry('1240x900')
        self.window.minsize(1040, 780)
        self.window.transient(fields.owner.window)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda _e: self.close())
        self.window.bind('<Destroy>', self.destroyed)
        self.form = {k: tk.StringVar(master=self.window) for k in PROFILE_FIELDS}
        self.spec_vars = {name: {k: tk.StringVar(master=self.window) for k in
                         (('low', 'high', 'unit', 'source', 'conditions') if name in ('frequency', 'field') else
                          ('value', 'unit', 'source', 'conditions'))} for name in SPEC_FIELDS}
        self.context = {k: tk.StringVar(master=self.window) for k in ('sampled_field', 'dc_x', 'dc_y', 'dc_z', 'dc_unit')}
        self.confirmed = tk.BooleanVar(master=self.window, value=False)
        self.scope, self.status = tk.StringVar(master=self.window), tk.StringVar(master=self.window)
        build_profile_widgets(self)
        self.variables = (*self.form.values(), *(v for row in self.spec_vars.values() for v in row.values()))
        self.traces = [(v, v.trace_add('write', self.changed)) for v in (*self.variables, *self.context.values())]
        self.traces.append((self.confirmed, self.confirmed.trace_add('write', lambda *_: self.changed(reset_confirmation=False))))
        self.set_profile(SensorProfile('New hypothetical profile'))

    def form_signature(self):
        return tuple(v.get() for v in self.variables)

    def dirty(self):
        return self.form_signature() != self.saved_signature

    def signature(self):
        return self.form_signature(), tuple(v.get() for v in self.context.values()), self.confirmed.get(), self.fields.valid_result()

    def valid_result(self):
        return self.result if self.accepted is not None and self.accepted == self.signature() else None

    def invalidate(self, reset_confirmation=True):
        self.result, self.accepted = None, None
        self.tree.delete(*self.tree.get_children())
        set_text(self.detail, 'No current assessment. Review the profile, field purpose and conditions, then Evaluate current fields.')
        if reset_confirmation and self.confirmed.get():
            self.confirmed.set(False)

    def changed(self, *_args, reset_confirmation=True):
        if self.suspend or self.closed:
            return
        self.invalidate(reset_confirmation)
        self.scope.set('ASSUMPTION-BASED SCREENING - no physical sensor implied' if self.form['basis'].get() == 'hypothetical'
                       else 'DOCUMENTED PROFILE CLAIM - sources user-recorded, not authenticated; no hardware validation')
        self.status.set('Inputs changed. Blank numeric specifications remain unknown; evaluate again before exporting.')

    def source_changed(self):
        if self.closed:
            return
        self.invalidate()
        overlay = self.fields.valid_result()
        info = ('No accepted field overlay. Profiles can still be edited and saved. Use Field overlay > Analyze overlay before evaluation.'
                if overlay is None else 'CURRENT: '+source_text(overlay.current_source)+'\nREFERENCE: '+source_text(overlay.reference_source))
        if overlay is not None:
            meta = overlay.bundle.data.metadata
            info += f'\nData: {meta.frequency_hz:g} Hz | {meta.phasor_convention} phasors | {meta.excitation} | {meta.phase_reference} | {meta.coordinate_frame}'
        set_text(self.source_info, info.encode('ascii', 'backslashreplace').decode('ascii'))
        self.status.set('Source inputs refreshed; review conditions and evaluate the current accepted fields.')

    def set_profile(self, profile):
        validate_profile(profile)
        self.suspend = True
        write_form(self, profile)
        for name, variable in self.context.items():
            variable.set('unknown' if name == 'sampled_field' else 'uT' if name == 'dc_unit' else '')
        self.confirmed.set(False)
        self.suspend = False
        self.saved_signature = self.form_signature()
        self.changed()
        self.source_changed()

    def can_close(self):
        return self.closed or not self.dirty() or messagebox.askyesno('Discard unsaved profile edits?',
                    'This profile has unsaved edits. Discard them?', parent=self.window)

    def new(self):
        if not self.can_close():
            return False
        self.set_profile(SensorProfile('New hypothetical profile'))
        self.tabs.select(0)
        return True

    def load(self):
        path = filedialog.askopenfilename(parent=self.window, title='Load sensor profile', filetypes=[('Sensor profile JSON', '*.json')])
        if not path:
            return False
        try:
            profile = load_sensor_profile(path)
            if not self.can_close():
                return False
            self.set_profile(profile)
            self.tabs.select(0)
            self.status.set('Profile loaded. Field purpose, DC bias and condition confirmation must be declared again.')
            return True
        except (OSError, ValueError) as exc:
            self.status.set('Profile load failed; current work kept: '+str(exc)[-350:])
            return False

    def save(self):
        try:
            profile, signature = read_form(self), self.form_signature()
            path = filedialog.asksaveasfilename(parent=self.window, title='Save sensor profile',
                                               defaultextension='.json', filetypes=[('Sensor profile JSON', '*.json')])
            if not path:
                return False
            if signature != self.form_signature():
                raise ValueError('Profile changed while choosing a file; save the current draft again')
            save_sensor_profile(path, profile)
            self.saved_signature = signature
            self.status.set('Profile saved. No context, result, DC bias or approval is restored by loading this file.')
            return True
        except (OSError, ValueError) as exc:
            self.status.set('Profile save blocked; current work kept: '+str(exc)[-350:])
            return False

    def evaluate(self):
        try:
            result = assess_sensor_limits(read_form(self), self.fields.valid_result(), **read_context(self))
        except ValueError as exc:
            self.invalidate(False)
            self.status.set('Evaluation blocked: '+str(exc))
            return False
        self.result, self.accepted = result, self.signature()
        self.scope.set(result.scope)
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(result.rows):
            self.tree.insert('', 'end', iid=str(i), values=(row.sensor_id, row.scenario, row.status,
                row.frequency.status, row.field.status, number(row.peak_axis_t, 1e6), number(row.minimum_t, 1e6),
                number(row.maximum_t, 1e6), row.sample_status))
        self.tree.selection_set('0')
        self.show_detail()
        self.tabs.select(1)
        self.status.set('Declared-limit screening only. '+result.context.reason+'. Sensitivity/noise recorded only; no detection or saturation approval.')
        return True

    def show_detail(self, _event=None):
        selected = self.tree.selection()
        if selected and self.valid_result() is not None:
            row = self.result.rows[int(selected[0])]
            set_text(self.detail, f'{row.sensor_id} | {row.scenario} | {row.status}\n'+self.result.scope
                     +'\nFrequency: '+row.frequency.reason+'\nField: '+row.field.reason
                     +f'\nAC peak axis B (T): {row.peak_axis_t!r}; uniform DC axis B (T): {row.dc_axis_t!r}'
                     +f'\nSigned interval (T): [{row.minimum_t!r}, {row.maximum_t!r}]'
                     +'\nNo total-vector maximum, transverse-field check, calibrated voltage, SNR or vehicle signature is inferred.')

    def export(self):
        try:
            result = self.valid_result()
            if result is None:
                raise ValueError('Evaluate the current profile and accepted field overlay before export')
            path = filedialog.asksaveasfilename(parent=self.window, title='Export declared-limit report',
                                               defaultextension='.json', filetypes=[('Sensor limit report JSON', '*.json')])
            if not path:
                return False
            if self.valid_result() != result:
                raise ValueError('Inputs changed while choosing a destination; evaluate again')
            save_sensor_assessment(path, result)
            self.status.set('Report saved with profile, assumptions, unavailable values and exact source states. Review user text before sharing.')
            return True
        except (OSError, ValueError) as exc:
            self.status.set('Report export blocked; current work kept: '+str(exc)[-350:])
            return False

    def close(self):
        if not self.can_close():
            return False
        self.window.destroy()
        return True

    def destroyed(self, event):
        if event.widget is self.window:
            self.closed = True
            for variable, trace in self.traces:
                variable.trace_remove('write', trace)
