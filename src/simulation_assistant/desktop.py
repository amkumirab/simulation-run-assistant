from __future__ import annotations

import os
import re
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from simulation_assistant.adapters import ComsolAdapter, MockElectromagneticAdapter
from simulation_assistant.adapters.comsol import (
    ComsolConfig,
    check_comsol,
    discover_comsol_executable,
)
from simulation_assistant.formulas import (
    supported_formula_symbols,
    validate_output_formulas,
)
from simulation_assistant.notifications import notifier_from_environment
from simulation_assistant.model_contract import (
    load_model_contract,
    validate_contract_parameters,
)
from simulation_assistant.plot_artifacts import (
    PlotComparisonArtifact,
    format_file_size,
    matching_plot_artifacts,
    parameter_summary,
    preview_subsample_factor,
    resolve_plot_artifact,
    write_plot_comparison_report,
)
from simulation_assistant.preflight import (
    RunPreflightPlan,
    build_comsol_run_context,
    build_preflight_plan,
)
from simulation_assistant.progress import format_duration, inspect_job_progress
from simulation_assistant.profiles import (
    ProfileStore,
    WorkspaceProfile,
    missing_local_paths,
    write_sanitized_profile_template,
)
from simulation_assistant.quantities import (
    common_quantity_dimension,
    parse_quantity,
    reference_unit,
)
from simulation_assistant.ranking import (
    RankingConstraint,
    RankingResult,
    rank_sweep_results,
    write_ranking_csv,
)
from simulation_assistant.runner import SimulationRunner
from simulation_assistant.storage import JobStore
from simulation_assistant.sweeps import (
    build_parameter_sets,
    comparison_rows,
    estimate_sequential_seconds,
    parse_sweep_values,
    write_comparison_csv,
)
from simulation_assistant.types import Job, JobStatus


COLORS = {
    "canvas": "#f3f6f8",
    "surface": "#ffffff",
    "soft": "#f7f9fb",
    "navy": "#16324a",
    "navy_soft": "#24465f",
    "ink": "#172630",
    "muted": "#667681",
    "line": "#dce4e8",
    "blue": "#246bfe",
    "blue_soft": "#eaf1ff",
    "teal": "#087f78",
    "teal_soft": "#e5f6f3",
    "amber": "#95620b",
    "amber_soft": "#fff4d8",
    "red": "#b42318",
    "red_soft": "#feeceb",
}

BUILTIN_OUTPUT_SYMBOLS = [
    ("comsol_duration_seconds", "Application wall-clock time"),
    ("comsol_reported_run_seconds", "COMSOL reported run time"),
    ("comsol_reported_total_seconds", "COMSOL reported total time"),
    ("degrees_of_freedom", "Solved degrees of freedom"),
    ("output_model_bytes", "Output MPH file size"),
]


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, height: int = 220) -> None:
        super().__init__(parent, style="Card.TFrame")
        self.canvas = tk.Canvas(
            self,
            height=height,
            background=COLORS["surface"],
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="Card.TFrame")
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.inner.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_inner)

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_inner(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window, width=event.width)


