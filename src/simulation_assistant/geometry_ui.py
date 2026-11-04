"""Native, cancellable, read-only saved geometry inspection."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from simulation_assistant.geometry_files import (
    BOUND_NAMES, brief_from_geometry, export_geometry_csv, load_snapshot, save_snapshot,
)
from simulation_assistant.geometry_inspector import inspect_geometry, validate_snapshot, z_separation
from simulation_assistant.geometry_views import draw_envelopes


class GeometryDialog:
    def __init__(self, parent):
        self.data, self.revision, self.closed = None, 0, False
        self.stop, self.events, self.worker = threading.Event(), queue.Queue(), None
        self.timer, self.traces = None, []
        self.window = tk.Toplevel(parent)
        self.window.title('Geometry & Layer Inspector')
        self.window.geometry('1240x850')
        self.window.minsize(1000, 760)
        self.window.transient(parent)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.window.bind('<Escape>', lambda _event: self.close())
        self.window.bind('<Destroy>', self.destroyed)
        self.model, self.executable = tk.StringVar(), tk.StringVar()
        self.lower, self.upper, self.parallel = tk.StringVar(), tk.StringVar(), tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Choose a saved 3D MPH and COMSOL batch executable, or load a portable snapshot.')
        self.identity = tk.StringVar(value='No snapshot. No solver or geometry build runs here.')
        self.separation = tk.StringVar(value='Unavailable: choose an ordered pair and declare a parallel, untilted stack.')
        body = ttk.Frame(self.window, style='Card.TFrame', padding=18)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(5, weight=1)
        ttk.Label(body, text='Geometry & Layer Inspector', style='CardTitle.TLabel').grid(row=0, column=0, sticky='w')
        notice = ttk.Label(body, text='READ ONLY  |  Saved geometry, not a historical sweep state. Bounding envelopes are approximate; '
                           'not CAD solids, collision checks or certified clearance.', style='CardText.TLabel', wraplength=1150)
        notice.grid(row=1, column=0, sticky='ew', pady=(6, 10))
        inputs = ttk.Frame(body, style='Card.TFrame')
        inputs.grid(row=2, column=0, sticky='ew')
        inputs.columnconfigure(1, weight=1)
        for row, (title, variable, extension) in enumerate((('Saved MPH', self.model, '*.mph'),
                                                        ('COMSOL batch', self.executable, '*.exe'))):
            ttk.Label(inputs, text=title, style='Field.TLabel').grid(row=row, column=0, sticky='w', padx=(0, 10))
            entry = ttk.Entry(inputs, textvariable=variable)
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            ttk.Button(inputs, text='Browse', style='Secondary.TButton',
                       command=lambda v=variable, ext=extension: self.browse(v, ext)).grid(row=row, column=2, padx=(8, 0))
        actions = ttk.Frame(body, style='Card.TFrame')
        actions.grid(row=3, column=0, sticky='ew', pady=8)
        for title, command in (('Inspect saved geometry', self.inspect), ('Cancel', self.cancel), ('Load snapshot', self.load),
                               ('Save snapshot', self.save), ('Export selected CSV', self.export), ('New brief from selected', self.new_brief)):
            ttk.Button(actions, text=title, command=command, style='Secondary.TButton').pack(side='left', padx=(0, 6))
        self.source_label = ttk.Label(body, textvariable=self.identity, style='CardText.TLabel', wraplength=1150)
        self.source_label.grid(row=4, column=0, sticky='ew', pady=(0, 8))
        self.tabs = ttk.Notebook(body)
        self.tabs.grid(row=5, column=0, sticky='nsew')
        table = ttk.Frame(self.tabs, padding=8)
        table.rowconfigure(1, weight=1)
        table.columnconfigure(0, weight=1)
        self.tabs.add(table, text='Bounds / selection')
        ttk.Label(table, text='Ctrl/Shift-click to select domains. No domain is assumed to be a coil, ferrite or shield. All bounds in mm.').grid(row=0, column=0, sticky='w', pady=(0, 6))
        columns = ('domain', 'selections', *BOUND_NAMES)
        self.tree = ttk.Treeview(table, columns=columns, show='headings', selectmode='extended', height=8)
        for name in columns:
            self.tree.heading(name, text=name.title() if name in ('domain', 'selections') else name+' (mm)')
            self.tree.column(name, width=70 if name == 'domain' else 290 if name == 'selections' else 85, minwidth=55, stretch=name == 'selections')
        self.tree.grid(row=1, column=0, sticky='nsew')
        for orient, row, col in (('vertical', 1, 1), ('horizontal', 2, 0)):
            scrollbar = ttk.Scrollbar(table, orient=orient, command=self.tree.yview if col else self.tree.xview)
            scrollbar.grid(row=row, column=col, sticky='ns' if col else 'ew')
            self.tree.configure(**{'yscrollcommand' if col else 'xscrollcommand': scrollbar.set})
        self.details = tk.StringVar(value='Nothing selected.')
        ttk.Label(table, textvariable=self.details, wraplength=1100).grid(row=3, column=0, sticky='ew', pady=6)
        self.tree.bind('<<TreeviewSelect>>', self.selected)
        self.tree.bind('<Return>', self.selected)
        self.canvas = tk.Canvas(self.tabs, background='#ffffff', highlightthickness=0)
        self.tabs.add(self.canvas, text='XZ schematic (not CAD)')
        self.canvas.bind('<Configure>', lambda _event: self.redraw())
        pair = ttk.LabelFrame(body, text='Declared parallel stack: global Z-envelope separation only', padding=8)
        pair.grid(row=6, column=0, sticky='ew', pady=8)
        for column, (label, variable) in enumerate((('Lower domain', self.lower), ('Upper domain', self.upper))):
            ttk.Label(pair, text=label).grid(row=0, column=column*2, padx=(0, 6))
            box = ttk.Combobox(pair, textvariable=variable, state='readonly', width=8)
            box.grid(row=0, column=column*2+1, padx=(0, 12))
            if column == 0:
                self.lower_box = box
            else:
                self.upper_box = box
        ttk.Checkbutton(pair, text='I declare these layers parallel and untilted', variable=self.parallel).grid(row=0, column=4, sticky='w')
        ttk.Label(pair, textvariable=self.separation, wraplength=1120).grid(row=1, column=0, columnspan=5, sticky='w', pady=(8, 0))
        self.feedback = ttk.Label(body, textvariable=self.status, style='CardText.TLabel', wraplength=1150)
        self.feedback.grid(row=7, column=0, sticky='ew')
        for variable in (self.model, self.executable):
            self.traces.append((variable, variable.trace_add('write', self.invalidate)))
        for variable in (self.lower, self.upper, self.parallel):
            self.traces.append((variable, variable.trace_add('write', self.update_separation)))
        body.bind('<Configure>', lambda event: [label.configure(wraplength=max(400, event.width-40))
                                                for label in (notice, self.source_label, self.feedback)])
        self.timer = self.window.after(100, self.poll)

    def browse(self, variable, extension):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[('Source', extension)])
        if path:
            variable.set(path)

    def invalidate(self, *_args):
        self.revision += 1
        self.stop.set()
        self.data = None
        self.tree.delete(*self.tree.get_children())
        self.lower.set('')
        self.upper.set('')
        self.parallel.set(False)
        self.lower_box.configure(values=())
        self.upper_box.configure(values=())
        self.identity.set('No current snapshot. Input changes invalidate previous results.')
        self.status.set('Inspect the current saved model, or load a stored snapshot.')
        self.selected()

    def inspect(self):
        if self.worker is not None and self.worker.is_alive():
            self.status.set('Previous inspection is stopping or running. Please wait; Cancel stops its owned process.')
            return
        self.invalidate()
        self.stop = threading.Event()
        stop, revision = self.stop, self.revision
        model, executable, events = self.model.get(), self.executable.get(), self.events
        self.status.set('Inspecting a private copy of saved geometry. No build or solve; Cancel remains available.')
        def work():
            try:
                result = inspect_geometry(model, executable, cancel_requested=stop.is_set)
                events.put((revision, result, ''))
            except Exception as exc:
                events.put((revision, None, str(exc)[-600:]))
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def poll(self):
        if self.closed:
            return
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            self.deliver(*event)
        self.timer = self.window.after(100, self.poll)

    def deliver(self, revision, data, error):
        if self.closed or revision != self.revision or self.stop.is_set():
            return
        if error:
            self.status.set('Inspection failed: '+error)
        else:
            self.set_snapshot(data, 'Saved MPH inspection')

    def set_snapshot(self, data, origin):
        validate_snapshot(data)
        self.data = data
        self.tree.delete(*self.tree.get_children())
        for part in data.parts:
            self.tree.insert('', 'end', iid=str(part.domain), values=(part.domain, part.selections, *(f'{v*1000:.4f}' for v in part.bounds_m)))
        values = tuple(str(part.domain) for part in data.parts)
        self.lower_box.configure(values=values)
        self.upper_box.configure(values=values)
        self.lower.set('')
        self.upper.set('')
        self.parallel.set(False)
        self.identity.set(f'{origin} | {data.component}/{data.geometry} | {len(data.parts)} domains | {data.engine_version}\nSource SHA-256: {data.source_sha256}')
        self.status.set('Snapshot loaded. Explicitly select domains for the schematic, CSV or a new proposed brief.')
        self.selected()

    def selected_domains(self):
        return tuple(int(value) for value in self.tree.selection()) if self.data else ()

    def selected(self, _event=None):
        ids = self.selected_domains()
        parts = tuple(p for p in self.data.parts if p.domain in ids) if self.data else ()
        self.details.set(' | '.join(f'D{p.domain}: {p.selections or "No named selection"}' for p in parts)[:750] or 'Nothing selected.')
        self.redraw()

    def redraw(self):
        ids = self.selected_domains()
        draw_envelopes(self.canvas, tuple(p for p in self.data.parts if p.domain in ids) if self.data else ())

    def update_separation(self, *_args):
        index = {str(p.domain): p for p in self.data.parts} if self.data else {}
        lower, upper = index.get(self.lower.get()), index.get(self.upper.get())
        value = z_separation(lower, upper, self.parallel.get()) if lower and upper else None
        self.separation.set('Unavailable: declare parallel layers; choose distinct, ordered domains with overlapping XY envelopes.'
                            if value is None else f'{value*1000:.3f} mm global Z-envelope separation (not clearance or collision approval).')

    def load(self):
        path = filedialog.askopenfilename(parent=self.window, filetypes=[('Geometry snapshot', '*.json')])
        if path:
            try:
                data = load_snapshot(path)
                self.invalidate()
                self.set_snapshot(data, 'Stored snapshot; not a live model connection')
            except (ValueError, OSError) as exc:
                self.status.set('Load failed; existing snapshot kept: '+str(exc)[-400:])

    def save(self):
        self._export(False)

    def export(self):
        self._export(True)

    def _export(self, csv):
        try:
            if self.data is None or (csv and not self.selected_domains()):
                raise ValueError('Load or inspect geometry and explicitly select domains for CSV.')
            suffix = '.csv' if csv else '.json'
            path = filedialog.asksaveasfilename(parent=self.window, defaultextension=suffix, filetypes=[('Geometry snapshot', '*'+suffix)])
            if path:
                if csv:
                    export_geometry_csv(path, self.data, self.selected_domains())
                else:
                    save_snapshot(path, self.data)
                self.status.set('Saved selected domains in CSV.' if csv else 'Saved all domains in a portable geometry snapshot; no local model path included.')
        except (ValueError, OSError) as exc:
            self.status.set('Export blocked: '+str(exc)[-400:])

    def new_brief(self):
        try:
            if self.data is None:
                raise ValueError('Load or inspect geometry first.')
            brief = brief_from_geometry(self.data, self.selected_domains(), 'Geometry envelope review', 'draft')
            from simulation_assistant.model_brief_ui import ModelBriefDialog
            # Keep the independent unsaved draft alive if this inspector closes.
            dialog = ModelBriefDialog(self.window.master)
            dialog.set_brief(brief)
            return dialog
        except ValueError as exc:
            self.status.set('Draft blocked: '+str(exc))
            return None

    def cancel(self):
        self.stop.set()
        self.revision += 1
        self.status.set('Cancellation requested. Pending results will not replace the current snapshot.')

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
