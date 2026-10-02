"""Native editor for resumable, multi-design WPT scenario campaigns."""
from __future__ import annotations

import tkinter as tk
from dataclasses import asdict
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from simulation_assistant.campaigns import estimate_campaign_storage_bytes
from simulation_assistant.design_campaigns import (
    SCENARIO_DIMENSIONS, Scenario, analyze_design_campaign, build_design_campaign,
    designs_from_jobs, require_campaign_identity,
)
from simulation_assistant.design_campaign_reports import (
    design_campaign_rows, load_design_campaign, save_design_campaign,
    write_design_campaign_csv, write_design_campaign_html,
)
from simulation_assistant.model_contract import load_model_contract, validate_contract_parameters
from simulation_assistant.preflight import build_comsol_run_context
from simulation_assistant.sweeps import estimate_sequential_seconds
from simulation_assistant.types import JobStatus
from simulation_assistant.wpt_circuit import (
    CircuitLimits, SeriesSeriesSettings, TwoPortMetricMap, suggest_two_port_metric_names,
)

if TYPE_CHECKING:
    from simulation_assistant.desktop import DesktopApp


def _table(parent, columns, *, height=8, selectmode="browse"):
    frame = ttk.Frame(parent, style="Card.TFrame")
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height,
                       selectmode=selectmode, style="Campaign.Treeview")
    for name in columns:
        tree.heading(name, text=name.replace("_", " ").upper())
        tree.column(name, width=125, minwidth=85)
    vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    return tree


def _scroll_content(parent):
    canvas = tk.Canvas(parent, highlightthickness=0,
                       background=ttk.Style(parent).lookup("Card.TFrame", "background"))
    scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    content = ttk.Frame(canvas, style="Card.TFrame")
    item = canvas.create_window((0, 0), window=content, anchor="nw")
    content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
    return content


