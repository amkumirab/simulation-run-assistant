"""Native budgeted experiment editing, offline evidence review and guarded queueing."""
from __future__ import annotations

import json
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

from simulation_assistant.experiment_files import (
    SavedExperiment, load_experiment, require_experiment_identity, save_experiment, write_experiment_csv,
)
from simulation_assistant.experiments import ExperimentSpec, InputRange, build_experiment_campaign, generate_experiments, validate_spec
from simulation_assistant.model_contract import load_model_contract, validate_contract_parameters
from simulation_assistant.preflight import build_comsol_run_context
from simulation_assistant.sweeps import estimate_sequential_seconds
from simulation_assistant.types import JobStatus


class ExperimentDialog:
    def __init__(self, app):
        self.app = app
        self.saved = self.plan = None
        self.loading = False
        self.inputs = {}
        self.window = tk.Toplevel(app.root)
        self.window.title("WPT Experiment Planner")
        self.window.geometry("1080x800")
        self.window.minsize(920, 680)
        self.window.transient(app.root)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        self.window.bind("<Control-r>", lambda _event: self.refresh())
        body = ttk.Frame(self.window, style="Card.TFrame", padding=18)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1)
        ttk.Label(body, text="WPT Experiment Planner", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.origin = tk.StringVar(value="Explore input ranges within a fixed solve-count budget. No solve starts during planning.")
        ttk.Label(body, textvariable=self.origin, wraplength=850,
                  style="CardText.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 10))
        settings = ttk.Frame(body, style="Card.TFrame")
        settings.grid(row=2, column=0, sticky="ew", pady=8)
        self.budget, self.seed = tk.StringVar(value="30"), tk.StringVar(value="7")
        self.batch = tk.StringVar(value=f"wpt-doe-{datetime.now():%Y%m%d-%H%M}")
        for label, variable, width in (("Max states (1-500)", self.budget, 7), ("Seed", self.seed, 12),
                                       ("Run label", self.batch, 27)):
            ttk.Label(settings, text=label, style="Field.TLabel").pack(side="left", padx=(0, 6))
            ttk.Entry(settings, textvariable=variable, width=width).pack(side="left", padx=(0, 16))
        self.radius = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Require r_in < r_out (length units required)", variable=self.radius,
                        style="Card.TCheckbutton").grid(row=3, column=0, sticky="w", pady=(0, 8))
        tabs = ttk.Notebook(body)
        tabs.grid(row=4, column=0, sticky="nsew")
        setup, results = [ttk.Frame(tabs, style="Card.TFrame", padding=12) for _ in range(2)]
        tabs.add(setup, text="1. Inputs & ranges")
        tabs.add(results, text="2. Experiments & evidence")
        self.tabs = tabs
        setup.columnconfigure(0, weight=1)
        setup.rowconfigure(1, weight=1)
        ttk.Label(setup, text="Fixed inputs inherit the connected editor. Change counts N1/N2 to Integer, not Continuous.",
                  style="CardText.TLabel", wraplength=840).grid(row=0, column=0, sticky="w", pady=(0, 10))
        scroll = ttk.Frame(setup, style="Card.TFrame")
        scroll.grid(row=1, column=0, sticky="nsew")
        canvas = tk.Canvas(scroll, highlightthickness=0, background=ttk.Style(self.window).lookup("Card.TFrame", "background"))
        vertical = ttk.Scrollbar(scroll, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vertical.set)
        vertical.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.editor = ttk.Frame(canvas, style="Card.TFrame")
        item = canvas.create_window(0, 0, window=self.editor, anchor="nw")
        self.editor.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        ttk.Button(setup, text="Import current model inputs", command=self.import_inputs,
                   style="Secondary.TButton").grid(row=2, column=0, sticky="w", pady=8)
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(results, columns=("state", "status", "job", "inputs"), show="headings", height=12)
        for key, title, width in (("state", "State", 65), ("status", "Evidence status", 140),
                                   ("job", "Job ID", 75), ("inputs", "Exact model inputs", 630)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=width, stretch=key == "inputs")
        self.tree.grid(row=0, column=0, sticky="nsew")
        for orientation, row, column, sticky in (("vertical", 0, 1, "ns"), ("horizontal", 1, 0, "ew")):
            bar = ttk.Scrollbar(results, orient=orientation, command=self.tree.yview if orientation == "vertical" else self.tree.xview)
            bar.grid(row=row, column=column, sticky=sticky)
            self.tree.configure(**{"yscrollcommand" if orientation == "vertical" else "xscrollcommand": bar.set})
        self.tree.bind("<Return>", self.show_state)
        self.tree.bind("<Double-1>", self.show_state)
        ttk.Label(results, text="Enter or double-click: open run details, or inspect inputs for an unsubmitted state.",
                  style="CardText.TLabel").grid(row=2, column=0, sticky="w", pady=8)
        self.summary = tk.StringVar(value="Connect a model, import its inputs, configure ranges, then Generate.")
        ttk.Label(body, textvariable=self.summary, style="CardText.TLabel", wraplength=850).grid(row=5, column=0, sticky="w", pady=10)
        actions = ttk.Frame(body, style="Card.TFrame")
        actions.grid(row=6, column=0, sticky="ew")
        for index, (label, callback) in enumerate((("Generate", self.generate), ("Refresh status", self.refresh),
                ("Save plan", self.save), ("Load plan", self.load), ("Export CSV", self.export),
                ("Queue remaining", lambda: self.submit(start=False)), ("Run / Resume", lambda: self.submit(start=True)))):
            ttk.Button(actions, text=label, command=callback,
                       style="Primary.TButton" if label == "Generate" else "Secondary.TButton").grid(row=index // 5, column=index % 5, sticky="w", padx=(0, 8), pady=4)
        for variable in (self.budget, self.seed, self.radius):
            variable.trace_add("write", self.invalidate)
        self.import_inputs()

    def invalidate(self, *_args):
        if self.loading:
            return
        self.saved = self.plan = None
        self.tree.delete(*self.tree.get_children())
        self.summary.set("Settings changed. Generate a new plan before saving or submitting.")

    def populate(self, fixed, ranges=()):
        self.loading = True
        try:
            for widget in self.editor.winfo_children():
                widget.destroy()
            self.inputs = {}
            ranges = {item.name: item for item in ranges}
            for column, label in enumerate(("Model input", "Mode", "Fixed value / Minimum", "Maximum")):
                ttk.Label(self.editor, text=label, style="Field.TLabel").grid(row=0, column=column, sticky="w", padx=8, pady=8)
            for row, name in enumerate(sorted(set(fixed) | set(ranges)), 1):
                definition = ranges.get(name)
                values = (definition.kind.title(), definition.minimum, definition.maximum) if definition else ("Fixed", fixed[name], fixed[name])
                variables = tuple(tk.StringVar(value=value) for value in values)
                self.inputs[name] = variables
                ttk.Label(self.editor, text=name, style="Field.TLabel").grid(row=row, column=0, sticky="w", padx=8, pady=6)
                ttk.Combobox(self.editor, textvariable=variables[0], values=("Fixed", "Continuous", "Integer"),
                             state="readonly", width=15).grid(row=row, column=1, sticky="ew", padx=8)
                for column, variable in enumerate(variables[1:], 2):
                    ttk.Entry(self.editor, textvariable=variable, width=25).grid(row=row, column=column, sticky="ew", padx=8)
                for variable in variables:
                    variable.trace_add("write", self.invalidate)
            for column in (2, 3):
                self.editor.columnconfigure(column, weight=1)
        finally:
            self.loading = False

    def import_inputs(self):
        self.invalidate()
        self.populate({name: variable.get().strip() for name, variable in self.app.parameter_variables.items()})
        if not self.inputs:
            self.summary.set("No model inputs yet. Check connection first, or load a saved plan for offline review.")

    def specification(self):
        fixed, ranges = {}, []
        for name, (mode, low, high) in self.inputs.items():
            if mode.get() == "Fixed":
                fixed[name] = low.get().strip()
            else:
                ranges.append(InputRange(name, low.get().strip(), high.get().strip(), mode.get().lower()))
        return ExperimentSpec(tuple(ranges), fixed, int(self.budget.get()), int(self.seed.get()), self.radius.get())

    def source(self):
        config = self.app._require_connected_config()
        if config.contract_path is None or not config.job_tag:
            raise ValueError("Select a model contract and COMSOL Job Sequence")
        if ((self.app.connection_report or {}).get("contract") or {}).get("status") not in {"ready", "warning"}:
            raise ValueError("Check connection and accept model contract preflight first")
        context = build_comsol_run_context(config.model_path, study_tag=config.study_tag, job_tag=config.job_tag,
                                          plot_tags=config.plot_tags, contract_path=config.contract_path)
        return config, context, self.app._collect_formulas(), load_model_contract(config.contract_path)

    def generate(self):
        self.saved = self.plan = None
        self.tree.delete(*self.tree.get_children())
        try:
            _config, context, formulas, contract = self.source()
            design = generate_experiments(self.specification(), contract)
            self.saved = SavedExperiment(design, context, formulas)
            self.refresh()
            self.tabs.select(1)
            return design
        except (OSError, ValueError, OverflowError) as exc:
            self.summary.set(f"Generation blocked: {exc}")
            return None

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        if self.saved is None:
            self.summary.set("Generate or load a plan first.")
            return None
        initial = build_experiment_campaign(self.saved.design, run_context=self.saved.run_context,
                                            output_formulas=self.saved.output_formulas, existing_jobs=[])
        self.origin.set("Imported stored evidence, not generated DOE solves." if self.saved.method == "stored-points-v1"
                        else "Planned stratified samples. Missing states have no simulation results; acceptance comes from matching jobs.")
        jobs = self.app.store.list_by_run_signatures(state.signature for state in initial.states)
        self.plan = build_experiment_campaign(self.saved.design, run_context=self.saved.run_context,
                                             output_formulas=self.saved.output_formulas, existing_jobs=jobs)
        for state in self.plan.states:
            self.tree.insert("", "end", iid=str(state.index), values=(state.index, state.status, state.job_id or "",
                             "; ".join(f"{name}={value}" for name, value in sorted(state.parameters.items()))))
        successful = [job for job in self.app.store.list(status=JobStatus.SUCCEEDED, limit=500)
                      if job.adapter == "comsol" and job.run_context == self.saved.run_context][:20]
        estimate = estimate_sequential_seconds(len(self.plan.pending), successful)
        shortfall = self.saved.design.shortfall
        self.summary.set(f"{len(self.plan.states)}/{self.saved.design.spec.budget} planned | {self.plan.completed_count} accepted | "
                         f"{self.plan.active_count} active | {len(self.plan.pending)} to submit"
                         + (f" | Shortfall: {shortfall}; unique feasible space or sampling limit reached." if shortfall else "")
                         + (f" | Approx. new-solve time: {self.app._format_duration(estimate)}" if estimate is not None else " | Time estimate unavailable."))
        return self.plan

    def execution_source(self, start):
        if self.saved is None or self.app.busy:
            raise ValueError("Plan or background state changed; review the plan again")
        config, context, formulas, contract = self.source()
        require_experiment_identity(self.saved, context, formulas)
        if ((self.app.connection_report or {}).get("result_pipeline") or {}).get("status") != "fresh":
            raise ValueError("COMSOL Job Sequence result pipeline must be Fresh")
        validate_spec(self.saved.design.spec, contract)
        validate_contract_parameters(contract, self.saved.design.points)
        if start and self.app.store.is_queue_paused():
            raise ValueError("Resume the run queue before starting experiment jobs")
        if not self.batch.get().strip() or len(self.batch.get()) > 100:
            raise ValueError("Run label must contain 1 to 100 characters")
        return config

    def submit(self, *, start):
        if self.app.busy:
            self.summary.set("Wait for the current background operation to finish.")
            return
        plan = self.refresh()
        if plan is None:
            return
        try:
            config = self.execution_source(start)
        except (OSError, ValueError) as exc:
            self.summary.set(f"Execution blocked: {exc}")
            return
        queued = [state.job_id for state in plan.states if state.status == "queued"] if start else []
        pending = plan.candidates_to_enqueue()
        if not pending and not queued:
            self.summary.set("All states are accepted or active. Nothing new to submit.")
            return
        if not messagebox.askyesno("Confirm experiments", f"{'Run' if start else 'Queue'} {len(pending)} new/retry states"
                                  + (f" and resume {len(queued)} queued states?" if start else "?"), parent=self.window):
            return
        try:
            # Confirmation can stay open while model files or job states change.
            config = self.execution_source(start)
            plan = self.refresh()
            pending = plan.candidates_to_enqueue()
            queued = [state.job_id for state in plan.states if state.status == "queued"] if start else []
        except (OSError, ValueError) as exc:
            self.summary.set(f"Execution blocked: {exc}")
            return
        if not pending and not queued:
            self.summary.set("All states are accepted or active. Nothing new to submit.")
            return
        ids = self.app.store.enqueue_batch(self.batch.get().strip(), "comsol", [item.parameters for item in pending],
                                           output_formulas=plan.output_formulas, run_context=plan.run_context) if pending else []
        self.app.refresh_jobs()
        self.refresh()
        if not start:
            self.app.activity_var.set(f"Queued {len(ids)} experiment states. No solver started.")
            return
        ids = list(dict.fromkeys(queued + ids))
        runner = self.app._runner(config)
        def finished(summary):
            self.app._submitted_jobs_finished(ids, summary)
            if self.window.winfo_exists():
                self.refresh()
        self.app._run_background("run", lambda: self.app._run_job_ids(runner, ids), finished)

    def save(self):
        if self.refresh() is None:
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="Save exact experiment plan",
                                          defaultextension=".json", filetypes=[("Experiment plan", "*.json")])
        if path:
            try:
                save_experiment(path, self.saved.design, self.saved.run_context, self.saved.output_formulas, method=self.saved.method)
                self.summary.set("Exact plan saved. Load it after restart to recheck current job evidence.")
            except (OSError, ValueError) as exc:
                self.summary.set(f"Save failed: {exc}")

    def load(self):
        path = filedialog.askopenfilename(parent=self.window, title="Load experiment plan", filetypes=[("Experiment plan", "*.json")])
        if not path:
            return
        self.invalidate()
        try:
            saved = load_experiment(path)
            self.populate(saved.design.spec.fixed, saved.design.spec.ranges)
            self.loading = True
            self.budget.set(str(saved.design.spec.budget))
            self.seed.set(str(saved.design.spec.seed))
            self.radius.set(saved.design.spec.radius_constraint)
            self.loading = False
            self.saved = saved
            self.refresh()
            self.tabs.select(1)
        except (OSError, ValueError) as exc:
            self.summary.set(f"Load failed: {exc}")
        finally:
            self.loading = False

    def export(self):
        if self.refresh() is None:
            return
        path = filedialog.asksaveasfilename(parent=self.window, title="Export experiment evidence",
                                          defaultextension=".csv", filetypes=[("CSV report", "*.csv")])
        if path:
            try:
                output = write_experiment_csv(path, self.plan)
                self.summary.set(f"Exported all {len(self.plan.states)} states to {output.name}.")
            except (OSError, ValueError) as exc:
                self.summary.set(f"Export failed: {exc}")

    def show_state(self, _event=None):
        selection = self.tree.selection()
        if not selection or self.plan is None:
            return
        state = self.plan.states[int(selection[0]) - 1]
        if state.job_id:
            self.app._show_job(self.app.store.get(state.job_id))
        else:
            messagebox.showinfo("Unsubmitted experiment", json.dumps(state.parameters, indent=2), parent=self.window)
