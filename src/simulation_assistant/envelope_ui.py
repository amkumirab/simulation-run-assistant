"""Native, offline source-amplitude envelope viewer."""
from __future__ import annotations

import json
import tkinter as tk
from dataclasses import asdict, replace
from tkinter import filedialog, ttk

from simulation_assistant.design_campaign_ui import _table
from simulation_assistant.envelope_reports import LIMITATION, write_envelope_csv, write_envelope_html
from simulation_assistant.operating_envelopes import EnvelopeLimits, analyze_operating_envelope


class OperatingEnvelopeDialog:
    def __init__(self, parent, campaign, jobs_provider):
        self.campaign, self.jobs_provider = campaign, jobs_provider
        self.report = None
        self.window = tk.Toplevel(parent)
        self.window.title("WPT Operating Envelope")
        self.window.geometry("1200x820")
        self.window.minsize(960, 700)
        self.window.transient(parent)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        self.window.bind("<Control-r>", lambda _event: self.analyze())
        self.body = ttk.Frame(self.window, style="Card.TFrame", padding=18)
        self.body.pack(fill="both", expand=True)
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(5, weight=2)
        self.body.rowconfigure(6, weight=3)
        ttk.Label(self.body, text="WPT Operating Envelope", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self.body, text="Adjust source amplitude only. Frequency, load and compensation stay fixed per geometry.\n"
                  "Offline linear AC model; limits are provisional. Source V RMS is not DC bus voltage.",
                  style="CardText.TLabel", wraplength=900).grid(row=1, column=0, sticky="w", pady=(4, 8))
        inputs = ttk.Frame(self.body, style="Card.TFrame")
        inputs.grid(row=2, column=0, sticky="ew")
        self.variables = {}
        settings = (("max_source_rms_v", "Source ceiling (V RMS)", 400),
                    ("target_load_power_w", "Target AC load power (W)", campaign.settings.target_load_power_w),
                    ("max_coil_current_rms_a", "Each coil ceiling (A RMS)", campaign.limits.max_coil_current_rms_a),
                    ("max_capacitor_voltage_rms_v", "Each capacitor ceiling (V RMS)", campaign.limits.max_capacitor_voltage_rms_v))
        for index, (key, label, value) in enumerate(settings):
            inputs.columnconfigure(index, weight=1)
            self.variables[key] = tk.StringVar(value=str(value))
            ttk.Label(inputs, text=label, style="Field.TLabel").grid(row=0, column=index, sticky="w")
            entry = ttk.Entry(inputs, textvariable=self.variables[key], width=18)
            entry.grid(row=1, column=index, sticky="ew", padx=(0, 12), pady=(4, 8))
            self.variables[key].trace_add("write", self.invalidate)
            if index == 0:
                self.source_entry = entry
        selection = ttk.Frame(self.body, style="Card.TFrame")
        selection.grid(row=3, column=0, sticky="ew", pady=4)
        ttk.Label(selection, text="Geometry", style="Field.TLabel").pack(side="left")
        self.design = tk.StringVar(value=campaign.plan.designs[0].name)
        self.design_combo = ttk.Combobox(selection, textvariable=self.design, state="readonly",
                                        values=[item.name for item in campaign.plan.designs], width=35)
        self.design_combo.pack(side="left", padx=8)
        self.design_combo.bind("<<ComboboxSelected>>", lambda _event: self.render())
        ttk.Label(selection, text="Ctrl+R: recalculate | Enter on a row: evidence", style="CardText.TLabel").pack(side="left", padx=8)
        self.controls_note = tk.StringVar()
        ttk.Label(self.body, textvariable=self.controls_note, style="CardText.TLabel", wraplength=900).grid(row=4, column=0, sticky="w", pady=4)
        self.tree = _table(self.body, ("scenario", "status", "required_V_RMS", "ceiling_V_RMS", "source_V_RMS", "capacity_W", "setpoint_W", "retention_pct", "minimum_met", "binding_limit"), height=7)
        self.tree.master.grid(row=5, column=0, sticky="nsew", pady=8)
        self.tree.column("scenario", width=160)
        self.tree.column("binding_limit", width=200)
        self.tree.bind("<Return>", self.show_details)
        self.tree.bind("<Double-1>", self.show_details)
        plot = ttk.Frame(self.body, style="Card.TFrame")
        plot.grid(row=6, column=0, sticky="nsew")
        self.chart = tk.Canvas(plot, height=150, highlightthickness=0,
                               background=ttk.Style(self.window).lookup("Card.TFrame", "background"))
        scroll = ttk.Scrollbar(plot, orient="vertical", command=self.chart.yview)
        self.chart.configure(yscrollcommand=scroll.set)
        self.chart.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.chart.bind("<Configure>", lambda _event: self.draw_chart())
        self.summary = tk.StringVar()
        ttk.Label(self.body, textvariable=self.summary, style="CardText.TLabel", wraplength=900).grid(row=7, column=0, sticky="w", pady=8)
        self.actions = ttk.Frame(self.body, style="Card.TFrame")
        self.actions.grid(row=8, column=0, sticky="ew")
        for label, callback in (("Calculate envelope", self.analyze), ("Export CSV", lambda: self.export(".csv")),
                                ("Export HTML", lambda: self.export(".html")), ("Close", self.window.destroy)):
            ttk.Button(self.actions, text=label, command=callback,
                       style="Primary.TButton" if label == "Calculate envelope" else "Secondary.TButton").pack(side="left", padx=(0, 8))
        self.source_entry.focus_set()
        self.analyze()

    def invalidate(self, *_args):
        self.report = None
        if hasattr(self, "tree"):
            self.tree.delete(*self.tree.get_children())
            self.chart.delete("all")
            self.controls_note.set("")
            self.summary.set("Settings changed. Calculate again; exports always use current settings and evidence.")

    def analyze(self):
        self.invalidate()
        try:
            values = {key: float(variable.get()) for key, variable in self.variables.items()}
            limits = EnvelopeLimits(values.pop("max_source_rms_v"))
            settings = replace(self.campaign.settings, target_load_power_w=values.pop("target_load_power_w"))
            campaign = replace(self.campaign, settings=settings, limits=replace(self.campaign.limits, **values))
            self.report = analyze_operating_envelope(campaign, self.jobs_provider(), limits)
        except (OSError, ValueError, OverflowError) as exc:
            self.summary.set(f"Not ready: {exc}")
            return None
        self.render()
        return self.report

    def render(self):
        self.tree.delete(*self.tree.get_children())
        if self.report is None:
            return
        design = next(item for item in self.report.designs if item.name == self.design.get())
        for index, row in enumerate(self.report.rows):
            if row.design != design.name:
                continue
            point = row.operating_point
            self.tree.insert("", "end", iid=str(index), values=(row.scenario, row.status.replace("_", " ").title(),
                             _number(row.required_source_rms_v), _number(row.maximum_source_rms_v),
                             _number(point.source_rms_v if point else None),
                             _number(row.maximum_load_power_w), _number(point.load_ac_w if point else None),
                             _number(row.power_retention * 100 if row.power_retention is not None else None),
                             "Yes" if row.minimum_retention_met else "No" if row.minimum_retention_met is False else "Unavailable",
                             ", ".join(row.limiting_constraints) or row.message))
        controls = design.controls
        self.controls_note.set((f"Fixed: {controls.frequency_hz/1000:.3f} kHz | C1 {controls.primary_capacitance_f*1e9:.3f} nF | "
                               f"C2 {controls.secondary_capacitance_f*1e9:.3f} nF | load {controls.load_ohm:.6g} ohm | "
                               f"minimum retention {self.report.circuit_limits.min_load_power_retention*100:.1f}%")
                              if controls else "Accepted nominal circuit controls are unavailable.")
        self.summary.set(f"{design.name}: {design.status.replace('_', ' ').title()} | {design.evaluated_count}/{design.required_count} evaluable samples | "
                         f"worst sampled capacity: {_number(design.worst_case_maximum_load_power_w)} W.\n"
                         "Capacity is not the setpoint. No interpolation or hardware safety qualification.")
        self.draw_chart()

    def draw_chart(self):
        self.chart.delete("all")
        if self.report is None:
            return
        rows = [item for item in self.report.rows if item.design == self.design.get()]
        target = self.report.settings.target_load_power_w
        scale = max([target] + [item.maximum_load_power_w for item in rows if item.maximum_load_power_w is not None])
        style = ttk.Style(self.window)
        text = style.lookup("CardText.TLabel", "foreground") or "#172630"
        accent = style.lookup("Primary.TButton", "background") or "#287c87"
        width = max(self.chart.winfo_width(), 800)
        start, end = 240, width - 130
        self.chart.create_text(0, 8, anchor="nw", fill=text,
                               text=f"Maximum modeled power (W) | dashed marker: target {target:.0f} W | sampled scenarios only")
        for index, row in enumerate(rows):
            y = 38 + index * 42
            self.chart.create_text(0, y + 10, anchor="w", fill=text, text=row.scenario[:34])
            if row.maximum_load_power_w is not None:
                self.chart.create_rectangle(start, y, start + (end-start)*row.maximum_load_power_w/scale, y+22,
                                             fill=accent, outline="")
                marker = start + (end-start)*target/scale
                self.chart.create_line(marker, y-3, marker, y+25, fill=text, dash=(3, 3), width=2)
            self.chart.create_text(end+10, y+10, anchor="w", fill=text,
                                   text=f"{_number(row.maximum_load_power_w)} W")
        self.chart.configure(scrollregion=(0, 0, width, 44 + len(rows)*42))

    def show_details(self, _event=None):
        if self.report is None or not self.tree.selection():
            return
        row = self.report.rows[int(self.tree.selection()[0])]
        self.detail_window = tk.Toplevel(self.window)
        detail = self.detail_window
        self.detail_window.title(f"Envelope evidence: {row.scenario}")
        self.detail_window.geometry("820x620")
        detail.bind("<Escape>", lambda _event: detail.destroy())
        text = tk.Text(self.detail_window, wrap="word", padx=12, pady=12)
        scroll = ttk.Scrollbar(self.detail_window, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.insert("1.0", LIMITATION + "\n\n" + json.dumps(asdict(row), indent=2, allow_nan=False))
        text.configure(state="disabled")
        text.focus_set()

    def export(self, suffix):
        report = self.analyze()
        if report is None:
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="Export WPT operating envelope",
                                          defaultextension=suffix, filetypes=[("Envelope report", "*" + suffix)])
        if path:
            try:
                output = (write_envelope_csv if suffix == ".csv" else write_envelope_html)(path, report)
                self.summary.set(f"Exported {output.name}. " + LIMITATION)
            except (OSError, ValueError) as exc:
                self.summary.set(f"Export failed: {exc}")


def _number(value):
    return "Unavailable" if value is None else f"{value:.3f}"