class DesignCampaignDialog:
    def __init__(self, app: DesktopApp):
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("WPT Design Scenario Campaign")
        self.window.geometry("1160x820")
        self.window.minsize(920, 680)
        self.window.transient(app.root)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        self.plan = self.report = None
        self.loaded_designs = None
        self.loaded_context = None
        self.loaded_formulas = None
        self.scenarios = [Scenario("Nominal", {}), Scenario("Offset 30 mm", {"xoff": "30[mm]"}),
                          Scenario("Offset 60 mm", {"xoff": "60[mm]"}),
                          Scenario("Tilt 5 deg", {"tilt": "5[deg]"}),
                          Scenario("Gap 180 mm", {"gap": "180[mm]"})]
        self.jobs = app.store.list(status=JobStatus.SUCCEEDED, limit=5000)
        self.accepted_jobs = []
        for job in self.jobs:
            try:
                designs_from_jobs([job])
                self.accepted_jobs.append(job)
            except ValueError:
                continue
        self.body = ttk.Frame(self.window, style="Card.TFrame", padding=18)
        self.body.pack(fill="both", expand=True)
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(4, weight=1)
        style = ttk.Style(self.window)
        style.map("Campaign.Treeview", foreground=[("selected", style.lookup("Treeview", "foreground"))])
        ttk.Label(self.body, text="WPT Design Scenario Campaign", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(self.body, text="Compare geometries under named scenarios, with independent nominal circuit controls.",
                  style="CardText.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 8))
        self.summary = tk.StringVar(value="Select nominal jobs, then click Preview / Analyze.")
        self.identity_note = tk.StringVar(value="Saved results can be reviewed without a COMSOL connection.")
        ttk.Label(self.body, textvariable=self.identity_note, style="CardText.TLabel", wraplength=860).grid(row=2, column=0, sticky="w")
        label_frame = ttk.Frame(self.body, style="Card.TFrame")
        label_frame.grid(row=3, column=0, sticky="ew", pady=8)
        self.batch = tk.StringVar(value=f"wpt-designs-{datetime.now():%Y%m%d-%H%M}")
        ttk.Label(label_frame, text="Run label", style="Field.TLabel").pack(side="left")
        ttk.Entry(label_frame, textvariable=self.batch, width=36).pack(side="left", padx=8)
        for label, callback in (("Load campaign", self.load), ("Save campaign", self.save)):
            ttk.Button(label_frame, text=label, command=callback, style="Secondary.TButton").pack(side="left", padx=4)
        self.tabs = ttk.Notebook(self.body)
        self.tabs.grid(row=4, column=0, sticky="nsew")
        setup, circuit, results = [ttk.Frame(self.tabs, style="Card.TFrame", padding=12) for _ in range(3)]
        for tab, label in ((setup, "1. Designs & scenarios"), (circuit, "2. Circuit settings"), (results, "3. Coverage & results")):
            self.tabs.add(tab, text=label)
        self._build_setup(setup)
        self._build_circuit(_scroll_content(circuit))
        self._build_results(results)
        ttk.Label(self.body, textvariable=self.summary, style="CardText.TLabel", wraplength=860).grid(row=5, column=0, sticky="w", pady=8)
        actions = ttk.Frame(self.body, style="Card.TFrame")
        actions.grid(row=6, column=0, sticky="ew")
        for label, callback in (("Preview / Analyze", self.preview), ("Export CSV", lambda: self.export(".csv")),
                                ("Export HTML", lambda: self.export(".html")),
                                ("Queue remaining", lambda: self.submit(start=False)),
                                ("Run / Resume", lambda: self.submit(start=True))):
            ttk.Button(actions, text=label, command=callback,
                       style="Primary.TButton" if label == "Run / Resume" else "Secondary.TButton").pack(side="left", padx=(0, 8))
        tools = ttk.Frame(self.body, style="Card.TFrame")
        tools.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(tools, text="Power envelope", command=self.open_envelope,
                   style="Secondary.TButton").pack(side="left")
        self.batch_combo.focus_set()

    def open_envelope(self):
        if self.preview() is None:
            return None
        from simulation_assistant.envelope_ui import OperatingEnvelopeDialog
        signatures = tuple(state.signature for state in self.plan.campaign.states)
        return OperatingEnvelopeDialog(self.window, self.report,
                                       lambda: self.app.store.list_by_run_signatures(signatures))

    def _build_setup(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        parent.rowconfigure(5, weight=1)
        ttk.Label(parent, text="Choose one accepted nominal job per geometry (Ctrl/Shift for multiple selection).",
                  style="CardText.TLabel", wraplength=860).grid(row=0, column=0, sticky="w")
        self.batch_filter = tk.StringVar(value="All batches")
        self.batch_combo = ttk.Combobox(parent, textvariable=self.batch_filter, state="readonly",
                                       values=["All batches"] + sorted({job.batch_name for job in self.accepted_jobs}))
        self.batch_combo.grid(row=1, column=0, sticky="ew", pady=4)
        self.design_tree = _table(parent, ("job", "batch", "nominal_inputs"), height=5, selectmode="extended")
        self.design_tree.master.grid(row=2, column=0, sticky="nsew", pady=8)
        self.design_tree.column("nominal_inputs", width=560)
        self.batch_combo.bind("<<ComboboxSelected>>", lambda _event: self.populate_designs())
        self.design_tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.populate_designs()
        self.selection_note = tk.StringVar(value="No designs selected.")
        ttk.Label(parent, textvariable=self.selection_note, style="CardText.TLabel", wraplength=860).grid(row=3, column=0, sticky="w")
        ttk.Label(parent, text="Scenario overrides: blank fields inherit each design's nominal input. Nominal cannot be edited.",
                  style="CardText.TLabel", wraplength=860).grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.scenario_tree = _table(parent, ("name", "gap", "xoff", "yoff", "tilt"), height=5)
        self.scenario_tree.master.grid(row=5, column=0, sticky="nsew", pady=8)
        self.scenario_tree.bind("<<TreeviewSelect>>", self._select_scenario)
        edit = ttk.Frame(parent, style="Card.TFrame")
        edit.grid(row=6, column=0, sticky="ew")
        self.scenario_vars = {name: tk.StringVar() for name in ("name", *SCENARIO_DIMENSIONS)}
        for index, (name, variable) in enumerate(self.scenario_vars.items()):
            edit.columnconfigure(index, weight=1)
            ttk.Label(edit, text=name.upper(), style="Field.TLabel").grid(row=0, column=index, sticky="w")
            ttk.Entry(edit, textvariable=variable, width=16).grid(row=1, column=index, sticky="ew", padx=(0, 8))
        controls = ttk.Frame(parent, style="Card.TFrame")
        controls.grid(row=7, column=0, sticky="ew", pady=8)
        for label, mode in (("Add scenario", "add"), ("Update selected", "update"), ("Remove selected", "remove")):
            ttk.Button(controls, text=label, style="Secondary.TButton", command=lambda m=mode: self.edit_scenario(m)).pack(side="left", padx=(0, 8))
        self.populate_scenarios()

    def populate_designs(self):
        self.design_tree.delete(*self.design_tree.get_children())
        for job in self.accepted_jobs:
            if self.batch_filter.get() not in {"All batches", job.batch_name}:
                continue
            inputs = "; ".join(f"{key}={value}" for key, value in sorted(job.parameters.items()))
            self.design_tree.insert("", "end", iid=str(job.id), values=(f"#{job.id}", job.batch_name, inputs))

    def _selection_changed(self, _event=None):
        if self.design_tree.selection():
            self.loaded_designs = None
            self.selection_note.set(f"{len(self.design_tree.selection())} nominal design(s) selected.")

    def populate_scenarios(self):
        self.scenario_tree.delete(*self.scenario_tree.get_children())
        for index, scenario in enumerate(self.scenarios):
            self.scenario_tree.insert("", "end", iid=str(index), values=(scenario.name,
                                      *(scenario.overrides.get(name, "inherit") for name in SCENARIO_DIMENSIONS)))

    def _select_scenario(self, _event=None):
        if self.scenario_tree.selection():
            scenario = self.scenarios[int(self.scenario_tree.selection()[0])]
            for name, variable in self.scenario_vars.items():
                variable.set(scenario.name if name == "name" else scenario.overrides.get(name, ""))

    def edit_scenario(self, mode):
        selected = self.scenario_tree.selection()
        index = int(selected[0]) if selected else None
        if mode != "add" and (index is None or index == 0):
            self.summary.set("Select a non-Nominal scenario to update or remove.")
            return
        if mode == "remove":
            self.scenarios.pop(index)
        else:
            scenario = Scenario(self.scenario_vars["name"].get().strip(), {
                name: self.scenario_vars[name].get().strip() for name in SCENARIO_DIMENSIONS
                if self.scenario_vars[name].get().strip()})
            if not scenario.name or scenario.name.casefold() == "nominal":
                self.summary.set("Give this scenario a unique, non-Nominal name.")
                return
            if mode == "add":
                self.scenarios.append(scenario)
            else:
                self.scenarios[index] = scenario
        self.populate_scenarios()
        self.summary.set("Scenario rows changed. Preview again before running.")

    def _build_circuit(self, parent):
        ttk.Label(parent, text="Two-port result mapping (SI units)", style="CardTitle.TLabel").pack(anchor="w")
        fields = ttk.Frame(parent, style="Card.TFrame")
        fields.pack(fill="x", pady=8)
        names = sorted({name for job in self.accepted_jobs for name in (job.result or {}).get("metrics", {})})
        suggestions = suggest_two_port_metric_names(names)
        self.metric_vars = {}
        for index, field in enumerate(TwoPortMetricMap.__dataclass_fields__):
            variable = self.metric_vars[field] = tk.StringVar(value=suggestions.get(field, ""))
            column, row = index % 3, (index // 3) * 2
            fields.columnconfigure(column, weight=1)
            ttk.Label(fields, text=field.replace("_", " ").title(), style="Field.TLabel").grid(row=row, column=column, sticky="w")
            ttk.Combobox(fields, textvariable=variable, values=names, width=25).grid(row=row+1, column=column, sticky="ew", padx=(0, 12), pady=(0, 8))
        self.setting_vars = self._numeric_fields(parent, "Nominal tuning", asdict(SeriesSeriesSettings()))
        self.limit_vars = self._numeric_fields(parent, "Circuit limits", asdict(CircuitLimits()))
        ttk.Label(parent, text="Each geometry gets its own tuned C1/C2, load and source voltage. Those controls stay fixed across its scenarios.\n"
                  "AC efficiency is not total charger efficiency. Limits and component assumptions remain provisional.",
                  style="CardText.TLabel", wraplength=1000).pack(anchor="w", pady=12)

    def _numeric_fields(self, parent, title, defaults):
        ttk.Label(parent, text=title, style="CardTitle.TLabel").pack(anchor="w", pady=(8, 4))
        fields = ttk.Frame(parent, style="Card.TFrame")
        fields.pack(fill="x")
        variables = {}
        for index, (name, value) in enumerate(defaults.items()):
            column, row = index % 3, (index // 3) * 2
            fields.columnconfigure(column, weight=1)
            variables[name] = tk.StringVar(value=str(value))
            ttk.Label(fields, text=name.replace("_", " ").title(), style="Field.TLabel").grid(row=row, column=column, sticky="w")
            ttk.Entry(fields, textvariable=variables[name]).grid(row=row+1, column=column, sticky="ew", padx=(0, 12), pady=(0, 8))
        return variables

    def _build_results(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        parent.rowconfigure(1, weight=3)
        self.coverage_tree = _table(parent, ("design", "coverage", "status", "message"), height=4)
        self.coverage_tree.master.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self.coverage_tree.column("message", width=540)
        self.result_tree = _table(parent, ("design", "scenario", "solve", "circuit", "job", "power_W", "eta_AC_pct", "max_I_RMS_A", "max_Vc_RMS_V"), height=10)
        self.result_tree.master.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self.result_tree.bind("<Double-1>", self.show_job)
        self.result_tree.bind("<Return>", self.show_job)
        ttk.Label(parent, text="Double-click a result (or press Enter) to view its job. Missing coverage cannot pass.", style="CardText.TLabel").grid(row=2, column=0, sticky="w")

    def configuration(self):
        mapping = TwoPortMetricMap(**{key: variable.get().strip() for key, variable in self.metric_vars.items()})
        values = {key: float(variable.get()) for key, variable in self.setting_vars.items()}
        count = values["load_samples"]
        if not count.is_integer():
            raise ValueError("Load samples must be an integer")
        values["load_samples"] = int(count)
        return mapping, SeriesSeriesSettings(**values), CircuitLimits(**{key: float(variable.get()) for key, variable in self.limit_vars.items()})

    def build(self):
        if self.loaded_designs is not None:
            designs, context, formulas = self.loaded_designs, self.loaded_context, self.loaded_formulas
        else:
            selected = [self.app.store.get(int(value)) for value in self.design_tree.selection()]
            designs = designs_from_jobs(selected)
            context, formulas = selected[0].run_context, selected[0].output_formulas
        initial = build_design_campaign(designs, self.scenarios, run_context=context,
                                        output_formulas=formulas, existing_jobs=[])
        jobs = self.app.store.list_by_run_signatures(state.signature for state in initial.campaign.states)
        self.plan = build_design_campaign(designs, self.scenarios, run_context=context,
                                         output_formulas=formulas, existing_jobs=jobs)
        mapping, settings, limits = self.configuration()
        self.report = analyze_design_campaign(self.plan, jobs, mapping, settings=settings, limits=limits)
        return self.plan

    def preview(self, *, switch=True):
        try:
            plan = self.build()
        except (OSError, ValueError, OverflowError) as exc:
            self.plan = self.report = None
            self.summary.set(f"Not ready: {exc}")
            self.coverage_tree.delete(*self.coverage_tree.get_children())
            self.result_tree.delete(*self.result_tree.get_children())
            return None
        self.coverage_tree.delete(*self.coverage_tree.get_children())
        self.result_tree.delete(*self.result_tree.get_children())
        for evaluation in self.report.designs:
            self.coverage_tree.insert("", "end", values=(evaluation.design.name,
                                      f"{evaluation.accepted_count}/{evaluation.required_count}", evaluation.status, evaluation.message))
        for index, row in enumerate(design_campaign_rows(self.report)):
            def number(key, percent=False):
                value = row[key]
                return f"{float(value)*(100 if percent else 1):.3f}" if value != "" and value is not None else "-"
            self.result_tree.insert("", "end", iid=str(index), values=(row["design"], row["scenario"], row["solve_status"], row["circuit_status"],
                                    row["job_id"], number("load_ac_w"), number("ac_efficiency", True), number("max_current_rms_a"), number("max_capacitor_rms_v")))
        estimates = []
        accepted = self.app.store.list(status=JobStatus.SUCCEEDED, limit=20)
        duration = estimate_sequential_seconds(len(plan.campaign.pending), accepted)
        storage = estimate_campaign_storage_bytes(len(plan.campaign.pending), accepted)
        if duration is not None:
            estimates.append(f"new solves ~{self.app._format_duration(duration)}")
        if storage is not None:
            estimates.append(f"output models ~{storage/1024**2:.1f} MiB")
        self.summary.set(f"{len(plan.designs)} designs x {len(plan.scenarios)} scenarios = {len(plan.campaign.states)} states | "
                         f"{plan.campaign.completed_count} accepted | {plan.campaign.active_count} active | {len(plan.campaign.pending)} to submit"
                         + (" | " + "; ".join(estimates) if estimates else ""))
        if switch:
            self.tabs.select(2)
        return plan

    def submit(self, *, start):
        if self.app.busy:
            self.summary.set("Wait for the current background operation to finish.")
            return
        plan = self.preview()
        if plan is None:
            return
        try:
            config = self.app._require_connected_config()
            if config.contract_path is None or not config.job_tag:
                raise ValueError("Select an accepted model contract and a COMSOL Job Sequence")
            if ((self.app.connection_report or {}).get("contract") or {}).get("status") not in {"ready", "warning"}:
                raise ValueError("Check connection and accept the model contract preflight first")
            if ((self.app.connection_report or {}).get("result_pipeline") or {}).get("status") != "fresh":
                raise ValueError("Check connection: the Job Sequence result pipeline must be Fresh")
            context = build_comsol_run_context(config.model_path, study_tag=config.study_tag, job_tag=config.job_tag,
                                              plot_tags=config.plot_tags, contract_path=config.contract_path)
            require_campaign_identity(plan, context, self.app._collect_formulas())
            validate_contract_parameters(load_model_contract(config.contract_path), [state.parameters for state in plan.campaign.states])
            if start and self.app.store.is_queue_paused():
                raise ValueError("Resume the run queue before starting campaign jobs")
            if not self.batch.get().strip():
                raise ValueError("Run label cannot be empty")
        except (OSError, ValueError) as exc:
            self.identity_note.set(f"Execution blocked: {exc}")
            return
        self.identity_note.set("Ready: matching model identity, accepted contract and Fresh Job Sequence.")
        queued = [state.job_id for state in plan.campaign.states if state.status == "queued"] if start else []
        pending = plan.campaign.candidates_to_enqueue()
        if not pending and not queued:
            self.summary.set("All states are accepted or already running. Nothing to submit.")
            return
        if not messagebox.askyesno("Confirm design campaign", f"{'Run' if start else 'Queue'} {len(pending)} new/retry states"
                                  + (f" and resume {len(queued)} queued states?" if start else "?"), parent=self.window):
            return
        new_ids = self.app.store.enqueue_batch(self.batch.get().strip(), "comsol", [item.parameters for item in pending],
                                               output_formulas=plan.campaign.output_formulas, run_context=plan.campaign.run_context) if pending else []
        self.app.refresh_jobs()
        self.preview(switch=False)
        if not start:
            self.app.activity_var.set(f"Queued {len(new_ids)} design campaign states.")
            return
        ids = list(dict.fromkeys(queued + new_ids))
        runner = self.app._runner(config)
        def finished(summary):
            self.app._submitted_jobs_finished(ids, summary)
            if self.window.winfo_exists():
                self.preview(switch=False)
        self.app._run_background("run", lambda: self.app._run_job_ids(runner, ids), finished)

    def save(self):
        if self.preview(switch=False) is None:
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="Save design campaign", defaultextension=".json", filetypes=[("Campaign configuration", "*.json")])
        if path:
            try:
                mapping, settings, limits = self.configuration()
                save_design_campaign(path, self.plan, mapping, settings=settings, limits=limits)
                self.identity_note.set("Configuration saved. Load it to recheck coverage and resume after restart.")
            except (OSError, ValueError) as exc:
                self.summary.set(f"Save failed: {exc}")

    def load(self):
        path = filedialog.askopenfilename(parent=self.window, title="Load design campaign", filetypes=[("Campaign configuration", "*.json")])
        if not path:
            return
        try:
            plan, mapping, settings, limits = load_design_campaign(path, [])
        except (OSError, ValueError) as exc:
            self.summary.set(f"Load failed: {exc}")
            return
        self.design_tree.selection_remove(*self.design_tree.selection())
        self.loaded_designs, self.loaded_context, self.loaded_formulas = plan.designs, plan.campaign.run_context, plan.campaign.output_formulas
        self.scenarios = list(plan.scenarios)
        for variables, values in ((self.metric_vars, asdict(mapping)), (self.setting_vars, asdict(settings)), (self.limit_vars, asdict(limits))):
            for name, value in values.items():
                variables[name].set(str(value))
        self.selection_note.set("Loaded designs: " + ", ".join(item.name for item in plan.designs))
        self.populate_scenarios()
        self.identity_note.set("Saved identity loaded. Execution requires the matching connected model and Fresh Job Sequence.")
        self.preview()

    def export(self, suffix):
        if self.preview() is None:
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="Export design campaign", defaultextension=suffix,
                                          filetypes=[("CSV report" if suffix == ".csv" else "HTML report", "*" + suffix)])
        if path:
            try:
                output = (write_design_campaign_csv if suffix == ".csv" else write_design_campaign_html)(path, self.report)
                self.summary.set(f"Exported {output.name}.")
            except (OSError, ValueError) as exc:
                self.summary.set(f"Export failed: {exc}")

    def show_job(self, _event=None):
        selection = self.result_tree.selection()
        if selection:
            job_id = self.result_tree.item(selection[0], "values")[4]
            if job_id:
                self.app._show_job(self.app.store.get(int(job_id)))