class ScrollablePage(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, style="App.TFrame")
        self.canvas = tk.Canvas(
            self,
            background=COLORS["canvas"],
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(
            self.canvas,
            style="App.TFrame",
            padding=(0, 12, 8, 0),
        )
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.inner.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_inner)
        self.canvas.bind("<MouseWheel>", self._scroll)

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_inner(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window, width=event.width)

    def _scroll(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class DesktopApp:
    def __init__(
        self,
        root: tk.Tk,
        database_path: str | Path,
        artifact_root: str | Path,
        profile_path: str | Path = ".sim-assistant/profiles.json",
    ) -> None:
        self.root = root
        self.store = JobStore(database_path)
        self.store.initialize()
        self.profile_store = ProfileStore(profile_path)
        self.artifact_root = Path(artifact_root)
        self.connection_report: dict[str, Any] | None = None
        self.selected_plot_tags: list[str] = []
        self.parameter_variables: dict[str, tk.StringVar] = {}
        self.parameter_modes: dict[str, tk.StringVar] = {}
        self.formula_rows: list[tuple[ttk.Frame, tk.StringVar, tk.StringVar]] = []
        self.active_formula_entry: ttk.Entry | None = None
        self.current_comparison_rows: list[dict[str, Any]] = []
        self.current_ranking_result: RankingResult | None = None
        self.ranking_constraint_rows: list[
            tuple[ttk.Frame, tk.StringVar, tk.StringVar, tk.StringVar, ttk.Combobox]
        ] = []
        self.ranking_field_lookup: dict[str, tuple[str, str]] = {}
        self.ranking_field_dimensions: dict[str, str | None] = {}
        self.busy = False
        self._ignore_connection_changes = False

        self._configure_window()
        self._configure_styles()
        self._create_variables()
        self._build_layout()
        self._load_defaults()
        self._restore_last_profile()
        self.refresh_jobs()
        self._observed_running_jobs = self.store.counts()[JobStatus.RUNNING.value]
        self.root.after(1500, self._poll_running_jobs)

    def _configure_window(self) -> None:
        self.root.title("Simulation Run Assistant")
        self.root.geometry("1320x860")
        self.root.minsize(1060, 700)
        self.root.configure(background=COLORS["canvas"])

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("App.TFrame", background=COLORS["canvas"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure(
            "Title.TLabel",
            background=COLORS["canvas"],
            foreground=COLORS["ink"],
            font=("Segoe UI Semibold", 24),
        )
        style.configure(
            "Subtitle.TLabel",
            background=COLORS["canvas"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "CardTitle.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["ink"],
            font=("Segoe UI Semibold", 12),
        )
        style.configure(
            "CardText.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Field.TLabel",
            background=COLORS["surface"],
            foreground="#34454f",
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "Primary.TButton",
            background=COLORS["blue"],
            foreground="white",
            borderwidth=0,
            padding=(15, 9),
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#195fe7"), ("disabled", "#9bb9f8")],
        )
        style.configure(
            "Secondary.TButton",
            background=COLORS["surface"],
            foreground=COLORS["ink"],
            bordercolor="#cbd6dc",
            padding=(13, 8),
            font=("Segoe UI Semibold", 9),
        )
        style.map("Secondary.TButton", background=[("active", COLORS["soft"])])
        style.configure("TEntry", padding=8, fieldbackground="white")
        style.configure("TCombobox", padding=7, fieldbackground="white")
        style.configure(
            "Treeview",
            rowheight=29,
            background="white",
            fieldbackground="white",
            foreground=COLORS["ink"],
            bordercolor=COLORS["line"],
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["soft"],
            foreground=COLORS["muted"],
            font=("Segoe UI Semibold", 8),
            padding=8,
        )
        style.map("Treeview", background=[("selected", COLORS["blue_soft"])])
        style.configure("TNotebook", background=COLORS["canvas"], borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            padding=(16, 9),
            font=("Segoe UI Semibold", 9),
        )

    def _create_variables(self) -> None:
        self.profile_name_var = tk.StringVar()
        self.profile_status_var = tk.StringVar(
            value="Profiles stay local and are never added to run artifacts."
        )
        self.executable_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.contract_var = tk.StringVar()
        self.contract_status_var = tk.StringVar(
            value="No model contract selected. Runs remain available with a warning."
        )
        self.target_mode_var = tk.StringVar(value="study")
        self.study_var = tk.StringVar()
        self.job_var = tk.StringVar()
        self.timeout_var = tk.StringVar(value="3600")
        self.cores_var = tk.StringVar()
        self.batch_var = tk.StringVar(value="desktop-comsol-run")
        self.connection_status_var = tk.StringVar(value="Not checked")
        self.activity_var = tk.StringVar(
            value="Choose a COMSOL model, then validate the connection."
        )
        self.model_summary_var = tk.StringVar(value="No model connected")
        self.freshness_var = tk.StringVar(
            value="Study runs provide fresh solver metrics. Use a COMSOL job sequence "
            "with Evaluate Derived Values for fresh physical output symbols."
        )
        self.compare_metric_var = tk.StringVar()
        self.compare_batch_var = tk.StringVar(value="All batches")
        self.compare_x_var = tk.StringVar()
        self.compare_best_var = tk.StringVar(value="Choose an output metric to compare runs.")
        self.ranking_batch_var = tk.StringVar()
        self.ranking_objective_var = tk.StringVar()
        self.ranking_direction_var = tk.StringVar(value="Maximize")
        self.ranking_summary_var = tk.StringVar(
            value="Choose a completed batch and output objective."
        )
        self.sweep_summary_var = tk.StringVar(value="1 simulation state")
        self.queue_status_var = tk.StringVar(value="Queue status unavailable")

        for variable in (
            self.executable_var,
            self.model_var,
            self.contract_var,
            self.target_mode_var,
            self.study_var,
            self.job_var,
            self.timeout_var,
            self.cores_var,
        ):
            variable.trace_add("write", self._connection_changed)

    def _build_layout(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self._build_sidebar()

        content = ttk.Frame(self.root, style="App.TFrame", padding=(30, 24, 30, 28))
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        header = ttk.Frame(content, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Native COMSOL workspace",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Connect, define computed outputs, run, and compare without a web server.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.status_label = tk.Label(
            header,
            textvariable=self.connection_status_var,
            background=COLORS["amber_soft"],
            foreground=COLORS["amber"],
            padx=12,
            pady=6,
            font=("Segoe UI Semibold", 9),
        )
        self.status_label.grid(row=0, column=1, rowspan=2, sticky="e")

        self.notebook = ttk.Notebook(content)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        workspace = ScrollablePage(self.notebook)
        runs = ttk.Frame(self.notebook, style="App.TFrame", padding=(0, 12, 0, 0))
        compare = ttk.Frame(self.notebook, style="App.TFrame", padding=(0, 12, 0, 0))
        ranking = ttk.Frame(self.notebook, style="App.TFrame", padding=(0, 12, 0, 0))
        self.notebook.add(workspace, text="Workspace")
        self.notebook.add(runs, text="Runs")
        self.notebook.add(compare, text="Compare runs")
        self.notebook.add(ranking, text="Rank results")
        self._build_workspace(workspace.inner)
        self._build_runs_tab(runs)
        self._build_compare(compare)
        self._build_ranking(ranking)

    def _build_sidebar(self) -> None:
        sidebar = tk.Frame(self.root, background=COLORS["navy"], width=226)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        brand = tk.Frame(sidebar, background=COLORS["navy"])
        brand.pack(fill="x", padx=22, pady=(28, 30))
        tk.Label(
            brand,
            text="SRA",
            background=COLORS["blue"],
            foreground="white",
            width=4,
            height=2,
            font=("Segoe UI Semibold", 9),
        ).pack(side="left")
        tk.Label(
            brand,
            text="Simulation\nAssistant",
            justify="left",
            background=COLORS["navy"],
            foreground="white",
            font=("Segoe UI Semibold", 11),
        ).pack(side="left", padx=(11, 0))

        for number, title in (
            ("1", "Connect COMSOL"),
            ("2", "Configure inputs"),
            ("3", "Define outputs"),
            ("4", "Run and compare"),
        ):
            item = tk.Frame(sidebar, background=COLORS["navy_soft"], padx=12, pady=10)
            item.pack(fill="x", padx=17, pady=4)
            tk.Label(
                item,
                text=number,
                background="#315771",
                foreground="#d9e8f2",
                width=2,
                font=("Segoe UI Semibold", 9),
            ).pack(side="left")
            tk.Label(
                item,
                text=title,
                background=COLORS["navy_soft"],
                foreground="#d9e8f2",
                font=("Segoe UI", 9),
            ).pack(side="left", padx=(10, 0))

        assistant = tk.Frame(sidebar, background=COLORS["navy"], padx=22, pady=20)
        assistant.pack(side="bottom", fill="x")
        tk.Label(
            assistant,
            text="RUN ASSISTANT",
            background=COLORS["navy"],
            foreground="#85b7ff",
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w")
        tk.Label(
            assistant,
            textvariable=self.activity_var,
            wraplength=175,
            justify="left",
            background=COLORS["navy"],
            foreground="#b8cbd7",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(8, 0))

    def _build_workspace(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        self._build_connection_card(parent)

        editor_grid = ttk.Frame(parent, style="App.TFrame")
        editor_grid.grid(row=1, column=0, sticky="nsew", pady=(14, 14))
        editor_grid.grid_columnconfigure(0, weight=1, uniform="editor")
        editor_grid.grid_columnconfigure(1, weight=1, uniform="editor")
        self._build_parameters_card(editor_grid)
        self._build_formulas_card(editor_grid)
        self._build_action_bar(parent)

    def _build_connection_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=1)
        card.grid_columnconfigure(2, weight=1)
        card.grid_columnconfigure(3, weight=1)

        ttk.Label(card, text="1  Connect COMSOL", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(
            card,
            textvariable=self.model_summary_var,
            style="CardText.TLabel",
        ).grid(row=0, column=3, sticky="e")

        profile_bar = ttk.Frame(card, style="Card.TFrame")
        profile_bar.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(14, 2))
        profile_bar.grid_columnconfigure(1, weight=1)
        ttk.Label(profile_bar, text="Workspace profile", style="Field.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.profile_selector = ttk.Combobox(
            profile_bar,
            textvariable=self.profile_name_var,
            state="normal",
            width=30,
        )
        self.profile_selector.grid(row=0, column=1, sticky="ew")
        self.profile_selector.bind("<<ComboboxSelected>>", self._profile_selected)
        ttk.Button(
            profile_bar,
            text="New",
            style="Secondary.TButton",
            command=self._new_profile,
        ).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(
            profile_bar,
            text="Save",
            style="Primary.TButton",
            command=self._save_profile,
        ).grid(row=0, column=3, padx=(8, 0))
        ttk.Button(
            profile_bar,
            text="Duplicate",
            style="Secondary.TButton",
            command=self._duplicate_profile,
        ).grid(row=1, column=2, padx=(8, 0), pady=(8, 0))
        ttk.Button(
            profile_bar,
            text="Delete",
            style="Secondary.TButton",
            command=self._delete_profile,
        ).grid(row=1, column=3, padx=(8, 0), pady=(8, 0))
        ttk.Button(
            profile_bar,
            text="Export template",
            style="Secondary.TButton",
            command=self._export_profile_template,
        ).grid(row=1, column=4, padx=(8, 0), pady=(8, 0))
        ttk.Label(
            profile_bar,
            textvariable=self.profile_status_var,
            style="CardText.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self._field_label(card, "COMSOL executable", 2, 0)
        executable = ttk.Entry(card, textvariable=self.executable_var)
        executable.grid(row=3, column=0, columnspan=3, sticky="ew", padx=(0, 8))
        ttk.Button(
            card,
            text="Browse",
            style="Secondary.TButton",
            command=self._browse_executable,
        ).grid(row=3, column=3, sticky="ew")

        self._field_label(card, "MPH model", 4, 0)
        model = ttk.Entry(card, textvariable=self.model_var)
        model.grid(row=5, column=0, columnspan=3, sticky="ew", padx=(0, 8))
        ttk.Button(
            card,
            text="Browse",
            style="Secondary.TButton",
            command=self._browse_model,
        ).grid(row=5, column=3, sticky="ew")

        self._field_label(card, "Model contract (optional JSON)", 6, 0)
        ttk.Entry(card, textvariable=self.contract_var).grid(
            row=7, column=0, columnspan=3, sticky="ew", padx=(0, 8)
        )
        ttk.Button(
            card,
            text="Browse",
            style="Secondary.TButton",
            command=self._browse_contract,
        ).grid(row=7, column=3, sticky="ew")
        ttk.Label(
            card,
            textvariable=self.contract_status_var,
            style="CardText.TLabel",
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Button(
            card,
            text="View preflight",
            style="Secondary.TButton",
            command=self._show_contract_report,
        ).grid(row=8, column=3, sticky="ew", pady=(6, 0))

        mode_frame = ttk.Frame(card, style="Card.TFrame")
        mode_frame.grid(row=9, column=0, columnspan=4, sticky="ew", pady=(13, 0))
        mode_frame.grid_columnconfigure(1, weight=1)
        mode_frame.grid_columnconfigure(3, weight=1)
        ttk.Radiobutton(
            mode_frame,
            text="Study",
            value="study",
            variable=self.target_mode_var,
            command=self._toggle_target,
        ).grid(row=0, column=0, sticky="w")
        self.study_entry = ttk.Combobox(
            mode_frame,
            textvariable=self.study_var,
            state="normal",
        )
        self.study_entry.grid(row=0, column=1, sticky="ew", padx=(7, 16))
        ttk.Radiobutton(
            mode_frame,
            text="Job sequence",
            value="job",
            variable=self.target_mode_var,
            command=self._toggle_target,
        ).grid(row=0, column=2, sticky="w")
        self.job_entry = ttk.Entry(mode_frame, textvariable=self.job_var)
        self.job_entry.grid(row=0, column=3, sticky="ew", padx=(7, 16))
        ttk.Label(mode_frame, text="Timeout", style="Field.TLabel").grid(
            row=0, column=4, sticky="w"
        )
        ttk.Entry(mode_frame, width=8, textvariable=self.timeout_var).grid(
            row=0, column=5, padx=(7, 12)
        )
        ttk.Label(mode_frame, text="Cores", style="Field.TLabel").grid(
            row=0, column=6, sticky="w"
        )
        ttk.Entry(mode_frame, width=6, textvariable=self.cores_var).grid(
            row=0, column=7, padx=(7, 12)
        )
        self.check_button = ttk.Button(
            mode_frame,
            text="Check connection",
            style="Primary.TButton",
            command=self.check_connection,
        )
        self.check_button.grid(row=0, column=8)
        self._toggle_target()

        plot_frame = ttk.Frame(card, style="Card.TFrame")
        plot_frame.grid(row=10, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        plot_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(plot_frame, text="Plot outputs", style="Field.TLabel").grid(
            row=0, column=0, sticky="nw", padx=(0, 10), pady=(7, 0)
        )
        self.plot_groups_list = tk.Listbox(
            plot_frame,
            height=3,
            selectmode=tk.EXTENDED,
            exportselection=False,
            background="white",
            foreground=COLORS["ink"],
            selectbackground=COLORS["blue"],
            selectforeground="white",
            highlightthickness=1,
            highlightbackground=COLORS["line"],
            relief="flat",
            font=("Segoe UI", 9),
        )
        self.plot_groups_list.grid(row=0, column=1, sticky="ew")
        self.plot_groups_list.bind("<<ListboxSelect>>", self._plot_selection_changed)
        plot_actions = ttk.Frame(plot_frame, style="Card.TFrame")
        plot_actions.grid(row=0, column=2, sticky="n", padx=(8, 0))
        ttk.Button(
            plot_actions,
            text="Select all",
            style="Secondary.TButton",
            command=self._select_all_plots,
        ).pack(fill="x")
        ttk.Button(
            plot_actions,
            text="Clear",
            style="Secondary.TButton",
            command=self._clear_plot_selection,
        ).pack(fill="x", pady=(6, 0))
        self.plot_selection_note = ttk.Label(
            plot_frame,
            text="Check the connection to discover saved 1D, 2D, and 3D Plot Groups.",
            style="CardText.TLabel",
        )
        self.plot_selection_note.grid(row=1, column=1, sticky="w", pady=(6, 0))

    def _build_parameters_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        card.grid_columnconfigure(0, weight=1)
        ttk.Label(card, text="2  Model inputs", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card,
            text="Set each input to Fixed or Sweep. Sweep accepts a list or start:stop:step.",
            style="CardText.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 12))
        self.parameters_frame = ScrollableFrame(card, height=210)
        self.parameters_frame.grid(row=2, column=0, sticky="nsew")
        card.grid_rowconfigure(2, weight=1)
        self._show_empty_parameters()

    def _build_formulas_card(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(3, weight=1)
        top = ttk.Frame(card, style="Card.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        ttk.Label(top, text="3  Computed outputs", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            top,
            text="+ Add formula",
            style="Secondary.TButton",
            command=self.add_formula_row,
        ).grid(row=0, column=1, sticky="e")
        ttk.Label(
            card,
            text="Use metric symbols with +, -, *, /, **, sqrt, log, min, or max.",
            style="CardText.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 10))
        self.formulas_frame = ScrollableFrame(card, height=105)
        self.formulas_frame.grid(row=2, column=0, sticky="ew")
        self.add_formula_row()

        symbols_frame = ttk.Frame(card, style="Card.TFrame")
        symbols_frame.grid(row=3, column=0, sticky="nsew", pady=(11, 0))
        symbols_frame.grid_columnconfigure(0, weight=1)
        symbols_frame.grid_rowconfigure(1, weight=1)
        ttk.Label(
            symbols_frame,
            text="Available output symbols — double-click to insert",
            style="Field.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        self.symbols_tree = ttk.Treeview(
            symbols_frame,
            columns=("symbol", "source", "saved"),
            show="headings",
            height=5,
        )
        self.symbols_tree.heading("symbol", text="SYMBOL")
        self.symbols_tree.heading("source", text="SOURCE")
        self.symbols_tree.heading("saved", text="SAVED VALUE")
        self.symbols_tree.column("symbol", width=210, stretch=True)
        self.symbols_tree.column("source", width=120)
        self.symbols_tree.column("saved", width=100, anchor="e")
        self.symbols_tree.grid(row=1, column=0, sticky="nsew")
        self.symbols_tree.bind("<Double-1>", self._insert_selected_symbol)
        self._populate_builtin_symbols()

    def _build_action_bar(self, parent: ttk.Frame) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=2, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        title = ttk.Frame(card, style="Card.TFrame")
        title.grid(row=0, column=0, sticky="ew")
        title.grid_columnconfigure(1, weight=1)
        ttk.Label(title, text="4  Ready to simulate", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        ttk.Label(title, textvariable=self.freshness_var, style="CardText.TLabel").grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(
            title,
            textvariable=self.sweep_summary_var,
            style="Field.TLabel",
        ).grid(row=0, column=2, sticky="e", padx=(12, 0))
        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(actions, text="Run label", style="Field.TLabel").pack(side="left")
        ttk.Entry(actions, textvariable=self.batch_var, width=34).pack(
            side="left", padx=(8, 16)
        )
        self.run_now_button = ttk.Button(
            actions,
            text="Run now",
            style="Primary.TButton",
            command=lambda: self.submit_run(start=True),
            state="disabled",
        )
        self.run_now_button.pack(side="left")
        self.queue_button = ttk.Button(
            actions,
            text="Queue only",
            style="Secondary.TButton",
            command=lambda: self.submit_run(start=False),
            state="disabled",
        )
        self.queue_button.pack(side="left", padx=(8, 0))
        self.run_next_button = ttk.Button(
            actions,
            text="Run next",
            style="Secondary.TButton",
            command=self.run_next,
            state="disabled",
        )
        self.run_next_button.pack(side="left", padx=(8, 0))
        self.review_plan_button = ttk.Button(
            actions,
            text="Review plan",
            style="Secondary.TButton",
            command=self._review_run_plan,
            state="disabled",
        )
        self.review_plan_button.pack(side="left", padx=(8, 0))
        ttk.Button(
            actions,
            text="Open run queue",
            style="Secondary.TButton",
            command=lambda: self.notebook.select(1),
        ).pack(side="right")

    def _build_runs_tab(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)
        toolbar = ttk.Frame(card, style="Card.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        toolbar.grid_columnconfigure(0, weight=1)
        ttk.Label(toolbar, text="Local run queue", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            toolbar,
            textvariable=self.queue_status_var,
            style="CardText.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        controls = ttk.Frame(toolbar, style="Card.TFrame")
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        self.pause_queue_button = ttk.Button(
            controls,
            text="Pause queue",
            style="Secondary.TButton",
            command=self._toggle_queue_pause,
        )
        self.pause_queue_button.pack(side="left")
        self.cancel_job_button = ttk.Button(
            controls,
            text="Cancel selected",
            style="Secondary.TButton",
            command=self._cancel_selected_job,
            state="disabled",
        )
        self.cancel_job_button.pack(side="left", padx=(8, 0))
        self.recover_jobs_button = ttk.Button(
            controls,
            text="Recover interrupted",
            style="Secondary.TButton",
            command=self._recover_interrupted_jobs,
            state="disabled",
        )
        self.recover_jobs_button.pack(side="left", padx=(8, 0))
        ttk.Button(
            controls,
            text="Refresh",
            style="Secondary.TButton",
            command=self.refresh_jobs,
        ).pack(side="left", padx=(8, 0))

        self.jobs_tree = ttk.Treeview(
            card,
            columns=(
                "id",
                "batch",
                "status",
                "progress",
                "adapter",
                "attempts",
                "created",
            ),
            show="headings",
            height=7,
        )
        headings = {
            "id": "ID",
            "batch": "RUN",
            "status": "STATUS",
            "progress": "LIVE PROGRESS",
            "adapter": "ADAPTER",
            "attempts": "ATTEMPTS",
            "created": "CREATED",
        }
        widths = {
            "id": 60,
            "batch": 220,
            "status": 90,
            "progress": 260,
            "adapter": 85,
            "attempts": 75,
            "created": 155,
        }
        for column, heading in headings.items():
            self.jobs_tree.heading(column, text=heading)
            self.jobs_tree.column(
                column,
                width=widths[column],
                stretch=column in {"batch", "progress", "created"},
            )
        self.jobs_tree.grid(row=1, column=0, sticky="nsew")
        self.jobs_tree.bind("<Double-1>", self._open_selected_job)
        self.jobs_tree.bind("<<TreeviewSelect>>", self._queue_selection_changed)

    def _build_compare(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        header = ttk.Frame(parent, style="Card.TFrame", padding=18)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(header, text="Compare computed outputs", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        controls = ttk.Frame(header, style="Card.TFrame")
        controls.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        controls.grid_columnconfigure(1, weight=1)
        controls.grid_columnconfigure(3, weight=1)
        ttk.Label(controls, text="Batch", style="Field.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 7)
        )
        self.compare_batch = ttk.Combobox(
            controls,
            textvariable=self.compare_batch_var,
            state="readonly",
            width=18,
        )
        self.compare_batch.grid(row=0, column=1, sticky="ew")
        self.compare_batch.bind("<<ComboboxSelected>>", self._comparison_filter_changed)
        ttk.Label(controls, text="X input", style="Field.TLabel").grid(
            row=0, column=2, sticky="e", padx=(14, 7)
        )
        self.compare_x = ttk.Combobox(
            controls,
            textvariable=self.compare_x_var,
            state="readonly",
            width=13,
        )
        self.compare_x.grid(row=0, column=3, sticky="ew")
        self.compare_x.bind("<<ComboboxSelected>>", self._refresh_comparison_rows)
        ttk.Label(controls, text="Output", style="Field.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 7), pady=(10, 0)
        )
        self.compare_metric = ttk.Combobox(
            controls,
            textvariable=self.compare_metric_var,
            state="readonly",
            width=28,
        )
        self.compare_metric.grid(
            row=1,
            column=1,
            columnspan=2,
            sticky="ew",
            pady=(10, 0),
        )
        self.compare_metric.bind("<<ComboboxSelected>>", self._refresh_comparison_rows)
        ttk.Button(
            controls,
            text="Export CSV",
            style="Secondary.TButton",
            command=self._export_comparison,
        ).grid(row=1, column=3, sticky="e", padx=(10, 0), pady=(10, 0))

        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=1, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(2, weight=1)
        summary = ttk.Frame(card, style="Card.TFrame")
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        summary.grid_columnconfigure(0, weight=1)
        ttk.Label(
            summary,
            textvariable=self.compare_best_var,
            style="CardText.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            summary,
            text="Refresh",
            style="Secondary.TButton",
            command=self.refresh_comparison,
        ).grid(row=0, column=1, sticky="e")

        self.compare_chart = tk.Canvas(
            card,
            height=220,
            background=COLORS["soft"],
            highlightthickness=1,
            highlightbackground=COLORS["line"],
        )
        self.compare_chart.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.compare_chart.bind("<Configure>", lambda _event: self._draw_comparison_chart())
        self.compare_tree = ttk.Treeview(
            card,
            columns=("id", "batch", "parameters", "value", "finished"),
            show="headings",
        )
        for column, heading, width in (
            ("id", "JOB", 65),
            ("batch", "RUN", 230),
            ("parameters", "INPUT STATE", 470),
            ("value", "OUTPUT VALUE", 150),
            ("finished", "FINISHED", 170),
        ):
            self.compare_tree.heading(column, text=heading)
            self.compare_tree.column(
                column,
                width=width,
                stretch=column in {"batch", "parameters"},
            )
        self.compare_tree.grid(row=2, column=0, sticky="nsew")

    def _build_ranking(self, parent: ttk.Frame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        header = ttk.Frame(parent, style="Card.TFrame", padding=18)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="Rank completed sweep results",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, columnspan=6, sticky="w")
        ttk.Label(
            header,
            text=(
                "Find the strongest feasible run using one objective and optional "
                "input or output limits."
            ),
            style="CardText.TLabel",
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(3, 12))
        for column in (1, 3):
            header.grid_columnconfigure(column, weight=1)
        ttk.Label(header, text="Batch", style="Field.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 7)
        )
        self.ranking_batch = ttk.Combobox(
            header,
            textvariable=self.ranking_batch_var,
            state="readonly",
            width=20,
        )
        self.ranking_batch.grid(row=2, column=1, sticky="ew")
        self.ranking_batch.bind("<<ComboboxSelected>>", self._ranking_batch_changed)
        ttk.Label(header, text="Objective", style="Field.TLabel").grid(
            row=2, column=2, sticky="e", padx=(14, 7)
        )
        self.ranking_objective = ttk.Combobox(
            header,
            textvariable=self.ranking_objective_var,
            state="readonly",
            width=25,
        )
        self.ranking_objective.grid(row=2, column=3, sticky="ew")
        self.ranking_objective.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._calculate_ranking(show_errors=False),
        )
        ttk.Label(header, text="Direction", style="Field.TLabel").grid(
            row=2, column=4, sticky="e", padx=(14, 7)
        )
        self.ranking_direction = ttk.Combobox(
            header,
            textvariable=self.ranking_direction_var,
            values=("Maximize", "Minimize"),
            state="readonly",
            width=10,
        )
        self.ranking_direction.grid(row=2, column=5, sticky="e")
        self.ranking_direction.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._calculate_ranking(show_errors=False),
        )

        constraints = ttk.Frame(parent, style="Card.TFrame", padding=18)
        constraints.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        constraints.grid_columnconfigure(0, weight=1)
        constraint_header = ttk.Frame(constraints, style="Card.TFrame")
        constraint_header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        constraint_header.grid_columnconfigure(0, weight=1)
        ttk.Label(
            constraint_header,
            text="Feasibility constraints",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            constraint_header,
            text=(
                "Dimensional inputs require an explicit supported unit; "
                "comparisons are normalized to SI."
            ),
            style="CardText.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Button(
            constraint_header,
            text="Clear",
            style="Secondary.TButton",
            command=self._clear_ranking_constraints,
        ).grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Button(
            constraint_header,
            text="+ Add constraint",
            style="Secondary.TButton",
            command=self._add_ranking_constraint,
        ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(8, 0))
        self.ranking_constraints_frame = ttk.Frame(
            constraints, style="Card.TFrame"
        )
        self.ranking_constraints_frame.grid(row=1, column=0, sticky="ew")
        self.ranking_constraints_frame.grid_columnconfigure(0, weight=1)
        self._add_ranking_constraint()

        results = ttk.Frame(parent, style="Card.TFrame", padding=18)
        results.grid(row=2, column=0, sticky="nsew")
        results.grid_columnconfigure(0, weight=1)
        results.grid_rowconfigure(1, weight=1)
        result_header = ttk.Frame(results, style="Card.TFrame")
        result_header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        result_header.grid_columnconfigure(0, weight=1)
        ttk.Label(
            result_header,
            textvariable=self.ranking_summary_var,
            style="CardText.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            result_header,
            text="Export CSV",
            style="Secondary.TButton",
            command=self._export_ranking,
        ).grid(row=0, column=1, sticky="e")
        ttk.Button(
            result_header,
            text="Apply ranking",
            style="Primary.TButton",
            command=lambda: self._calculate_ranking(show_errors=True),
        ).grid(row=0, column=2, sticky="e", padx=(8, 0))

        self.ranking_tree = ttk.Treeview(
            results,
            columns=("rank", "job", "objective", "constraints", "parameters", "finished"),
            show="headings",
        )
        for column, heading, width in (
            ("rank", "RANK", 60),
            ("job", "JOB", 65),
            ("objective", "OBJECTIVE VALUE", 145),
            ("constraints", "CONSTRAINT VALUES", 300),
            ("parameters", "INPUT STATE", 400),
            ("finished", "FINISHED", 160),
        ):
            self.ranking_tree.heading(column, text=heading)
            self.ranking_tree.column(
                column,
                width=width,
                stretch=column in {"constraints", "parameters"},
            )
        self.ranking_tree.grid(row=1, column=0, sticky="nsew")
        self.ranking_tree.bind("<Double-1>", self._open_ranked_job)

    def _field_label(self, parent: ttk.Frame, text: str, row: int, column: int) -> None:
        ttk.Label(parent, text=text, style="Field.TLabel").grid(
            row=row,
            column=column,
            columnspan=4,
            sticky="w",
            pady=(11, 5),
        )

    def _load_defaults(self) -> None:
        self._ignore_connection_changes = True
        try:
            executable = os.getenv("COMSOL_EXECUTABLE")
            if not executable:
                try:
                    executable = str(discover_comsol_executable())
                except ValueError:
                    executable = ""
            self.executable_var.set(executable)
            self.model_var.set(os.getenv("COMSOL_MODEL_PATH", ""))
            self.contract_var.set(os.getenv("COMSOL_CONTRACT_PATH", ""))
            self.study_var.set(os.getenv("COMSOL_STUDY_TAG", ""))
            self.job_var.set(os.getenv("COMSOL_JOB_TAG", ""))
            self.timeout_var.set(os.getenv("COMSOL_TIMEOUT_SECONDS", "3600"))
            self.cores_var.set(os.getenv("COMSOL_CORES", ""))
            if self.job_var.get():
                self.target_mode_var.set("job")
            self._toggle_target()
        finally:
            self._ignore_connection_changes = False
        if self.executable_var.get():
            self.activity_var.set(
                "COMSOL was detected. Choose an MPH model and check the connection."
            )

    def _restore_last_profile(self) -> None:
        try:
            self._refresh_profile_choices()
            profile = self.profile_store.last()
        except ValueError as exc:
            self.profile_status_var.set("Profile storage needs attention.")
            self.activity_var.set(str(exc))
            messagebox.showwarning("Workspace profiles", str(exc), parent=self.root)
            return
        if profile is not None:
            self._apply_profile(profile, warn_missing=True)

    def _refresh_profile_choices(self) -> None:
        profiles = self.profile_store.list()
        self.profile_selector.configure(values=[profile.name for profile in profiles])

    def _profile_selected(self, _event: tk.Event | None = None) -> None:
        name = self.profile_name_var.get().strip()
        if not name:
            return
        try:
            profile = self.profile_store.get(name)
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Workspace profile", str(exc), parent=self.root)
            return
        self._apply_profile(profile, warn_missing=True)

    def _apply_profile(
        self,
        profile: WorkspaceProfile,
        *,
        warn_missing: bool,
    ) -> None:
        self.connection_report = None
        self._ignore_connection_changes = True
        try:
            self.profile_name_var.set(profile.name)
            self.executable_var.set(profile.executable_path)
            self.model_var.set(profile.model_path)
            self.contract_var.set(profile.contract_path)
            self.target_mode_var.set(profile.target_mode)
            self.study_var.set(profile.study_tag)
            self.job_var.set(profile.job_tag)
            self.timeout_var.set(str(profile.timeout_seconds))
            self.cores_var.set(str(profile.cores) if profile.cores is not None else "")
            self.batch_var.set(profile.batch_name)
            self.selected_plot_tags = list(profile.plot_tags)
            self.plot_groups_list.delete(0, tk.END)
            self.plot_selection_note.configure(
                text=(
                    f"{len(self.selected_plot_tags)} saved plot selection(s); "
                    "check the connection to match them to this model."
                )
            )
            self._toggle_target()
            self._populate_parameters(profile.parameters)
            self._apply_profile_parameter_values(profile)
            self._replace_formulas(profile.output_formulas)
        finally:
            self._ignore_connection_changes = False

        try:
            self.profile_store.set_last(profile.name)
            self._refresh_profile_choices()
        except (KeyError, OSError, ValueError) as exc:
            self.profile_status_var.set(str(exc))
        self.connection_status_var.set("Needs check")
        self.status_label.configure(
            background=COLORS["amber_soft"], foreground=COLORS["amber"]
        )
        self.model_summary_var.set(f"{Path(profile.model_path).name}  ·  profile loaded")
        self._set_run_actions(False)

        missing = missing_local_paths(profile)
        if missing:
            labels = ", ".join(label for label, _path in missing)
            self.profile_status_var.set(
                f"Loaded locally. Missing: {labels}. Browse to the new location and save again."
            )
            self.activity_var.set(f"Profile '{profile.name}' loaded with missing local files.")
            if warn_missing:
                details = "\n".join(f"{label}: {path}" for label, path in missing)
                messagebox.showwarning(
                    "Profile paths not found",
                    "Some local files have moved or are unavailable:\n\n"
                    f"{details}\n\nBrowse to each new location, then save the profile.",
                    parent=self.root,
                )
        else:
            self.profile_status_var.set(
                "Loaded from local storage. Check the COMSOL connection before running."
            )
            self.activity_var.set(
                f"Profile '{profile.name}' restored. Validate COMSOL to continue."
            )

    def _capture_profile(self, name: str) -> WorkspaceProfile:
        timeout = self._positive_int(self.timeout_var.get(), "Timeout")
        cores_text = self.cores_var.get().strip()
        cores = self._positive_int(cores_text, "Core count") if cores_text else None
        parameters = {
            parameter_name: variable.get().strip()
            for parameter_name, variable in self.parameter_variables.items()
        }
        modes = {
            parameter_name: self.parameter_modes[parameter_name].get()
            for parameter_name in parameters
        }
        return WorkspaceProfile.create(
            name=name,
            executable_path=self.executable_var.get(),
            model_path=self.model_var.get(),
            contract_path=self.contract_var.get(),
            target_mode=self.target_mode_var.get(),
            study_tag=self.study_var.get(),
            job_tag=self.job_var.get(),
            timeout_seconds=timeout,
            cores=cores,
            batch_name=self.batch_var.get(),
            parameters=parameters,
            parameter_modes=modes,
            output_formulas=self._collect_formulas(),
            plot_tags=tuple(self.selected_plot_tags),
        )

    def _save_profile(self) -> None:
        name = self.profile_name_var.get().strip()
        if not name:
            name = simpledialog.askstring(
                "Save workspace profile",
                "Profile name:",
                parent=self.root,
            ) or ""
        if not name:
            return
        try:
            profile = self._capture_profile(name)
            self.profile_store.save(profile)
            saved = self.profile_store.get(name)
            self._refresh_profile_choices()
        except (KeyError, OSError, ValueError) as exc:
            messagebox.showerror("Save workspace profile", str(exc), parent=self.root)
            return
        self.profile_name_var.set(saved.name)
        self.profile_status_var.set(
            f"Saved locally as '{saved.name}'. Local model paths are not added to run artifacts."
        )
        self.activity_var.set(f"Workspace profile '{saved.name}' was saved locally.")

    def _new_profile(self) -> None:
        self.profile_name_var.set("")
        self.profile_status_var.set(
            "Enter a new profile name. Current workspace values are kept as a starting point."
        )
        self.activity_var.set("Edit the workspace, enter a profile name, then select Save.")
        self.profile_selector.focus_set()

    def _duplicate_profile(self) -> None:
        source_name = self.profile_name_var.get().strip()
        if not source_name:
            messagebox.showinfo(
                "Duplicate workspace profile",
                "Select a saved profile first.",
                parent=self.root,
            )
            return
        new_name = simpledialog.askstring(
            "Duplicate workspace profile",
            "New profile name:",
            initialvalue=f"{source_name} copy",
            parent=self.root,
        )
        if not new_name:
            return
        try:
            duplicate = self.profile_store.duplicate(source_name, new_name)
            self._refresh_profile_choices()
        except (KeyError, OSError, ValueError) as exc:
            messagebox.showerror("Duplicate workspace profile", str(exc), parent=self.root)
            return
        self._apply_profile(duplicate, warn_missing=False)
        self.profile_status_var.set(f"Created local profile '{duplicate.name}'.")

    def _delete_profile(self) -> None:
        name = self.profile_name_var.get().strip()
        if not name:
            return
        confirmed = messagebox.askyesno(
            "Delete workspace profile",
            f"Delete the local profile '{name}'?\n\nSimulation results are not affected.",
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self.profile_store.delete(name)
            self._refresh_profile_choices()
        except (KeyError, OSError, ValueError) as exc:
            messagebox.showerror("Delete workspace profile", str(exc), parent=self.root)
            return
        self.profile_name_var.set("")
        self.profile_status_var.set(
            "Profile deleted locally. Current workspace values were kept."
        )
        self.activity_var.set(f"Workspace profile '{name}' was deleted.")

    def _export_profile_template(self) -> None:
        name = self.profile_name_var.get().strip() or "workspace-template"
        try:
            profile = self._capture_profile(name)
        except ValueError as exc:
            messagebox.showerror("Export profile template", str(exc), parent=self.root)
            return
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-")
        selected = filedialog.asksaveasfilename(
            title="Export sanitized workspace template",
            defaultextension=".json",
            initialfile=f"{safe_name or 'workspace-template'}.json",
            filetypes=[("JSON file", "*.json"), ("All files", "*")],
        )
        if not selected:
            return
        try:
            output = write_sanitized_profile_template(selected, profile)
        except OSError as exc:
            messagebox.showerror("Export profile template", str(exc), parent=self.root)
            return
        self.profile_status_var.set(
            "Template exported without the COMSOL executable or MPH model path."
        )
        self.activity_var.set(f"Sanitized workspace template exported to {output.name}.")

    def _browse_executable(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select COMSOL batch executable",
            filetypes=[("COMSOL batch executable", "comsolbatch.exe"), ("All files", "*")],
        )
        if selected:
            self.executable_var.set(selected)

    def _browse_model(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select COMSOL model",
            filetypes=[("COMSOL model", "*.mph"), ("All files", "*")],
        )
        if selected:
            self.selected_plot_tags = []
            self.plot_groups_list.delete(0, tk.END)
            self.plot_selection_note.configure(
                text="Check the connection to discover this model's Plot Groups."
            )
            self.model_var.set(selected)

    def _browse_contract(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select model contract",
            filetypes=[("Model contract", "*.json"), ("All files", "*")],
        )
        if selected:
            self.contract_var.set(selected)

    def _show_contract_report(self) -> None:
        report = (self.connection_report or {}).get("contract")
        if report is None:
            messagebox.showinfo(
                "Model contract preflight",
                "No model contract is selected. Add a versioned JSON contract "
                "and check the connection again.",
                parent=self.root,
            )
            return
        issues = report.get("issues", [])
        lines = [
            f"Status: {str(report.get('status', 'unknown')).upper()}",
            f"Contract: {report.get('contract_name', '')} {report.get('contract_version', '')}",
            f"Design inputs: {len(report.get('design_inputs', []))}",
            f"Internal parameters: {len(report.get('internal_parameters', []))}",
            f"Output bindings: {len(report.get('output_bindings', {}))}",
        ]
        if issues:
            lines.append("")
            lines.append("Findings:")
            lines.extend(
                f"- {str(issue.get('level', 'info')).upper()}: {issue.get('message', '')}"
                for issue in issues
            )
        else:
            lines.extend(["", "All contract requirements were satisfied."])
        messagebox.showinfo(
            "Model contract preflight",
            "\n".join(lines),
            parent=self.root,
        )

    def _toggle_target(self) -> None:
        if self.target_mode_var.get() == "job":
            self.study_entry.configure(state="disabled")
            self.job_entry.configure(state="normal")
            self.freshness_var.set(
                "Job sequence mode can provide fresh Derived Values when configured in COMSOL."
            )
        else:
            self.study_entry.configure(state="normal")
            self.job_entry.configure(state="disabled")
            self.freshness_var.set(
                "Study mode keeps saved table values out of fresh output formulas."
            )

    def _connection_changed(self, *_args: object) -> None:
        if self._ignore_connection_changes or self.connection_report is None:
            return
        self.connection_report = None
        self.connection_status_var.set("Needs recheck")
        self.contract_status_var.set("Connection settings changed; run preflight again.")
        self.status_label.configure(
            background=COLORS["amber_soft"], foreground=COLORS["amber"]
        )
        self._set_run_actions(False)
        self.activity_var.set("Connection settings changed. Validate COMSOL again.")

    def _build_config(self) -> ComsolConfig:
        timeout = self._positive_int(self.timeout_var.get(), "Timeout")
        cores_text = self.cores_var.get().strip()
        cores = self._positive_int(cores_text, "Core count") if cores_text else None
        mode = self.target_mode_var.get()
        config = ComsolConfig(
            executable=Path(self.executable_var.get().strip()),
            model_path=Path(self.model_var.get().strip()),
            study_tag=self.study_var.get().strip() or None if mode == "study" else None,
            job_tag=self.job_var.get().strip() or None if mode == "job" else None,
            timeout_seconds=timeout,
            cores=cores,
            plot_tags=tuple(self.selected_plot_tags),
            contract_path=(
                Path(self.contract_var.get().strip())
                if self.contract_var.get().strip()
                else None
            ),
        )
        config.validate()
        return config

    @staticmethod
    def _positive_int(value: str, label: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ValueError(f"{label} must be a positive integer") from exc
        if parsed < 1:
            raise ValueError(f"{label} must be a positive integer")
        return parsed

    def check_connection(self) -> None:
        try:
            config = self._build_config()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Connection settings", str(exc), parent=self.root)
            return
        self.connection_report = None
        self._set_run_actions(False)
        self.connection_status_var.set("Checking...")
        self.activity_var.set("Inspecting the model and validating COMSOL licenses...")
        self._run_background(
            "check",
            lambda: check_comsol(replace(config, plot_tags=())),
            lambda report: self._connection_ready(config, report),
        )

    def _connection_ready(
        self,
        config: ComsolConfig,
        report: dict[str, Any],
    ) -> None:
        self.connection_report = report
        self._ignore_connection_changes = True
        try:
            if report.get("selected_study"):
                self.study_var.set(str(report["selected_study"]))
            studies = report.get("model", {}).get("studies", [])
            self.study_entry.configure(
                values=[study.get("tag", "") for study in studies]
            )
        finally:
            self._ignore_connection_changes = False
        model = report["model"]
        self.model_summary_var.set(
            f"{model['filename']}  ·  {len(model.get('plot_groups', []))} plot group(s)"
        )
        contract_report = report.get("contract")
        contract_status = (
            str(contract_report.get("status", "warning"))
            if contract_report is not None
            else "warning"
        )
        blocked = contract_status == "blocked"
        self.connection_status_var.set(contract_status.capitalize())
        color = "red" if blocked else "amber" if contract_status == "warning" else "teal"
        self.status_label.configure(
            background=COLORS[f"{color}_soft"], foreground=COLORS[color]
        )
        if contract_report is None:
            self.contract_status_var.set(
                "Warning · no model contract selected; compatibility is not enforced."
            )
            self.activity_var.set(
                f"{model['filename']} connected without a model contract."
            )
            visible_parameters = model.get("parameters", {})
        else:
            issue_count = len(contract_report.get("issues", []))
            self.contract_status_var.set(
                f"{contract_status.capitalize()} · {contract_report.get('contract_name', '')} "
                f"v{contract_report.get('contract_version', '')} · {issue_count} finding(s)"
            )
            self.activity_var.set(
                f"Contract preflight {contract_status} for {model['filename']}. "
                "Open the report for details."
            )
            design_inputs = set(contract_report.get("design_inputs", []))
            visible_parameters = {
                name: value
                for name, value in model.get("parameters", {}).items()
                if name in design_inputs
            }
        self._populate_parameters(visible_parameters)
        selected_profile = self._selected_saved_profile()
        if selected_profile is not None:
            self._apply_profile_parameter_values(selected_profile)
        self._populate_output_symbols(report.get("output_symbols", []))
        self._populate_plot_groups(model.get("plot_groups", []))
        self._set_run_actions(not blocked)
        if config.job_tag:
            self.freshness_var.set(
                "Physical output formulas use tables reevaluated by the selected job sequence."
            )

    def _populate_plot_groups(self, plot_groups: list[dict[str, str]]) -> None:
        requested = set(self.selected_plot_tags)
        self.plot_groups_list.delete(0, tk.END)
        available_tags: list[str] = []
        for plot in plot_groups:
            tag = str(plot.get("tag", ""))
            if not tag:
                continue
            index = len(available_tags)
            available_tags.append(tag)
            label = str(plot.get("label") or tag)
            dimension = str(plot.get("dimension") or "plot")
            self.plot_groups_list.insert(tk.END, f"{tag}  ·  {dimension}  ·  {label}")
            if tag in requested:
                self.plot_groups_list.selection_set(index)
        self.selected_plot_tags = [tag for tag in available_tags if tag in requested]
        missing = sorted(requested.difference(available_tags))
        count = len(self.selected_plot_tags)
        self.plot_selection_note.configure(
            text=(
                f"{count} selected; saved tag(s) not found: {', '.join(missing)}."
                if missing
                else f"{count} plot group(s) selected for the next export step."
                if plot_groups
                else "No Plot Groups were found in this model."
            )
        )

    def _plot_selection_changed(self, _event: tk.Event | None = None) -> None:
        if self.connection_report is None:
            return
        plot_groups = self.connection_report.get("model", {}).get("plot_groups", [])
        tags = [str(plot.get("tag", "")) for plot in plot_groups if plot.get("tag")]
        self.selected_plot_tags = [
            tags[index]
            for index in self.plot_groups_list.curselection()
            if index < len(tags)
        ]
        self.plot_selection_note.configure(
            text=f"{len(self.selected_plot_tags)} plot group(s) selected for export."
        )

    def _select_all_plots(self) -> None:
        self.plot_groups_list.selection_set(0, tk.END)
        self._plot_selection_changed()

    def _clear_plot_selection(self) -> None:
        self.plot_groups_list.selection_clear(0, tk.END)
        self.selected_plot_tags = []
        self.plot_selection_note.configure(text="No Plot Groups selected.")

    def _show_empty_parameters(self) -> None:
        for child in self.parameters_frame.inner.winfo_children():
            child.destroy()
        ttk.Label(
            self.parameters_frame.inner,
            text="Connect a model to load its global parameters.",
            style="CardText.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=5, pady=12)
        self.sweep_summary_var.set("1 simulation state")

    def _populate_parameters(self, parameters: dict[str, str]) -> None:
        for child in self.parameters_frame.inner.winfo_children():
            child.destroy()
        self.parameter_variables.clear()
        self.parameter_modes.clear()
        self.parameters_frame.inner.grid_columnconfigure(2, weight=1)
        if not parameters:
            self._show_empty_parameters()
            return
        ttk.Label(
            self.parameters_frame.inner,
            text="PARAMETER",
            style="CardText.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(5, 12), pady=(0, 4))
        ttk.Label(
            self.parameters_frame.inner,
            text="MODE",
            style="CardText.TLabel",
        ).grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(0, 4))
        ttk.Label(
            self.parameters_frame.inner,
            text="VALUE OR RANGE",
            style="CardText.TLabel",
        ).grid(row=0, column=2, sticky="w", padx=(0, 6), pady=(0, 4))
        for row, (name, value) in enumerate(parameters.items(), start=1):
            variable = tk.StringVar(value=value)
            mode = tk.StringVar(value="Fixed")
            self.parameter_variables[name] = variable
            self.parameter_modes[name] = mode
            ttk.Label(
                self.parameters_frame.inner,
                text=name,
                style="Field.TLabel",
            ).grid(row=row, column=0, sticky="w", padx=(5, 12), pady=5)
            ttk.Combobox(
                self.parameters_frame.inner,
                textvariable=mode,
                values=("Fixed", "Sweep"),
                state="readonly",
                width=9,
            ).grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=5)
            ttk.Entry(
                self.parameters_frame.inner,
                textvariable=variable,
            ).grid(row=row, column=2, sticky="ew", padx=(0, 6), pady=5)
            variable.trace_add("write", self._update_sweep_preview)
            mode.trace_add("write", self._update_sweep_preview)
        self._update_sweep_preview()

    def _selected_saved_profile(self) -> WorkspaceProfile | None:
        name = self.profile_name_var.get().strip()
        if not name:
            return None
        try:
            return self.profile_store.get(name)
        except (KeyError, ValueError):
            return None

    def _apply_profile_parameter_values(self, profile: WorkspaceProfile) -> None:
        for name, variable in self.parameter_variables.items():
            if name not in profile.parameters:
                continue
            variable.set(profile.parameters[name])
            self.parameter_modes[name].set(profile.parameter_modes.get(name, "Fixed"))
        self._update_sweep_preview()

    def add_formula_row(
        self,
        name: str | None = None,
        expression: str | None = None,
    ) -> None:
        row_frame = ttk.Frame(self.formulas_frame.inner, style="Card.TFrame")
        row_frame.pack(fill="x", padx=(2, 4), pady=4)
        name_var = tk.StringVar()
        expression_var = tk.StringVar()
        name_entry = ttk.Entry(row_frame, textvariable=name_var, width=21)
        name_entry.pack(side="left", padx=(0, 7))
        expression_entry = ttk.Entry(row_frame, textvariable=expression_var)
        expression_entry.pack(side="left", fill="x", expand=True, padx=(0, 7))
        expression_entry.bind(
            "<FocusIn>",
            lambda _event, entry=expression_entry: self._set_active_formula_entry(entry),
        )
        remove = ttk.Button(
            row_frame,
            text="Remove",
            style="Secondary.TButton",
            command=lambda: self._remove_formula_row(row_frame),
        )
        remove.pack(side="right")
        if name is not None or expression is not None:
            name_var.set(name or "")
            expression_var.set(expression or "")
        elif not self.formula_rows:
            name_var.set("solve_time_ratio")
            expression_var.set(
                "comsol_duration_seconds / comsol_reported_total_seconds"
            )
        self.formula_rows.append((row_frame, name_var, expression_var))

    def _replace_formulas(self, formulas: dict[str, str]) -> None:
        for frame, _name_var, _expression_var in self.formula_rows:
            frame.destroy()
        self.formula_rows.clear()
        if formulas:
            for name, expression in formulas.items():
                self.add_formula_row(name, expression)
        else:
            self.add_formula_row("", "")

    def _remove_formula_row(self, frame: ttk.Frame) -> None:
        for row in list(self.formula_rows):
            if row[0] is frame:
                self.formula_rows.remove(row)
                frame.destroy()
                break

    def _set_active_formula_entry(self, entry: ttk.Entry) -> None:
        self.active_formula_entry = entry

    def _populate_builtin_symbols(self) -> None:
        self.symbols_tree.delete(*self.symbols_tree.get_children())
        for key, description in BUILTIN_OUTPUT_SYMBOLS:
            self.symbols_tree.insert("", "end", values=(key, description, "after run"))

    def _populate_output_symbols(self, symbols: list[dict[str, Any]]) -> None:
        self._populate_builtin_symbols()
        for symbol in symbols:
            self.symbols_tree.insert(
                "",
                "end",
                values=(
                    symbol["key"],
                    symbol.get("table_label") or symbol.get("table_tag") or "COMSOL table",
                    self._format_number(symbol.get("saved_value")),
                ),
            )

    def _insert_selected_symbol(self, _event: tk.Event) -> None:
        selection = self.symbols_tree.selection()
        if not selection:
            return
        if self.active_formula_entry is None:
            messagebox.showinfo(
                "Formula editor",
                "Click inside a formula expression, then double-click a symbol.",
                parent=self.root,
            )
            return
        symbol = str(self.symbols_tree.item(selection[0], "values")[0])
        self.active_formula_entry.insert(tk.INSERT, symbol)
        self.active_formula_entry.focus_set()

    def _collect_parameter_sets(self) -> list[dict[str, str]]:
        fixed: dict[str, str] = {}
        sweep: dict[str, list[str]] = {}
        for name, variable in self.parameter_variables.items():
            value = variable.get().strip()
            if not value:
                raise ValueError(f"Parameter '{name}' cannot be empty")
            if self.parameter_modes[name].get() == "Sweep":
                sweep[name] = parse_sweep_values(value)
            else:
                fixed[name] = value
        return build_parameter_sets(fixed, sweep)

    def _update_sweep_preview(self, *_args: object) -> None:
        if not hasattr(self, "sweep_summary_var"):
            return
        try:
            count = len(self._collect_parameter_sets())
        except ValueError as exc:
            self.sweep_summary_var.set(f"Sweep needs attention: {exc}")
            return
        estimate = estimate_sequential_seconds(
            count,
            self.store.list(status=JobStatus.SUCCEEDED, limit=20),
        )
        label = f"{count} simulation state{'s' if count != 1 else ''}"
        if estimate is not None:
            label += f"  ·  about {self._format_duration(estimate)} sequentially"
        self.sweep_summary_var.set(label)
        if hasattr(self, "run_now_button"):
            self.run_now_button.configure(text="Run sweep" if count > 1 else "Run now")
            self.queue_button.configure(text="Queue sweep" if count > 1 else "Queue only")

    def _collect_formulas(self) -> dict[str, str]:
        formulas: dict[str, str] = {}
        for _frame, name_var, expression_var in self.formula_rows:
            name = name_var.get().strip()
            expression = expression_var.get().strip()
            if not name and not expression:
                continue
            if not name or not expression:
                raise ValueError("Every computed output needs a name and expression")
            if name in formulas:
                raise ValueError(f"Computed output '{name}' is duplicated")
            formulas[name] = expression
        return validate_output_formulas(formulas)

    def _build_run_preflight(
        self,
        config: ComsolConfig,
        parameter_sets: list[dict[str, str]],
        formulas: dict[str, str],
    ) -> RunPreflightPlan:
        if config.contract_path is not None:
            validate_contract_parameters(
                load_model_contract(config.contract_path),
                parameter_sets,
            )
        context = build_comsol_run_context(
            config.model_path,
            study_tag=config.study_tag,
            job_tag=config.job_tag,
            plot_tags=config.plot_tags,
            contract_path=config.contract_path,
        )
        initial = build_preflight_plan(
            parameter_sets,
            adapter="comsol",
            output_formulas=formulas,
            run_context=context,
            existing_jobs=[],
        )
        existing = self.store.list_by_run_signatures(
            candidate.signature for candidate in initial.requested
        )
        return build_preflight_plan(
            parameter_sets,
            adapter="comsol",
            output_formulas=formulas,
            run_context=context,
            existing_jobs=existing,
        )

    def _review_run_plan(self) -> None:
        try:
            config = self._require_connected_config()
            parameter_sets = self._collect_parameter_sets()
            formulas = self._collect_formulas()
            plan = self._build_run_preflight(config, parameter_sets, formulas)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Sweep preflight", str(exc), parent=self.root)
            return
        messagebox.showinfo(
            "Sweep preflight",
            self._preflight_summary(plan),
            parent=self.root,
        )
        self.sweep_summary_var.set(
            f"{len(plan.new)} new · {plan.duplicate_count} duplicate · "
            f"{len(plan.requested)} requested"
        )

    def _preflight_summary(self, plan: RunPreflightPlan) -> str:
        estimate = estimate_sequential_seconds(
            len(plan.new),
            self.store.list(status=JobStatus.SUCCEEDED, limit=20),
        )
        lines = [
            f"Requested states: {len(plan.requested)}",
            f"New jobs: {len(plan.new)}",
            f"Reusable successful results: {len(plan.succeeded)}",
            f"Already queued or running: {len(plan.scheduled)}",
            f"Repeated inside this request: {len(plan.repeated)}",
        ]
        if estimate is not None and plan.new:
            lines.append(
                f"Estimated time for new jobs: {self._format_duration(estimate)}"
            )
        if plan.successful_job_ids:
            ids = ", ".join(f"#{job_id}" for job_id in plan.successful_job_ids)
            lines.append(f"Reusable job IDs: {ids}")
        if plan.scheduled_job_ids:
            ids = ", ".join(f"#{job_id}" for job_id in plan.scheduled_job_ids)
            lines.append(f"Scheduled job IDs: {ids}")
        return "\n".join(lines)

    def submit_run(self, *, start: bool) -> None:
        try:
            config = self._require_connected_config()
            if start and self.store.is_queue_paused():
                raise ValueError("Run queue is paused. Resume it before starting jobs")
            parameter_sets = self._collect_parameter_sets()
            formulas = self._collect_formulas()
            plan = self._build_run_preflight(config, parameter_sets, formulas)
            batch_name = self.batch_var.get().strip()
            if not batch_name:
                raise ValueError("Run label cannot be empty")
            candidates = list(plan.requested)
            skipped_duplicates = False
            if plan.has_duplicates:
                choice = messagebox.askyesnocancel(
                    "Duplicate runs detected",
                    self._preflight_summary(plan)
                    + "\n\nYes: skip duplicates and reuse successful results"
                    + "\nNo: run every requested state again"
                    + "\nCancel: return to the workspace",
                    parent=self.root,
                )
                if choice is None:
                    return
                if choice:
                    candidates = list(plan.new)
                    skipped_duplicates = True
            if not candidates:
                self.refresh_jobs()
                self.activity_var.set(
                    "No new jobs were added. Existing results and scheduled runs cover the plan."
                )
                self.notebook.select(1)
                return
            if len(candidates) >= 25:
                action = "run" if start else "queue"
                confirmed = messagebox.askyesno(
                    "Confirm parameter sweep",
                    f"This will {action} {len(candidates)} new COMSOL jobs "
                    "sequentially. Continue?",
                    parent=self.root,
                )
                if not confirmed:
                    return
            job_ids = self.store.enqueue_batch(
                batch_name,
                "comsol",
                [candidate.parameters for candidate in candidates],
                output_formulas=formulas,
                run_context=plan.run_context,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("Run setup", str(exc), parent=self.root)
            return

        self.refresh_jobs()
        if not start:
            duplicate_note = (
                f" {plan.duplicate_count} duplicate state(s) were skipped."
                if skipped_duplicates
                else ""
            )
            if len(job_ids) == 1:
                self.activity_var.set(
                    f"Job #{job_ids[0]} was added to the local queue.{duplicate_note}"
                )
            else:
                self.activity_var.set(
                    f"{len(job_ids)} sweep jobs were added to the local queue."
                    f"{duplicate_note}"
                )
            return
        if len(job_ids) == 1:
            self.activity_var.set(f"COMSOL is processing Job #{job_ids[0]}...")
        else:
            self.activity_var.set(
                f"COMSOL is processing {len(job_ids)} sweep jobs sequentially..."
            )
        runner = self._runner(config)
        self._run_background(
            "run",
            lambda: self._run_job_ids(runner, job_ids),
            lambda summary: self._submitted_jobs_finished(job_ids, summary),
        )

    @staticmethod
    def _run_job_ids(runner: SimulationRunner, job_ids: list[int]) -> dict[str, int]:
        succeeded = 0
        failed = 0
        cancelled = 0
        for job_id in job_ids:
            if runner.store.is_queue_paused():
                break
            summary = runner.run_job(job_id)
            succeeded += summary.succeeded
            failed += summary.failed
            cancelled += summary.cancelled
        return {
            "succeeded": succeeded,
            "failed": failed,
            "cancelled": cancelled,
        }

    def _submitted_jobs_finished(
        self,
        job_ids: list[int],
        summary: dict[str, int],
    ) -> None:
        if len(job_ids) == 1:
            self._run_finished(job_ids[0])
            return
        self.refresh_jobs()
        self.refresh_comparison()
        self.activity_var.set(
            f"Sweep finished: {summary['succeeded']} succeeded, "
            f"{summary['failed']} failed, {summary['cancelled']} stopped."
        )
        processed = summary["succeeded"] + summary["failed"] + summary["cancelled"]
        if processed < len(job_ids):
            remaining = len(job_ids) - processed
            self.activity_var.set(
                f"Sweep paused with {remaining} job(s) still in the queue."
            )
        self.notebook.select(2)

    def run_next(self) -> None:
        try:
            if self.store.is_queue_paused():
                raise ValueError("Run queue is paused. Resume it before running a job")
            config = self._require_connected_config()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Run queue", str(exc), parent=self.root)
            return
        self.activity_var.set("Processing the next queued job...")
        self._run_background(
            "run",
            lambda: self._runner(config).run_pending(limit=1),
            self._next_finished,
        )

    def _require_connected_config(self) -> ComsolConfig:
        if self.connection_report is None:
            raise ValueError("Check the COMSOL connection before running a job")
        contract_report = self.connection_report.get("contract")
        if contract_report and contract_report.get("status") == "blocked":
            raise ValueError(
                "The model contract preflight is blocked. Open the report and resolve its errors."
            )
        return self._build_config()

    def _runner(self, config: ComsolConfig) -> SimulationRunner:
        return SimulationRunner(
            store=self.store,
            artifact_root=self.artifact_root,
            adapters=[MockElectromagneticAdapter(), ComsolAdapter(config)],
            notifier=notifier_from_environment(),
        )

    def _run_finished(self, job_id: int) -> None:
        job = self.store.get(job_id)
        self.refresh_jobs()
        self.refresh_comparison()
        metadata = (job.result or {}).get("metadata", {})
        formula_errors = metadata.get("formula_errors", {})
        plot_errors = metadata.get("plot_export_errors", {})
        if job.status == JobStatus.SUCCEEDED and (formula_errors or plot_errors):
            issues = len(formula_errors) + len(plot_errors)
            self.activity_var.set(
                f"Job #{job_id} succeeded; {issues} optional output(s) need attention."
            )
        else:
            self.activity_var.set(f"Job #{job_id} finished with status: {job.status.value}.")
        self._show_job(job)

    def _next_finished(self, summary: Any) -> None:
        self.refresh_jobs()
        self.refresh_comparison()
        if summary.processed:
            self.activity_var.set(
                f"Queue worker finished: {summary.succeeded} succeeded, "
                f"{summary.failed} failed, {summary.cancelled} stopped."
            )
        else:
            self.activity_var.set("The run queue is empty.")

    def refresh_jobs(self, *, refresh_comparison: bool = True) -> None:
        if not hasattr(self, "jobs_tree"):
            return
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        for job in self.store.list(limit=100):
            status_label = (
                "stopping"
                if job.status == JobStatus.RUNNING and job.stop_requested_at
                else job.status.value
            )
            progress_label = ""
            if job.adapter == "comsol" and job.status == JobStatus.RUNNING:
                progress_label = inspect_job_progress(job).summary
            self.jobs_tree.insert(
                "",
                "end",
                iid=str(job.id),
                values=(
                    f"#{job.id}",
                    job.batch_name,
                    status_label,
                    progress_label,
                    job.adapter,
                    job.attempts,
                    job.created_at.replace("T", " "),
                ),
            )
        self._update_queue_controls()
        if refresh_comparison:
            self.refresh_comparison()

    def _poll_running_jobs(self) -> None:
        try:
            running = self.store.counts()[JobStatus.RUNNING.value]
            if not self.busy and (running or self._observed_running_jobs):
                self.refresh_jobs(refresh_comparison=False)
            self._observed_running_jobs = running
            self.root.after(2000, self._poll_running_jobs)
        except tk.TclError:
            return

    def _update_queue_controls(self) -> None:
        if not hasattr(self, "pause_queue_button"):
            return
        counts = self.store.counts()
        paused = self.store.is_queue_paused()
        state = "Paused" if paused else "Ready"
        queued = counts[JobStatus.QUEUED.value]
        running = counts[JobStatus.RUNNING.value]
        cancelled = counts[JobStatus.CANCELLED.value]
        self.queue_status_var.set(
            f"{state} · {queued} queued · {running} running · "
            f"{cancelled} cancelled"
        )
        self.pause_queue_button.configure(
            text="Resume queue" if paused else "Pause queue"
        )
        recover_state = "normal" if running and not self.busy else "disabled"
        self.recover_jobs_button.configure(state=recover_state)
        self._queue_selection_changed()

    def _queue_selection_changed(self, _event: tk.Event | None = None) -> None:
        if not hasattr(self, "cancel_job_button"):
            return
        selection = self.jobs_tree.selection()
        button_state = "disabled"
        button_text = "Cancel selected"
        if selection:
            try:
                job = self.store.get(int(selection[0]))
                if job.status == JobStatus.QUEUED:
                    button_state = "normal"
                elif job.status == JobStatus.RUNNING:
                    button_text = (
                        "Stop requested" if job.stop_requested_at else "Stop selected"
                    )
                    if not job.stop_requested_at:
                        button_state = "normal"
            except (KeyError, ValueError):
                pass
        self.cancel_job_button.configure(
            text=button_text,
            state=button_state,
        )

    def _toggle_queue_pause(self) -> None:
        paused = not self.store.is_queue_paused()
        self.store.set_queue_paused(paused)
        self.refresh_jobs()
        self._set_run_actions(self.connection_report is not None)
        if paused:
            self.activity_var.set(
                "Queue paused. A currently running simulation will finish normally."
            )
        else:
            self.activity_var.set("Queue resumed and ready to process waiting jobs.")

    def _cancel_selected_job(self) -> None:
        selection = self.jobs_tree.selection()
        if not selection:
            return
        job_id = int(selection[0])
        try:
            job = self.store.get(job_id)
        except KeyError as exc:
            messagebox.showerror("Queue control", str(exc), parent=self.root)
            return
        if job.status == JobStatus.RUNNING:
            self._request_job_stop(job_id, self.root)
            return
        if not messagebox.askyesno(
            "Cancel queued job",
            f"Cancel Job #{job_id}? Its history will remain available and it can be requeued later.",
            parent=self.root,
        ):
            return
        try:
            self.store.cancel(job_id)
        except ValueError as exc:
            messagebox.showerror("Cancel job", str(exc), parent=self.root)
            return
        self.refresh_jobs()
        self.activity_var.set(f"Job #{job_id} was cancelled before execution.")

    def _recover_interrupted_jobs(self) -> None:
        if self.busy:
            messagebox.showerror(
                "Recover interrupted jobs",
                "Wait for the current desktop run to finish before recovery.",
                parent=self.root,
            )
            return
        running = self.store.list(status=JobStatus.RUNNING, limit=500)
        if not running:
            self.refresh_jobs()
            return
        choice = messagebox.askyesnocancel(
            "Recover interrupted jobs",
            f"Found {len(running)} job(s) marked running. Only continue when no other worker is active.\n\n"
            "Yes: return them to the queue\nNo: mark them as failed\nCancel: leave them unchanged",
            parent=self.root,
        )
        if choice is None:
            return
        recovered = self.store.recover_interrupted(requeue=choice)
        self.refresh_jobs()
        action = "returned to the queue" if choice else "marked as failed"
        self.activity_var.set(f"{len(recovered)} interrupted job(s) {action}.")

    def _open_selected_job(self, _event: tk.Event) -> None:
        selection = self.jobs_tree.selection()
        if selection:
            self._show_job(self.store.get(int(selection[0])))

    def _show_job(self, job: Job) -> None:
        status_label = (
            "stopping"
            if job.stop_requested_at and job.status == JobStatus.RUNNING
            else job.status.value
        )
        window = tk.Toplevel(self.root)
        window.title(f"Job #{job.id} details")
        window.geometry("980x720")
        window.minsize(820, 620)
        window.configure(background=COLORS["canvas"])
        container = ttk.Frame(window, style="Card.TFrame", padding=22)
        container.pack(fill="both", expand=True, padx=18, pady=18)
        ttk.Label(
            container,
            text=f"Job #{job.id} · {job.batch_name}",
            style="CardTitle.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            container,
            text=f"{status_label} · {job.adapter} · {job.attempts} attempt(s)",
            style="CardText.TLabel",
        ).pack(anchor="w", pady=(4, 14))

        notebook = ttk.Notebook(container)
        notebook.pack(fill="both", expand=True)
        live_tab = None
        if job.adapter == "comsol" and (
            job.status == JobStatus.RUNNING or job.artifact_dir
        ):
            live_tab = self._add_live_monitor(notebook, job.id, window)
        metadata = (job.result or {}).get("metadata", {})
        identity_model = job.run_context.get("model", {})
        if not isinstance(identity_model, dict):
            identity_model = {}
        identity_target = job.run_context.get("target", {})
        if not isinstance(identity_target, dict):
            identity_target = {}
        identity_plots = job.run_context.get("plot_tags", [])
        if not isinstance(identity_plots, list):
            identity_plots = []
        identity_values = {
            "signature": job.run_signature or "Not recorded",
            "model": identity_model.get("name", "Not recorded"),
            "model_size_bytes": identity_model.get("size_bytes", ""),
            "target": (
                f"{identity_target.get('kind', '')}: {identity_target.get('tag', '')}"
                if identity_target
                else "Not recorded"
            ),
            "plot_groups": ", ".join(str(tag) for tag in identity_plots),
        }
        plot_exports = [
            item
            for item in metadata.get("plot_exports", [])
            if isinstance(item, dict)
        ]
        plot_values = {"status": metadata.get("plot_export_status", "not_requested")}
        plot_values.update(
            {
                str(item.get("tag", "plot")): item.get("filename", "")
                for item in plot_exports
            }
        )
        if plot_exports:
            self._add_plot_viewer(notebook, job, plot_exports)
        for title, values in (
            (
                "Run status",
                {
                    "status": job.status.value,
                    "error": job.error or "",
                    "created_at": job.created_at,
                    "started_at": job.started_at or "",
                    "finished_at": job.finished_at or "",
                    "stop_requested_at": job.stop_requested_at or "",
                },
            ),
            ("Run identity", identity_values),
            ("Inputs", job.parameters),
            ("Formulas", job.output_formulas),
            ("Metrics", (job.result or {}).get("metrics", {})),
            ("Plot exports", plot_values),
            ("Plot errors", metadata.get("plot_export_errors", {})),
            (
                "Formula errors",
                metadata.get("formula_errors", {}),
            ),
        ):
            frame = ttk.Frame(notebook, style="Card.TFrame", padding=12)
            notebook.add(frame, text=title)
            tree = ttk.Treeview(frame, columns=("name", "value"), show="headings")
            tree.heading("name", text="NAME")
            tree.heading("value", text="VALUE")
            tree.column("name", width=250)
            tree.column("value", width=400, stretch=True)
            tree.pack(fill="both", expand=True)
            for name, value in values.items():
                tree.insert("", "end", values=(name, self._format_number(value)))
        if live_tab is not None and job.status == JobStatus.RUNNING:
            notebook.select(live_tab)

        footer = ttk.Frame(container, style="Card.TFrame")
        footer.pack(fill="x", pady=(12, 0))
        if job.artifact_dir:
            ttk.Button(
                footer,
                text="Open artifacts",
                style="Secondary.TButton",
                command=lambda path=job.artifact_dir: self._open_artifacts(path),
            ).pack(side="left")
        if job.status in {JobStatus.FAILED, JobStatus.CANCELLED}:
            ttk.Button(
                footer,
                text="Retry" if job.status == JobStatus.FAILED else "Requeue",
                style="Secondary.TButton",
                command=lambda: self._retry_job(job.id, window),
            ).pack(side="left", padx=(8, 0))
        ttk.Button(
            footer,
            text="Close",
            style="Primary.TButton",
            command=window.destroy,
        ).pack(side="right")

    def _add_live_monitor(
        self,
        notebook: ttk.Notebook,
        job_id: int,
        window: tk.Toplevel,
    ) -> ttk.Frame:
        frame = ttk.Frame(notebook, style="Card.TFrame", padding=16)
        notebook.add(frame, text="Live monitor")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(3, weight=1)

        summary_var = tk.StringVar(value="Reading solver activity...")
        detail_var = tk.StringVar(value="")
        warning_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=summary_var, style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(frame, textvariable=detail_var, style="CardText.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )
        ttk.Label(frame, textvariable=warning_var, style="CardText.TLabel").grid(
            row=2, column=0, sticky="w", pady=(4, 10)
        )
        log_text = tk.Text(
            frame,
            wrap="none",
            background="#101820",
            foreground="#d9e4eb",
            insertbackground="white",
            font=("Cascadia Mono", 9),
            padx=12,
            pady=10,
            relief="flat",
            state="disabled",
        )
        log_text.grid(row=3, column=0, sticky="nsew")
        controls = ttk.Frame(frame, style="Card.TFrame")
        controls.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        open_button = ttk.Button(
            controls,
            text="Open live log",
            style="Secondary.TButton",
            state="disabled",
        )
        open_button.pack(side="left")
        stop_button = ttk.Button(
            controls,
            text="Stop job",
            style="Secondary.TButton",
            command=lambda: self._request_job_stop(job_id, window),
        )
        stop_button.pack(side="left", padx=(8, 0))

        def refresh_monitor() -> None:
            try:
                if not window.winfo_exists():
                    return
                current_job = self.store.get(job_id)
                progress = inspect_job_progress(current_job)
                summary_var.set(progress.summary)
                activity = (
                    f"{format_duration(progress.idle_seconds)} ago"
                    if progress.idle_seconds is not None
                    else "Not available"
                )
                detail_var.set(
                    f"Elapsed: {format_duration(progress.elapsed_seconds)} · "
                    f"Last activity: {activity} · {progress.message}"
                )
                warning_var.set(
                    "No recent log activity. Check the solver window, license, or model."
                    if progress.stale
                    else ""
                )
                log_text.configure(state="normal")
                log_text.delete("1.0", "end")
                log_text.insert("1.0", "\n".join(progress.log_tail))
                log_text.see("end")
                log_text.configure(state="disabled")
                open_button.configure(
                    state="normal" if progress.log_exists else "disabled",
                    command=(
                        lambda path=progress.log_path: self._open_live_log(path, window)
                    ),
                )
                can_stop = (
                    current_job.status == JobStatus.RUNNING
                    and not current_job.stop_requested_at
                )
                stop_button.configure(
                    state="normal" if can_stop else "disabled",
                    text=(
                        "Stop requested"
                        if current_job.stop_requested_at
                        else "Stop job"
                    ),
                )
                if current_job.status == JobStatus.RUNNING:
                    window.after(1000, refresh_monitor)
            except (KeyError, OSError, tk.TclError):
                return

        refresh_monitor()
        return frame

    def _open_live_log(self, path: str | None, parent: tk.Misc) -> None:
        if not path or not Path(path).is_file():
            messagebox.showerror(
                "Live monitor",
                "The COMSOL log is not available yet.",
                parent=parent,
            )
            return
        try:
            os.startfile(Path(path))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Live monitor", str(exc), parent=parent)

    def _request_job_stop(self, job_id: int, parent: tk.Misc) -> bool:
        if not messagebox.askyesno(
            "Stop running job",
            f"Stop Job #{job_id}? The active solver process will be "
            "terminated and the job history will remain available.",
            parent=parent,
        ):
            return False
        try:
            self.store.request_stop(job_id)
        except ValueError as exc:
            messagebox.showerror("Stop job", str(exc), parent=parent)
            return False
        self.refresh_jobs(refresh_comparison=False)
        self.activity_var.set(
            f"Stop requested for Job #{job_id}. Waiting for the solver to exit."
        )
        return True

    def _add_plot_viewer(
        self,
        notebook: ttk.Notebook,
        job: Job,
        plots: list[dict[str, Any]],
    ) -> None:
        frame = ttk.Frame(notebook, style="Card.TFrame", padding=12)
        notebook.add(frame, text=f"Results ({len(plots)})")
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        browser = tk.Frame(
            frame,
            background=COLORS["soft"],
            highlightbackground=COLORS["line"],
            highlightthickness=1,
            padx=10,
            pady=10,
        )
        browser.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        ttk.Label(browser, text="PLOT GROUPS", style="Field.TLabel").pack(anchor="w")
        plot_list = tk.Listbox(
            browser,
            width=31,
            height=18,
            background=COLORS["surface"],
            foreground=COLORS["ink"],
            selectbackground=COLORS["blue"],
            selectforeground="#ffffff",
            highlightbackground=COLORS["line"],
            highlightthickness=1,
            borderwidth=0,
            activestyle="none",
            font=("Segoe UI", 9),
        )
        plot_list.pack(fill="y", expand=True, pady=(8, 0))
        for plot in plots:
            tag = str(plot.get("tag") or "plot")
            label = str(plot.get("label") or tag)
            dimension = str(plot.get("dimension") or "plot")
            plot_list.insert(tk.END, f"{tag}  ·  {dimension}  ·  {label}")

        preview_panel = ttk.Frame(frame, style="Card.TFrame")
        preview_panel.grid(row=0, column=1, sticky="nsew")
        preview_panel.grid_columnconfigure(0, weight=1)
        preview_panel.grid_rowconfigure(0, weight=1)
        image_label = tk.Label(
            preview_panel,
            text="Select a plot to preview its PNG artifact.",
            background=COLORS["soft"],
            foreground=COLORS["muted"],
            highlightbackground=COLORS["line"],
            highlightthickness=1,
            anchor="center",
            font=("Segoe UI", 10),
        )
        image_label.grid(row=0, column=0, sticky="nsew")

        info_var = tk.StringVar(value="")
        ttk.Label(
            preview_panel,
            textvariable=info_var,
            style="CardText.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(9, 0))

        controls = ttk.Frame(preview_panel, style="Card.TFrame")
        controls.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        state: dict[str, Any] = {
            "path": None,
            "plot": None,
            "source": None,
            "preview": None,
        }

        def show_plot(index: int) -> None:
            plot_list.selection_clear(0, tk.END)
            plot_list.selection_set(index)
            plot_list.activate(index)
            plot_list.see(index)
            plot = plots[index]
            try:
                path = resolve_plot_artifact(job.artifact_dir, plot)
                source = tk.PhotoImage(file=str(path))
            except (ValueError, tk.TclError) as exc:
                state.update(path=None, plot=None, source=None, preview=None)
                image_label.configure(
                    image="",
                    text=f"Preview unavailable\n\n{exc}",
                    foreground=COLORS["red"],
                )
                image_label.image = None  # type: ignore[attr-defined]
                info_var.set(f"{index + 1} of {len(plots)}")
                open_button.configure(state="disabled")
                compare_button.configure(state="disabled")
                return

            factor = preview_subsample_factor(source.width(), source.height())
            preview = source if factor == 1 else source.subsample(factor, factor)
            state.update(path=path, plot=plot, source=source, preview=preview)
            image_label.configure(image=preview, text="", foreground=COLORS["muted"])
            image_label.image = preview  # type: ignore[attr-defined]
            label = str(plot.get("label") or plot.get("tag") or "Plot")
            dimension = str(plot.get("dimension") or "plot")
            info_var.set(
                f"{index + 1} of {len(plots)}  ·  {label}  ·  {dimension}  ·  "
                f"{source.width()} × {source.height()}  ·  "
                f"{format_file_size(path.stat().st_size)}"
            )
            open_button.configure(state="normal")
            compare_button.configure(state="normal")

        def selected_index() -> int:
            selection = plot_list.curselection()
            return int(selection[0]) if selection else 0

        def move_plot(offset: int) -> None:
            target = max(0, min(len(plots) - 1, selected_index() + offset))
            show_plot(target)

        ttk.Button(
            controls,
            text="Previous",
            style="Secondary.TButton",
            command=lambda: move_plot(-1),
        ).pack(side="left")
        ttk.Button(
            controls,
            text="Next",
            style="Secondary.TButton",
            command=lambda: move_plot(1),
        ).pack(side="left", padx=(8, 0))
        open_button = ttk.Button(
            controls,
            text="Open PNG",
            style="Primary.TButton",
            state="disabled",
            command=lambda: self._open_plot_artifact(state.get("path")),
        )
        open_button.pack(side="right")
        compare_button = ttk.Button(
            controls,
            text="Compare runs",
            style="Secondary.TButton",
            state="disabled",
            command=lambda: self._show_plot_comparison(job, state.get("plot")),
        )
        compare_button.pack(side="right", padx=(0, 8))
        plot_list.bind(
            "<<ListboxSelect>>",
            lambda _event: show_plot(selected_index()),
        )
        show_plot(0)

    def _show_plot_comparison(
        self,
        current_job: Job,
        plot: dict[str, Any] | None,
    ) -> None:
        if not plot or not plot.get("tag"):
            messagebox.showinfo(
                "Compare runs",
                "Select an available Plot Group first.",
                parent=self.root,
            )
            return
        tag = str(plot["tag"])
        successful_jobs = self.store.list(status=JobStatus.SUCCEEDED, limit=500)
        comparisons = matching_plot_artifacts(
            successful_jobs,
            batch_name=current_job.batch_name,
            plot_tag=tag,
            limit=12,
            include_job_id=current_job.id,
        )
        if len(comparisons) < 2:
            messagebox.showinfo(
                "Compare runs",
                "At least two successful jobs in this batch need the same Plot Group.",
                parent=self.root,
            )
            return

        label = str(plot.get("label") or tag)
        window = tk.Toplevel(self.root)
        window.title(f"Compare {tag} across runs")
        window.geometry("1220x650")
        window.minsize(860, 560)
        window.configure(background=COLORS["canvas"])

        container = ttk.Frame(window, style="Card.TFrame", padding=20)
        container.pack(fill="both", expand=True, padx=18, pady=18)
        ttk.Label(
            container,
            text=f"{label} · {tag}",
            style="CardTitle.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            container,
            text=(
                f"{len(comparisons)} successful states from "
                f"'{current_job.batch_name}' · ordered by job number"
            ),
            style="CardText.TLabel",
        ).pack(anchor="w", pady=(4, 14))

        gallery = ttk.Frame(container, style="Card.TFrame")
        gallery.pack(fill="both", expand=True)
        canvas = tk.Canvas(
            gallery,
            background=COLORS["surface"],
            highlightthickness=0,
            height=470,
        )
        scrollbar = ttk.Scrollbar(gallery, orient="horizontal", command=canvas.xview)
        cards = tk.Frame(canvas, background=COLORS["surface"])
        canvas_window = canvas.create_window((0, 0), window=cards, anchor="nw")
        canvas.configure(xscrollcommand=scrollbar.set)
        canvas.pack(fill="both", expand=True)
        scrollbar.pack(fill="x", pady=(8, 0))
        cards.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(canvas_window, height=event.height),
        )

        image_references: list[tk.PhotoImage] = []
        for column, comparison in enumerate(comparisons):
            card = tk.Frame(
                cards,
                width=370,
                height=450,
                background=COLORS["soft"],
                highlightbackground=(
                    COLORS["blue"]
                    if comparison.job.id == current_job.id
                    else COLORS["line"]
                ),
                highlightthickness=(
                    2 if comparison.job.id == current_job.id else 1
                ),
                padx=12,
                pady=12,
            )
            card.grid(row=0, column=column, sticky="ns", padx=(0, 12))
            card.pack_propagate(False)

            heading = tk.Frame(card, background=COLORS["soft"])
            heading.pack(fill="x")
            tk.Label(
                heading,
                text=f"Job #{comparison.job.id}",
                background=COLORS["soft"],
                foreground=COLORS["ink"],
                font=("Segoe UI Semibold", 11),
            ).pack(side="left")
            if comparison.job.id == current_job.id:
                tk.Label(
                    heading,
                    text="CURRENT",
                    background=COLORS["blue_soft"],
                    foreground=COLORS["blue"],
                    font=("Segoe UI Semibold", 8),
                    padx=7,
                    pady=2,
                ).pack(side="right")

            try:
                source = tk.PhotoImage(file=str(comparison.path))
            except tk.TclError as exc:
                tk.Label(
                    card,
                    text=f"Preview unavailable\n\n{exc}",
                    background=COLORS["surface"],
                    foreground=COLORS["red"],
                    highlightbackground=COLORS["line"],
                    highlightthickness=1,
                    wraplength=320,
                ).pack(fill="both", expand=True, pady=(10, 9))
            else:
                factor = preview_subsample_factor(
                    source.width(),
                    source.height(),
                    max_width=338,
                    max_height=285,
                )
                preview = (
                    source if factor == 1 else source.subsample(factor, factor)
                )
                image_references.extend([source, preview])
                tk.Label(
                    card,
                    image=preview,
                    background=COLORS["surface"],
                    highlightbackground=COLORS["line"],
                    highlightthickness=1,
                ).pack(fill="both", expand=True, pady=(10, 9))

            tk.Label(
                card,
                text=parameter_summary(comparison.job.parameters),
                background=COLORS["soft"],
                foreground=COLORS["ink"],
                font=("Segoe UI", 9),
                justify="left",
                anchor="w",
                wraplength=338,
            ).pack(fill="x")
            footer = tk.Frame(card, background=COLORS["soft"])
            footer.pack(fill="x", pady=(8, 0))
            tk.Label(
                footer,
                text=format_file_size(comparison.path.stat().st_size),
                background=COLORS["soft"],
                foreground=COLORS["muted"],
                font=("Segoe UI", 8),
            ).pack(side="left")
            ttk.Button(
                footer,
                text="Open PNG",
                style="Secondary.TButton",
                command=lambda path=comparison.path: self._open_plot_artifact(path),
            ).pack(side="right")

        window.plot_images = image_references  # type: ignore[attr-defined]
        actions = ttk.Frame(container, style="Card.TFrame")
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(
            actions,
            text="Export report",
            style="Secondary.TButton",
            command=lambda: self._export_plot_comparison_report(
                window,
                current_job,
                plot,
                comparisons,
            ),
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Close",
            style="Primary.TButton",
            command=window.destroy,
        ).pack(side="right")

    def _export_plot_comparison_report(
        self,
        parent: tk.Toplevel,
        current_job: Job,
        plot: dict[str, Any],
        comparisons: list[PlotComparisonArtifact],
    ) -> None:
        tag = str(plot.get("tag") or "plot")
        label = str(plot.get("label") or tag)
        batch_slug = re.sub(
            r"[^a-z0-9]+",
            "-",
            current_job.batch_name.lower(),
        ).strip("-")[:48]
        tag_slug = re.sub(r"[^a-z0-9]+", "-", tag.lower()).strip("-")[:32]
        artifact_dir = Path(current_job.artifact_dir or "")
        initial_dir = artifact_dir if artifact_dir.is_dir() else Path.cwd()
        destination = filedialog.asksaveasfilename(
            parent=parent,
            title="Export plot comparison report",
            initialdir=str(initial_dir.resolve()),
            initialfile=f"{batch_slug or 'batch'}-{tag_slug or 'plot'}-comparison.html",
            defaultextension=".html",
            filetypes=[("HTML report", "*.html")],
        )
        if not destination:
            return
        try:
            written = write_plot_comparison_report(
                destination,
                comparisons,
                title=label,
                batch_name=current_job.batch_name,
                current_job_id=current_job.id,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("Export report", str(exc), parent=parent)
            return
        should_open = messagebox.askyesno(
            "Report exported",
            f"The self-contained report was saved to:\n{written}\n\nOpen it now?",
            parent=parent,
        )
        if should_open:
            try:
                os.startfile(written)  # type: ignore[attr-defined]
            except OSError as exc:
                messagebox.showerror("Export report", str(exc), parent=parent)

    def _open_plot_artifact(self, path: Path | None) -> None:
        if path is None or not path.is_file():
            messagebox.showerror(
                "Plot artifact",
                "The selected PNG artifact is no longer available.",
                parent=self.root,
            )
            return
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Plot artifact", str(exc), parent=self.root)

    def _open_artifacts(self, path: str) -> None:
        resolved = Path(path).resolve()
        if not resolved.exists():
            messagebox.showerror(
                "Artifacts",
                f"Artifact directory was not found: {resolved}",
                parent=self.root,
            )
            return
        os.startfile(resolved)  # type: ignore[attr-defined]

    def _retry_job(self, job_id: int, window: tk.Toplevel) -> None:
        try:
            self.store.retry(job_id)
        except ValueError as exc:
            messagebox.showerror("Retry", str(exc), parent=window)
            return
        window.destroy()
        self.refresh_jobs()
        self.activity_var.set(f"Job #{job_id} was returned to the queue.")

    def _add_ranking_constraint(self) -> None:
        if not hasattr(self, "ranking_constraints_frame"):
            return
        if len(self.ranking_constraint_rows) >= 8:
            messagebox.showinfo(
                "Rank results",
                "A ranking can contain at most eight constraints.",
                parent=self.root,
            )
            return
        frame = ttk.Frame(self.ranking_constraints_frame, style="Card.TFrame")
        frame.grid(
            row=len(self.ranking_constraint_rows),
            column=0,
            sticky="ew",
            pady=(0, 7),
        )
        frame.grid_columnconfigure(0, weight=1)
        field_var = tk.StringVar()
        operator_var = tk.StringVar(value="<=")
        threshold_var = tk.StringVar()
        field = ttk.Combobox(
            frame,
            textvariable=field_var,
            values=list(self.ranking_field_lookup),
            state="readonly",
            width=34,
        )
        field.grid(row=0, column=0, sticky="ew")
        ttk.Combobox(
            frame,
            textvariable=operator_var,
            values=("<=", ">=", "<", ">"),
            state="readonly",
            width=5,
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Entry(
            frame,
            textvariable=threshold_var,
            width=18,
        ).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(
            frame,
            text="Remove",
            style="Secondary.TButton",
            command=lambda: self._remove_ranking_constraint(frame),
        ).grid(row=0, column=3, padx=(8, 0))
        self.ranking_constraint_rows.append(
            (frame, field_var, operator_var, threshold_var, field)
        )
        self._regrid_ranking_constraints()

    def _remove_ranking_constraint(self, frame: ttk.Frame) -> None:
        for row in list(self.ranking_constraint_rows):
            if row[0] is frame:
                self.ranking_constraint_rows.remove(row)
                frame.destroy()
                break
        if not self.ranking_constraint_rows:
            self._add_ranking_constraint()
        else:
            self._regrid_ranking_constraints()

    def _regrid_ranking_constraints(self) -> None:
        for index, row in enumerate(self.ranking_constraint_rows):
            row[0].grid_configure(row=index)

    def _clear_ranking_constraints(self) -> None:
        for frame, _field, _operator, _threshold, _widget in self.ranking_constraint_rows:
            frame.destroy()
        self.ranking_constraint_rows.clear()
        self._add_ranking_constraint()
        self._calculate_ranking(show_errors=False)

    def _refresh_ranking_options(self) -> None:
        if not hasattr(self, "ranking_batch"):
            return
        successful_jobs = self.store.list(status=JobStatus.SUCCEEDED, limit=500)
        batches = list(dict.fromkeys(job.batch_name for job in successful_jobs))
        self.ranking_batch.configure(values=batches)
        if not batches:
            self.ranking_batch_var.set("")
            self.ranking_objective_var.set("")
            self.ranking_objective.configure(values=[])
            self.ranking_field_lookup = {}
            self.ranking_field_dimensions = {}
            self.current_ranking_result = None
            self.ranking_tree.delete(*self.ranking_tree.get_children())
            self.ranking_summary_var.set("No successful runs are available to rank.")
            return
        if self.ranking_batch_var.get() not in batches:
            self.ranking_batch_var.set(batches[0])
        batch_name = self.ranking_batch_var.get()
        batch_jobs = [job for job in successful_jobs if job.batch_name == batch_name]

        objective_names = sorted(
            {
                str(name)
                for job in batch_jobs
                for name, value in (job.result or {}).get("metrics", {}).items()
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and parse_quantity(value) is not None
                )
            }
        )
        candidate_input_names = sorted(
            {str(name) for job in batch_jobs for name in job.parameters}
        )
        self.ranking_objective.configure(values=objective_names)
        if self.ranking_objective_var.get() not in objective_names:
            formula_names = {
                name
                for job in batch_jobs
                for name in job.output_formulas
                if name in objective_names
            }
            selected = (
                sorted(formula_names)[0]
                if formula_names
                else (objective_names[0] if objective_names else "")
            )
            self.ranking_objective_var.set(selected)

        field_lookup: dict[str, tuple[str, str]] = {}
        field_dimensions: dict[str, str | None] = {}
        for name in candidate_input_names:
            values = [job.parameters[name] for job in batch_jobs if name in job.parameters]
            try:
                dimension = common_quantity_dimension(values)
            except ValueError:
                continue
            unit = reference_unit(dimension)
            suffix = f" [{unit}]" if unit else ""
            label = f"Input · {name}{suffix}"
            field_lookup[label] = ("input", name)
            field_dimensions[label] = dimension
        for name in objective_names:
            label = f"Output · {name}"
            field_lookup[label] = ("output", name)
            field_dimensions[label] = None
        self.ranking_field_lookup = field_lookup
        self.ranking_field_dimensions = field_dimensions
        options = list(field_lookup)
        for _frame, field_var, _operator, _threshold, widget in self.ranking_constraint_rows:
            widget.configure(values=options)
            if field_var.get() not in field_lookup:
                field_var.set("")
        self._calculate_ranking(show_errors=False)

    def _ranking_batch_changed(self, _event: tk.Event | None = None) -> None:
        self._refresh_ranking_options()

    def _collect_ranking_constraints(self) -> list[RankingConstraint]:
        constraints: list[RankingConstraint] = []
        keys: set[tuple[str, str]] = set()
        for (
            _frame,
            field_var,
            operator_var,
            threshold_var,
            _widget,
        ) in self.ranking_constraint_rows:
            label = field_var.get()
            threshold_text = threshold_var.get().strip()
            if not label and not threshold_text:
                continue
            if label not in self.ranking_field_lookup:
                raise ValueError("Choose a field for every constraint")
            if not threshold_text:
                raise ValueError(f"Enter a threshold for {label}")
            source, field = self.ranking_field_lookup[label]
            constraint = RankingConstraint.from_value(
                source,
                field,
                operator_var.get(),
                threshold_text,
            )
            expected_dimension = self.ranking_field_dimensions[label]
            if constraint.dimension != expected_dimension:
                unit = reference_unit(expected_dimension)
                if unit:
                    raise ValueError(
                        f"Constraint threshold for {label} must include a compatible "
                        f"unit such as [{unit}]"
                    )
                raise ValueError(
                    f"Constraint threshold for {label} must not include a physical unit"
                )
            key = (source, field)
            if key in keys:
                raise ValueError(f"Constraint field is duplicated: {label}")
            keys.add(key)
            constraints.append(constraint)
        return constraints

    def _calculate_ranking(self, *, show_errors: bool) -> None:
        if not hasattr(self, "ranking_tree"):
            return
        batch_name = self.ranking_batch_var.get()
        objective = self.ranking_objective_var.get()
        if not batch_name or not objective:
            self.current_ranking_result = None
            self.ranking_tree.delete(*self.ranking_tree.get_children())
            self.ranking_summary_var.set(
                "Choose a completed batch and numeric output objective."
            )
            return
        try:
            constraints = self._collect_ranking_constraints()
            result = rank_sweep_results(
                self.store.list(status=JobStatus.SUCCEEDED, limit=500),
                objective,
                direction=self.ranking_direction_var.get().casefold(),
                constraints=constraints,
                batch_name=batch_name,
            )
        except ValueError as exc:
            self.current_ranking_result = None
            if show_errors:
                messagebox.showerror("Rank results", str(exc), parent=self.root)
            else:
                self.ranking_summary_var.set(str(exc))
            return

        self.current_ranking_result = result
        self.ranking_tree.delete(*self.ranking_tree.get_children())
        if result.rows:
            best = result.rows[0]
            self.ranking_summary_var.set(
                f"Best {objective}: {self._format_number(best.objective_value)} at "
                f"Job #{best.job_id} · {result.qualifying_jobs} qualified · "
                f"{result.rejected_jobs} rejected · {result.missing_values} missing"
            )
        else:
            self.ranking_summary_var.set(
                f"No run satisfies every constraint · {result.rejected_jobs} rejected · "
                f"{result.missing_values} missing"
            )
        constraint_labels = {constraint.key: constraint for constraint in constraints}
        for row in result.rows[:100]:
            parameter_text = ", ".join(
                f"{name}={value}"
                for name, value in list(row.parameters.items())[:8]
            )
            constraint_text = ", ".join(
                self._format_constraint_value(
                    constraint_labels.get(name),
                    name,
                    value,
                )
                for name, value in row.constraint_values.items()
            ) or "No constraints"
            item = self.ranking_tree.insert(
                "",
                "end",
                iid=str(row.job_id),
                values=(
                    row.rank,
                    f"#{row.job_id}",
                    self._format_number(row.objective_value),
                    constraint_text,
                    parameter_text,
                    row.finished_at.replace("T", " "),
                ),
            )
            if row.rank == 1:
                self.ranking_tree.item(item, tags=("best",))
        self.ranking_tree.tag_configure("best", background=COLORS["teal_soft"])

    def _format_constraint_value(
        self,
        constraint: RankingConstraint | None,
        fallback: str,
        value: float,
    ) -> str:
        if constraint is None:
            return f"{fallback}={self._format_number(value)}"
        unit = reference_unit(constraint.dimension)
        suffix = f" {unit}" if unit else ""
        return f"{constraint.field}={self._format_number(value)}{suffix}"

    def _open_ranked_job(self, _event: tk.Event) -> None:
        selection = self.ranking_tree.selection()
        if selection:
            self._show_job(self.store.get(int(selection[0])))

    def _export_ranking(self) -> None:
        self._calculate_ranking(show_errors=True)
        if self.current_ranking_result is None or not self.current_ranking_result.rows:
            messagebox.showinfo(
                "Export ranking",
                "There are no ranked results to export.",
                parent=self.root,
            )
            return
        safe_name = re.sub(
            r"[^A-Za-z0-9_.-]+",
            "-",
            f"{self.ranking_batch_var.get()}-{self.ranking_objective_var.get()}-ranking",
        ).strip("-")
        selected = filedialog.asksaveasfilename(
            title="Export ranking CSV",
            defaultextension=".csv",
            initialfile=f"{safe_name or 'ranking'}.csv",
            filetypes=[("CSV file", "*.csv"), ("All files", "*")],
        )
        if not selected:
            return
        try:
            output = write_ranking_csv(selected, self.current_ranking_result)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Export ranking", str(exc), parent=self.root)
            return
        self.activity_var.set(f"Result ranking exported to {output.name}.")

    def refresh_comparison(self) -> None:
        if not hasattr(self, "compare_metric"):
            return
        successful_jobs = self.store.list(status=JobStatus.SUCCEEDED, limit=500)
        batches = sorted({job.batch_name for job in successful_jobs})
        self.compare_batch.configure(values=["All batches", *batches])
        if self.compare_batch_var.get() not in {"All batches", *batches}:
            self.compare_batch_var.set("All batches")
        selected_batch = self._selected_comparison_batch()
        filtered_jobs = [
            job
            for job in successful_jobs
            if selected_batch is None or job.batch_name == selected_batch
        ]
        metric_names: set[str] = set()
        parameter_names: set[str] = set()
        for job in filtered_jobs:
            metrics = (job.result or {}).get("metrics", {})
            metric_names.update(str(name) for name in metrics)
            parameter_names.update(str(name) for name in job.parameters)
        values = sorted(metric_names)
        self.compare_metric.configure(values=values)
        x_values = ["Job ID", *sorted(parameter_names)]
        self.compare_x.configure(values=x_values)
        if self.compare_x_var.get() not in x_values:
            self.compare_x_var.set(x_values[1] if len(x_values) > 1 else "Job ID")
        if self.compare_metric_var.get() not in values:
            formula_names = {
                name
                for job in filtered_jobs
                for name in job.output_formulas
                if name in values
            }
            selected = sorted(formula_names)[0] if formula_names else (values[0] if values else "")
            self.compare_metric_var.set(selected)
        self._refresh_comparison_rows()
        self._refresh_ranking_options()

    def _selected_comparison_batch(self) -> str | None:
        selected = self.compare_batch_var.get()
        return None if selected == "All batches" else selected

    def _comparison_filter_changed(self, _event: tk.Event | None = None) -> None:
        self.refresh_comparison()

    def _refresh_comparison_rows(self, _event: tk.Event | None = None) -> None:
        if not hasattr(self, "compare_tree"):
            return
        self.compare_tree.delete(*self.compare_tree.get_children())
        metric = self.compare_metric_var.get()
        if not metric:
            self.current_comparison_rows = []
            self.compare_best_var.set("Choose an output metric to compare runs.")
            self._draw_comparison_chart()
            return
        jobs = self.store.list(status=JobStatus.SUCCEEDED, limit=500)
        rows = comparison_rows(
            jobs,
            metric,
            batch_name=self._selected_comparison_batch(),
        )
        self.current_comparison_rows = rows
        best_row = max(rows, key=lambda row: row["value"]) if rows else None
        if best_row:
            self.compare_best_var.set(
                f"Best (highest) {metric}: {self._format_number(best_row['value'])} "
                f"at Job #{best_row['job_id']} · {best_row['batch_name']}"
            )
        else:
            self.compare_best_var.set("No successful runs contain the selected output.")
        for row in rows:
            parameters = ", ".join(
                f"{name}={value}"
                for name, value in list(dict(row["parameters"]).items())[:8]
            )
            item = self.compare_tree.insert(
                "",
                "end",
                values=(
                    f"#{row['job_id']}",
                    row["batch_name"],
                    parameters,
                    self._format_number(row["value"]),
                    str(row["finished_at"]).replace("T", " "),
                ),
            )
            if best_row and row["job_id"] == best_row["job_id"]:
                self.compare_tree.item(item, tags=("best",))
        self.compare_tree.tag_configure("best", background=COLORS["teal_soft"])
        self._draw_comparison_chart()

    def _draw_comparison_chart(self) -> None:
        if not hasattr(self, "compare_chart"):
            return
        canvas = self.compare_chart
        canvas.delete("all")
        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 220)
        rows = self.current_comparison_rows
        if not rows:
            canvas.create_text(
                width / 2,
                height / 2,
                text="Successful runs will appear here as a comparison chart.",
                fill=COLORS["muted"],
                font=("Segoe UI", 10),
            )
            return

        x_name = self.compare_x_var.get()
        points: list[tuple[float, float, int]] = []
        x_dimensions: set[str | None] = set()
        for row in rows:
            if x_name == "Job ID":
                x_value = float(row["job_id"])
            else:
                quantity = parse_quantity(dict(row["parameters"]).get(x_name))
                x_value = quantity.si_value if quantity else None
                if quantity:
                    x_dimensions.add(quantity.dimension)
            if x_value is not None:
                points.append((x_value, float(row["value"]), int(row["job_id"])))
        if not points:
            canvas.create_text(
                width / 2,
                height / 2,
                text=f"'{x_name}' does not contain numeric values for this chart.",
                fill=COLORS["muted"],
                font=("Segoe UI", 10),
            )
            return
        if len(x_dimensions) > 1:
            canvas.create_text(
                width / 2,
                height / 2,
                text=f"'{x_name}' contains incompatible physical dimensions.",
                fill=COLORS["red"],
                font=("Segoe UI", 10),
            )
            return
        points.sort(key=lambda point: (point[0], point[2]))
        left, right, top, bottom = 62, width - 24, 22, height - 42
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
        x_min, x_max = min(x_values), max(x_values)
        y_min, y_max = min(y_values), max(y_values)
        if x_min == x_max:
            x_min -= 0.5
            x_max += 0.5
        if y_min == y_max:
            margin = max(abs(y_min) * 0.05, 0.5)
            y_min -= margin
            y_max += margin

        def project_x(value: float) -> float:
            return left + (value - x_min) / (x_max - x_min) * (right - left)

        def project_y(value: float) -> float:
            return bottom - (value - y_min) / (y_max - y_min) * (bottom - top)

        canvas.create_line(left, top, left, bottom, fill="#aab8c0")
        canvas.create_line(left, bottom, right, bottom, fill="#aab8c0")
        projected = [(project_x(x), project_y(y), job_id) for x, y, job_id in points]
        if len(projected) > 1 and len(set(x_values)) == len(x_values):
            line_coordinates = [coordinate for point in projected for coordinate in point[:2]]
            canvas.create_line(*line_coordinates, fill=COLORS["blue"], width=2)
        best_job_id = max(rows, key=lambda row: row["value"])["job_id"]
        for x, y, job_id in projected:
            color = COLORS["teal"] if job_id == best_job_id else COLORS["blue"]
            radius = 5 if job_id == best_job_id else 4
            canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=color,
                outline="white",
                width=1,
            )
        canvas.create_text(
            left,
            bottom + 18,
            text=self._format_number(x_min),
            anchor="w",
            fill=COLORS["muted"],
            font=("Segoe UI", 8),
        )
        canvas.create_text(
            right,
            bottom + 18,
            text=self._format_number(x_max),
            anchor="e",
            fill=COLORS["muted"],
            font=("Segoe UI", 8),
        )
        x_dimension = next(iter(x_dimensions), None)
        x_unit = reference_unit(x_dimension)
        x_label = f"{x_name} [{x_unit}]" if x_unit else x_name
        canvas.create_text(
            (left + right) / 2,
            height - 10,
            text=x_label,
            fill=COLORS["muted"],
            font=("Segoe UI Semibold", 8),
        )
        canvas.create_text(
            left - 8,
            top,
            text=self._format_number(y_max),
            anchor="e",
            fill=COLORS["muted"],
            font=("Segoe UI", 8),
        )
        canvas.create_text(
            left - 8,
            bottom,
            text=self._format_number(y_min),
            anchor="e",
            fill=COLORS["muted"],
            font=("Segoe UI", 8),
        )

    def _export_comparison(self) -> None:
        if not self.current_comparison_rows:
            messagebox.showinfo(
                "Export comparison",
                "There are no comparison rows to export.",
                parent=self.root,
            )
            return
        batch = self._selected_comparison_batch() or "all-batches"
        metric = self.compare_metric_var.get() or "metric"
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{batch}-{metric}").strip("-")
        selected = filedialog.asksaveasfilename(
            title="Export comparison CSV",
            defaultextension=".csv",
            initialfile=f"{safe_name or 'comparison'}.csv",
            filetypes=[("CSV file", "*.csv"), ("All files", "*")],
        )
        if not selected:
            return
        try:
            output = write_comparison_csv(selected, self.current_comparison_rows)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Export comparison", str(exc), parent=self.root)
            return
        self.activity_var.set(f"Comparison exported to {output.name}.")

    def _set_run_actions(self, enabled: bool) -> None:
        state = "normal" if enabled and not self.busy else "disabled"
        queue_paused = self.store.is_queue_paused()
        run_state = "disabled" if queue_paused else state
        self.run_now_button.configure(state=run_state)
        self.queue_button.configure(state=state)
        self.run_next_button.configure(state=run_state)
        self.review_plan_button.configure(state=state)
        self._update_queue_controls()

    def _run_background(
        self,
        operation: str,
        task: Callable[[], Any],
        on_success: Callable[[Any], None],
    ) -> None:
        if self.busy:
            return
        self.busy = True
        self.check_button.configure(state="disabled")
        self._set_run_actions(False)
        if operation == "run":
            self.root.after(250, self._refresh_active_run)

        def worker() -> None:
            try:
                result = task()
            except Exception as exc:
                self.root.after(
                    0,
                    lambda error=exc: self._background_failed(operation, error),
                )
                return
            self.root.after(0, lambda: self._background_succeeded(result, on_success))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_active_run(self) -> None:
        if not self.busy:
            return
        self.refresh_jobs(refresh_comparison=False)
        self.root.after(500, self._refresh_active_run)

    def _background_succeeded(
        self,
        result: Any,
        callback: Callable[[Any], None],
    ) -> None:
        self.busy = False
        self.check_button.configure(state="normal")
        self._set_run_actions(self.connection_report is not None)
        callback(result)

    def _background_failed(self, operation: str, error: Exception) -> None:
        self.busy = False
        self.check_button.configure(state="normal")
        self._set_run_actions(self.connection_report is not None)
        self.connection_status_var.set("Check failed" if operation == "check" else "Connected")
        self.activity_var.set(f"{operation.title()} failed: {error}")
        messagebox.showerror(operation.title(), str(error), parent=self.root)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        rounded = max(0, round(seconds))
        hours, remainder = divmod(rounded, 3600)
        minutes, remaining_seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {remaining_seconds}s"
        return f"{remaining_seconds}s"

    @staticmethod
    def _format_number(value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.9g}"
        return str(value)


def run_desktop(
    database_path: str | Path,
    artifact_root: str | Path,
    profile_path: str | Path = ".sim-assistant/profiles.json",
) -> None:
    root = tk.Tk()
    DesktopApp(root, database_path, artifact_root, profile_path)
    root.mainloop()
