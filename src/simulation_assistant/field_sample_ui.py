"""Offline field import, fixed sensor layout and scenario comparison."""
import json
import tkinter as tk
from dataclasses import asdict
from tkinter import filedialog, messagebox, ttk

from simulation_assistant.field_samples import FieldMetadata, Sensor, analyze_field_samples
from simulation_assistant.field_sample_files import (
    load_field_csv, load_field_workspace, save_field_workspace, write_field_readings_csv, write_sensor_layout_csv,
)
from simulation_assistant.field_sample_views import SensorLayoutEditor, draw_field_layout, field_table


class FieldSamplesDialog:
    def __init__(self, parent):
        self.data, self.readings, self.loading = None, (), False
        self.window = tk.Toplevel(parent)
        self.window.title("Field Samples & Sensor Layout")
        self.window.geometry("1120x840")
        self.window.minsize(980, 720)
        self.window.transient(parent)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        self.window.bind("<Control-r>", lambda _event: self.analyze())
        body = ttk.Frame(self.window, style="Card.TFrame", padding=18)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)
        ttk.Label(body, text="Field Samples & Sensor Layout", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.origin = tk.StringVar(value="Offline sampled fields, not MTJ voltage, DOA or hardware control. No solver starts here.")
        ttk.Label(body, textvariable=self.origin, wraplength=920, style="CardText.TLabel").grid(row=1, column=0, sticky="w", pady=8)
        self.tabs = ttk.Notebook(body)
        self.tabs.grid(row=2, column=0, sticky="nsew")
        setup = ttk.Frame(self.tabs, style="Card.TFrame", padding=12)
        self.summary = tk.StringVar(value="Declare metadata, then import a normalized field CSV, or load a saved workspace.")
        self.layout = SensorLayoutEditor(self.tabs, self.invalidate, self.summary.set)
        result = ttk.Frame(self.tabs, style="Card.TFrame", padding=12)
        for tab, title in ((setup, "1. Field data"), (self.layout, "2. Sensor layout"), (result, "3. Scenario comparison")):
            self.tabs.add(tab, text=title)
        self.meta_vars = {}
        options = {"source_kind": ("synthetic", "comsol-export"), "coordinate_unit": ("mm", "cm", "m"),
                   "field_unit": ("T", "mT", "uT"), "phasor_convention": ("peak", "rms")}
        for index, name in enumerate(FieldMetadata.__dataclass_fields__):
            row, column = divmod(index, 3)
            container = ttk.Frame(setup, style="Card.TFrame")
            container.grid(row=row, column=column, sticky="ew", padx=(0, 16), pady=6)
            setup.columnconfigure(column, weight=1)
            ttk.Label(container, text=name.replace("_", " "), style="Field.TLabel").pack(anchor="w")
            variable = tk.StringVar()
            self.meta_vars[name] = variable
            widget = (ttk.Combobox(container, textvariable=variable, values=options[name], state="readonly")
                      if name in options else ttk.Entry(container, textvariable=variable))
            widget.pack(fill="x", pady=4)
            variable.trace_add("write", self.metadata_changed)
        ttk.Label(setup, text="All metadata is user-declared, not verified. One frame, frequency, excitation and phase reference per CSV.\n"
                  "Expected columns: scenario, point_id, x, y, z, bx_real, bx_imag, by_real, by_imag, bz_real, bz_imag.\n"
                  "Enter numeric coordinates/fields in the declared units. Complex phase is retained; no zero-imaginary guesses.",
                  wraplength=900, style="CardText.TLabel").grid(row=4, column=0, columnspan=3, sticky="w", pady=12)
        self.dataset_note = tk.StringVar(value="No dataset imported.")
        ttk.Label(setup, textvariable=self.dataset_note, wraplength=900, style="CardText.TLabel").grid(row=5, column=0, columnspan=3, sticky="w", pady=8)
        controls = ttk.Frame(setup, style="Card.TFrame")
        controls.grid(row=6, column=0, columnspan=3, sticky="w")
        ttk.Button(controls, text="Import CSV", command=self.import_csv, style="Primary.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Use scenario points as sensors", command=self.use_points, style="Secondary.TButton").pack(side="left")
        result.columnconfigure(0, weight=1)
        result.rowconfigure(1, weight=2)
        result.rowconfigure(2, weight=2)
        self.scenario, self.reference = tk.StringVar(), tk.StringVar()
        selection = ttk.Frame(result, style="Card.TFrame")
        selection.grid(row=0, column=0, sticky="ew", pady=4)
        self.combos = []
        for label, variable in (("Scenario", self.scenario), ("Reference", self.reference)):
            ttk.Label(selection, text=label, style="Field.TLabel").pack(side="left", padx=(0, 8))
            combo = ttk.Combobox(selection, textvariable=variable, state="readonly", width=25)
            combo.pack(side="left", padx=(0, 16))
            self.combos.append(combo)
            variable.trace_add("write", self.invalidate)
        ttk.Button(selection, text="Analyze", command=self.analyze, style="Primary.TButton").pack(side="left")
        frame, self.tree = field_table(result, ("sensor", "status", "reference_status", "x_mm", "y_mm", "z_mm",
                                              "amplitude_uT", "phase_deg", "reference_uT", "change_uT", "phase_change_deg"))
        frame.grid(row=1, column=0, sticky="nsew", pady=8)
        self.tree.bind("<Return>", self.show_details)
        self.tree.bind("<Double-1>", self.show_details)
        self.chart = tk.Canvas(result, highlightthickness=0, height=230,
                               background=ttk.Style(self.window).lookup("Card.TFrame", "background") or "white")
        self.chart.grid(row=2, column=0, sticky="nsew")
        self.chart.bind("<Configure>", lambda _event: self.draw())
        ttk.Label(body, textvariable=self.summary, style="CardText.TLabel", wraplength=920).grid(row=3, column=0, sticky="w", pady=8)
        actions = ttk.Frame(body, style="Card.TFrame")
        actions.grid(row=4, column=0, sticky="ew")
        for index, (label, callback) in enumerate((("Load workspace", self.load), ("Save workspace", self.save),
                 ("Export comparison CSV", self.export), ("Export layout points", self.export_layout), ("Close", self.window.destroy))):
            ttk.Button(actions, text=label, command=callback, style="Secondary.TButton").grid(row=index//4, column=index%4, padx=(0, 8), pady=4)

    def invalidate(self, *_args):
        if hasattr(self, "tree"):
            self.readings = ()
            self.tree.delete(*self.tree.get_children())
            self.draw()
            self.summary.set("Selection or layout changed. Analyze again to refresh comparison.")

    def metadata_changed(self, *_args):
        if self.loading:
            return
        self.data = None
        self.invalidate()
        self.dataset_note.set("Metadata changed. Re-import CSV before analysis or saving.")
        self.origin.set("No active dataset. Metadata edits invalidate previously imported fields.")
        for combo in self.combos:
            combo.configure(values=())
        self.summary.set("Metadata changed. Re-import CSV; changing unit labels cannot reinterpret saved samples.")

    def set_data(self, data, sensors=None):
        self.loading = True
        try:
            for name, value in asdict(data.metadata).items():
                self.meta_vars[name].set(str(value))
            self.data = data
            for combo in self.combos:
                combo.configure(values=data.scenarios)
            self.scenario.set(data.scenarios[-1])
            self.reference.set(data.scenarios[0])
            if sensors is not None:
                self.layout.set_sensors(sensors)
            else:
                # A new CSV may declare a different frame; never reuse old locations implicitly.
                self.layout.clear()
        finally:
            self.loading = False
        meta = data.metadata
        self.origin.set(f"{meta.source_kind.upper()} (user-declared) | {meta.frequency_hz:g} Hz | {meta.phasor_convention} phasors | "
                        "ideal-axis field projection, not calibrated MTJ voltage.")
        self.dataset_note.set(f"{len(data.samples)} points in {len(data.scenarios)} scenarios | frame: {meta.coordinate_frame}\n"
                              f"Source CSV SHA-256: {data.source_sha256}")
        self.summary.set("Dataset loaded. Use scenario points or define fixed sensors, then Analyze.")

    def import_csv(self):
        path = filedialog.askopenfilename(parent=self.window, title="Import normalized complex field CSV", filetypes=[("Field samples", "*.csv")])
        if not path:
            return
        self.data = None
        self.invalidate()
        try:
            values = {name: variable.get().strip() for name, variable in self.meta_vars.items()}
            values["frequency_hz"] = float(values["frequency_hz"])
            self.set_data(load_field_csv(path, FieldMetadata(**values)))
        except (OSError, ValueError, OverflowError) as exc:
            self.origin.set("Import failed. No active dataset.")
            self.dataset_note.set("Import failed; no partial dataset accepted.")
            self.summary.set(f"Import blocked: {exc}")

    def use_points(self):
        if self.data is None:
            self.summary.set("Import or load a dataset first.")
            return
        sensors = tuple(Sensor(sample.point_id, sample.position_m, (0., 0., 1.)) for sample in self.data.samples
                        if sample.scenario == self.scenario.get())
        self.layout.set_sensors(sensors)
        self.tabs.select(1)
        self.summary.set("Copied selected scenario points as fixed Z-axis sensors. Review layout before analysis.")

    def analyze(self):
        self.invalidate()
        try:
            if self.data is None:
                raise ValueError("Import or load field data first")
            self.readings = analyze_field_samples(self.data, self.layout.get_sensors(), self.scenario.get(), self.reference.get())
            for index, row in enumerate(self.readings):
                baseline = abs(row.reference_t)*1e6 if row.reference_t is not None else None
                self.tree.insert("", "end", iid=str(index), values=(row.sensor.point_id, row.status, row.reference_status,
                    *(_number(v*1000) for v in row.sensor.position_m), _number(row.amplitude_t, 1e6), _number(row.phase_deg),
                    _number(baseline), _number(row.amplitude_change_t, 1e6), _number(row.phase_change_deg)))
            self.draw()
            available = sum(row.status == "available" for row in self.readings)
            paired = sum(row.projected_t is not None and row.reference_t is not None for row in self.readings)
            self.summary.set(f"{available}/{len(self.readings)} current readings available; {paired} comparable to reference. "
                             f"Amplitudes are {self.data.metadata.phasor_convention} field projections in uT; not sensor voltages.")
            self.tabs.select(2)
            return self.readings
        except (ValueError, OverflowError) as exc:
            self.summary.set(f"Analysis blocked: {exc}")
            return None

    def draw(self):
        if hasattr(self, "chart"):
            draw_field_layout(self.chart, self.readings, self.scenario.get(), self.reference.get())

    def _destination(self, title, suffix):
        return filedialog.asksaveasfilename(parent=self.window, title=title, defaultextension=suffix,
                                          filetypes=[("Workspace" if suffix == ".json" else "CSV", "*"+suffix)])

    def save(self):
        try:
            if self.data is None:
                raise ValueError("Import or load field data first")
            sensors = self.layout.get_sensors()
            path = self._destination("Save field workspace", ".json")
            if path:
                save_field_workspace(path, self.data, sensors)
                self.summary.set("Saved exact fields, metadata and layout. Original source files unchanged.")
        except (OSError, ValueError) as exc:
            self.summary.set(f"Save blocked: {exc}")

    def load(self):
        path = filedialog.askopenfilename(parent=self.window, title="Load field workspace", filetypes=[("Workspace", "*.json")])
        if path:
            self.data = None
            self.invalidate()
            try:
                data, sensors = load_field_workspace(path)
                self.set_data(data, sensors)
                self.analyze()
            except (OSError, ValueError) as exc:
                self.origin.set("Load failed. No active dataset.")
                self.dataset_note.set("Load failed; no partial dataset accepted.")
                self.summary.set(f"Load blocked: {exc}")

    def export(self):
        if self.analyze() is None:
            return
        path = self._destination("Export current field comparison", ".csv")
        if path:
            try:
                write_field_readings_csv(path, self.data, self.layout.get_sensors(), self.scenario.get(), self.reference.get())
                self.summary.set("Exported every layout sensor, including unavailable readings and source metadata.")
            except (OSError, ValueError) as exc:
                self.summary.set(f"Export failed: {exc}")

    def export_layout(self):
        try:
            sensors = self.layout.get_sensors()
            path = self._destination("Export fixed sensor locations", ".csv")
            if path:
                write_sensor_layout_csv(path, sensors)
                self.summary.set("Exported locations in m and normalized directions. No field samples or COMSOL solve generated.")
        except (OSError, ValueError) as exc:
            self.summary.set(f"Export blocked: {exc}")

    def show_details(self, _event=None):
        selection = self.tree.selection()
        if selection:
            row = self.readings[int(selection[0])]
            messagebox.showinfo("Field sample evidence", json.dumps({"reading": asdict(row), "metadata": asdict(self.data.metadata),
                                "source_csv_sha256": self.data.source_sha256}, indent=2, default=str), parent=self.window)


def _number(value, scale=1.):
    return "unavailable" if value is None else f"{value*scale:.6g}"
