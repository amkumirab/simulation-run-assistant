"""Native, cancellable saved-solution sampling with explicit evidence selection."""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from simulation_assistant.adapters.comsol import discover_comsol_executable
from simulation_assistant.comsol_field_sampling import (
    FieldSelection, SavedScenario, inspect_saved_fields, extract_scenarios,
    save_source_bundle, validate_selection,
)
from simulation_assistant.field_samples import validate_label
from simulation_assistant.field_sample_views import field_table


class SavedFieldDialog:
    def __init__(self, owner):
        self.owner = owner
        self.inspected, self.result, self.busy, self.closed = None, None, False, False
        self.scenarios = ()
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.timer = None
        self.revision = 0
        self.traces = []
        self.window = tk.Toplevel(owner.window)
        self.window.title('Sample saved COMSOL fields')
        self.window.geometry('1080x820')
        self.window.minsize(980, 760)
        self.window.transient(owner.window)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda _event: self.close())
        self.window.bind('<Destroy>', self.destroyed)
        body = ttk.Frame(self.window, style='Card.TFrame', padding=16)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)
        ttk.Label(body, text='Saved-solution field sampling', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(body, text='Cartesian 3D only. Reads a private copy; never solves or saves the source model.\n'
                  'Fields are not calibrated MTJ voltages or evidence of vehicle detection.',
                  style='CardText.TLabel', wraplength=920).grid(row=1, column=0, sticky='w', pady=8)
        self.variables = {name: tk.StringVar() for name in ('model', 'executable', 'scenario', 'prefix', 'convention', 'excitation', 'phase_reference')}
        self.status = tk.StringVar(value='Define fixed sensors first. Inspect a solved model, then explicitly choose and add a saved state.')
        self.confirmed = tk.BooleanVar(value=False)
        try:
            self.variables['executable'].set(str(discover_comsol_executable()))
        except ValueError:
            pass
        files = ttk.Frame(body, style='Card.TFrame')
        files.grid(row=2, column=0, sticky='ew')
        files.columnconfigure(1, weight=1)
        for row, (name, label) in enumerate((('executable', 'COMSOL batch'), ('model', 'Saved MPH file'))):
            ttk.Label(files, text=label, style='Field.TLabel').grid(row=row, column=0, sticky='w', padx=(0, 12))
            ttk.Entry(files, textvariable=self.variables[name]).grid(row=row, column=1, sticky='ew', pady=4)
            ttk.Button(files, text='Browse', style='Secondary.TButton', command=lambda name=name: self.browse(name)).grid(row=row, column=2, padx=8)
        choose = ttk.Frame(body, style='Card.TFrame')
        choose.grid(row=3, column=0, sticky='ew', pady=8)
        choose.columnconfigure(1, weight=1)
        ttk.Button(choose, text='Inspect saved states', command=self.inspect, style='Secondary.TButton').grid(row=0, column=0, padx=(0, 8))
        self.state_combo = ttk.Combobox(choose, state='readonly', width=65)
        self.state_combo.grid(row=0, column=1, columnspan=3, sticky='ew')
        ttk.Label(choose, text='Scenario name', style='Field.TLabel').grid(row=1, column=0, sticky='w', pady=8)
        ttk.Entry(choose, textvariable=self.variables['scenario']).grid(row=1, column=1, sticky='ew')
        ttk.Button(choose, text='Add named state', command=self.add_state, style='Secondary.TButton').grid(row=1, column=2, padx=8)
        ttk.Button(choose, text='Remove selected', command=self.remove, style='Secondary.TButton').grid(row=1, column=3)
        frame, self.tree = field_table(body, ('scenario', 'dataset', 'solver', 'outer', 'inner', 'source_sha256', 'parameters'))
        frame.grid(row=4, column=0, sticky='nsew', pady=8)
        self.tree.column('source_sha256', width=480)
        self.tree.column('parameters', width=480)
        declarations = ttk.Frame(body, style='Card.TFrame')
        declarations.grid(row=5, column=0, sticky='ew')
        for column, (name, label) in enumerate((('prefix', 'Field prefix (e.g. mf)'), ('convention', 'Declared phasors'),
                                               ('excitation', 'Shared excitation'), ('phase_reference', 'Shared phase reference'))):
            declarations.columnconfigure(column, weight=1)
            ttk.Label(declarations, text=label, style='Field.TLabel').grid(row=0, column=column, sticky='w')
            widget = (ttk.Combobox(declarations, textvariable=self.variables[name], values=('peak', 'rms'), state='readonly', width=15)
                      if name == 'convention' else ttk.Entry(declarations, textvariable=self.variables[name], width=24))
            widget.grid(row=1, column=column, sticky='ew', padx=(0, 8), pady=6)
        ttk.Checkbutton(body, text='I confirm a shared global XYZ frame, excitation and phase reference for every selected state.',
                        variable=self.confirmed).grid(row=6, column=0, sticky='w', pady=8)
        ttk.Label(body, textvariable=self.status, style='CardText.TLabel', wraplength=920).grid(row=7, column=0, sticky='w', pady=8)
        actions = ttk.Frame(body, style='Card.TFrame')
        actions.grid(row=8, column=0, sticky='ew')
        self.extract_button = ttk.Button(actions, text='Extract to comparison', command=self.extract, style='Primary.TButton')
        self.extract_button.pack(side='left', padx=(0, 8))
        for label, command in (('Cancel task', self.cancel), ('Export source bundle', self.export), ('Close', self.close)):
            ttk.Button(actions, text=label, command=command, style='Secondary.TButton').pack(side='left', padx=(0, 8))
        for name, variable in self.variables.items():
            token = variable.trace_add('write', lambda *_args, name=name: self.changed(name))
            self.traces.append((variable, token))
        token = self.confirmed.trace_add('write', lambda *_args: self.changed())
        self.traces.append((self.confirmed, token))
        for variable in (*owner.layout.variables.values(), *owner.meta_vars.values()):
            token = variable.trace_add('write', self.inputs_edited)
            self.traces.append((variable, token))

    def inputs_edited(self, *_args):
        self.revision += 1

    def changed(self, name=None):
        self.inputs_edited()
        if name in ('model', 'executable'):
            self.inspected = None
            self.state_combo.set('')
            self.state_combo.configure(values=())
        if self.result is not None and self.owner.data is self.result.data:
            self.owner.data = None
            self.owner.invalidate()
            self.owner.origin.set('Saved-field inputs changed. Extract again before analysis.')
        self.result = None

    def signature(self):
        return (self.revision, id(self.owner.data), tuple(v.get() for v in self.variables.values()), self.confirmed.get(), self.scenarios,
                self.owner.layout.sensors, self.owner.layout.dirty,
                tuple(v.get() for v in self.owner.layout.variables.values()),
                tuple(v.get() for v in self.owner.meta_vars.values()))

    def browse(self, name):
        path = filedialog.askopenfilename(parent=self.window, title='Select '+name,
                  filetypes=[('COMSOL model', '*.mph')] if name == 'model' else [('COMSOL batch executable', '*')])
        if path:
            self.variables[name].set(path)

    def inspect(self):
        if self.closed or self.busy:
            return
        model, executable = Path(self.variables['model'].get()), Path(self.variables['executable'].get())
        self.inspected = None
        self.state_combo.set('')
        self.state_combo.configure(values=())
        self.submit('catalog', lambda: inspect_saved_fields(model, executable, cancel_requested=self.stop.is_set))

    def accept_catalog(self, value):
        digest, states = value
        self.inspected = (Path(self.variables['model'].get()), digest, states)
        self.state_combo.configure(values=[f'{s.dataset} / {s.solver} / outer {s.outer} / inner {s.inner} | {s.parameters}' for s in states])
        self.state_combo.set('')
        self.status.set(f'{len(states)} saved states found. Choose one explicitly. Source SHA-256: {digest}')

    def add_state(self):
        try:
            if self.busy or self.inspected is None or self.state_combo.current() < 0:
                raise ValueError('Inspect and explicitly choose a saved state first')
            name = self.variables['scenario'].get().strip()
            validate_label(name)
            if len(self.scenarios) >= 32 or any(s.name == name for s in self.scenarios):
                raise ValueError('Use unique scenario names; limit 32 states')
            path, digest, states = self.inspected
            state = states[self.state_combo.current()]
            self.scenarios += (SavedScenario(name, path, digest, state),)
            self.tree.insert('', 'end', iid=name, values=(name, state.dataset, state.solver, state.outer, state.inner, digest, state.parameters))
            self.changed()
            self.status.set('State added. You may inspect another saved model and add its matching-excitation state.')
        except (ValueError, IndexError) as exc:
            self.status.set(str(exc))

    def remove(self):
        if not self.busy:
            names = self.tree.selection()
            self.scenarios = tuple(s for s in self.scenarios if s.name not in names)
            self.tree.delete(*names)
            self.changed()

    def extract(self):
        if self.closed or self.busy:
            return
        try:
            if not self.confirmed.get():
                raise ValueError('Confirm shared frame, excitation and phase reference; no MTJ suitability is inferred')
            sensors = self.owner.layout.get_sensors()
            if not self.scenarios:
                raise ValueError('Add at least one explicit saved state')
            variables = self.variables
            expressions = tuple(variables['prefix'].get().strip()+'.B'+axis for axis in 'xyz')
            convention, excitation, phase = (variables[n].get().strip() for n in ('convention', 'excitation', 'phase_reference'))
            validate_selection(FieldSelection(self.scenarios[0].model_sha256, tuple((s.name, s.state) for s in self.scenarios),
                                               expressions, convention, excitation, phase), sensors)
            scenarios, executable = self.scenarios, Path(variables['executable'].get())
            self.changed()
            self.submit('extract', lambda: extract_scenarios(scenarios, executable, expressions, sensors,
                         convention, excitation, phase, cancel_requested=self.stop.is_set))
        except ValueError as exc:
            self.status.set(str(exc))

    def submit(self, kind, operation):
        if self.closed:
            return
        if self.busy:
            self.status.set('A saved-field task is already running. Wait or cancel it.')
            return
        self.busy = True
        self.stop.clear()
        snapshot = self.signature()
        self.extract_button.configure(state='disabled')
        self.status.set('Reading a private model copy. No solve starts. You may cancel; edits discard pending results.')
        def worker():
            try:
                value = operation()
            except Exception as exc:
                value = exc
            self.events.put((kind, snapshot, value))
        threading.Thread(target=worker, daemon=True).start()
        self.timer = self.window.after(100, self.poll)

    def poll(self):
        self.timer = None
        if self.closed:
            return
        try:
            kind, snapshot, value = self.events.get_nowait()
        except queue.Empty:
            self.timer = self.window.after(100, self.poll)
            return
        self.complete(kind, snapshot, value)

    def complete(self, kind, snapshot, value):
        self.busy = False
        if self.closed:
            return
        self.extract_button.configure(state='normal')
        if self.stop.is_set() or snapshot != self.signature():
            self.status.set('Pending results discarded after cancellation or input/layout edits. Extract again.')
        elif isinstance(value, Exception):
            self.status.set('Saved-field task failed; no partial data imported. '+str(value)[-500:])
        elif kind == 'catalog':
            self.accept_catalog(value)
        else:
            self.owner.set_data(value.data, value.sensors)
            self.owner.analyze()
            self.result = value
            self.status.set('Fields imported into Scenario comparison. Export source bundle to preserve full model/state provenance.')

    def export(self):
        try:
            if self.result is None or self.owner.data is not self.result.data or self.owner.layout.get_sensors() != self.result.sensors:
                raise ValueError('Extract current inputs first. Edited layouts require a fresh extraction.')
            parent = filedialog.askdirectory(parent=self.window, title='Save new source evidence bundle inside')
            if parent:
                self.status.set('Source bundle saved: '+str(save_source_bundle(parent, self.result)))
        except (OSError, ValueError) as exc:
            self.status.set('Bundle export blocked: '+str(exc)[-400:])

    def cancel(self):
        self.stop.set()
        self.status.set('Cancellation requested. No pending result will be imported.')

    def destroyed(self, event):
        if event.widget is self.window:
            self.closed = True
            self.stop.set()
            for variable, token in self.traces:
                variable.trace_remove('write', token)
            self.traces.clear()
            if self.timer:
                self.window.after_cancel(self.timer)
                self.timer = None

    def close(self):
        self.stop.set()
        self.window.destroy()
