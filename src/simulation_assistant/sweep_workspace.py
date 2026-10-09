"""Read-only, paginated sweep history. Run controls live in existing details."""

import tkinter as tk
from tkinter import ttk
from typing import Callable

from simulation_assistant.storage import JobStore
from simulation_assistant.table_paging import TablePager
from simulation_assistant.types import Job, JobStatus


class SweepWorkspaceDialog:
    def __init__(self, parent, store: JobStore, show_job: Callable[[Job], None],
                 compare_batch: Callable[[str], None], rank_batch: Callable[[str], None]):
        self.store = store
        self.show_job = show_job
        self.compare_batch = compare_batch
        self.rank_batch = rank_batch
        self.selected_batch: str | None = None
        self.batch_names: dict[str, str] = {}
        self.window = tk.Toplevel(parent)
        self.window.title("Sweep workspace")
        self.window.geometry("1120x760")
        self.window.minsize(860, 640)
        self.window.bind("<Escape>", lambda _event: self.window.destroy())
        body = ttk.Frame(self.window, padding=16, style="Card.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)
        body.rowconfigure(6, weight=2)
        ttk.Label(body, text="Sweep workspace", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        filters = ttk.Frame(body, style="Card.TFrame")
        filters.grid(row=1, column=0, sticky="ew", pady=8)
        ttk.Label(filters, text="Batch search", style="Field.TLabel").pack(side="left")
        self.search_var = tk.StringVar()
        search = ttk.Entry(filters, textvariable=self.search_var, width=30)
        search.pack(side="left", padx=8)
        search.bind("<Return>", lambda _event: self.refresh_batches())
        ttk.Button(filters, text="Search", style="Secondary.TButton", command=self.refresh_batches).pack(side="left")
        ttk.Button(filters, text="Refresh", style="Secondary.TButton", command=lambda: self.refresh_batches(reset=False)).pack(side="right")
        self.batch_tree = self._table(body, 2, (
            ("batch", "BATCH", 280), ("total", "TOTAL", 75),
            ("succeeded", "SUCCEEDED", 100), ("failed", "FAILED", 85),
            ("queued", "QUEUED", 85), ("running", "RUNNING", 90),
            ("cancelled", "CANCELLED", 95),
        ))
        self.batch_tree.bind("<<TreeviewSelect>>", self.select_batch)
        self.batch_tree.bind("<Return>", self.select_batch)
        self.batch_pager = TablePager(body, lambda: self.refresh_batches(reset=False), page_size=30)
        self.batch_pager.grid(row=3, column=0, sticky="ew")
        self.summary_var = tk.StringVar(value="Choose a batch to browse its runs.")
        ttk.Label(body, textvariable=self.summary_var, style="CardText.TLabel", wraplength=800).grid(row=4, column=0, sticky="w", pady=8)
        run_filters = ttk.Frame(body, style="Card.TFrame")
        run_filters.grid(row=5, column=0, sticky="ew", pady=(0, 8))
        self.status_var = tk.StringVar(value="All statuses")
        status = ttk.Combobox(run_filters, textvariable=self.status_var, state="readonly",
                              values=["All statuses", *[item.value for item in JobStatus]], width=14)
        status.pack(side="left")
        status.bind("<<ComboboxSelected>>", lambda _event: self.refresh_jobs(reset=True))
        self.job_search_var = tk.StringVar()
        entry = ttk.Entry(run_filters, textvariable=self.job_search_var, width=22)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda _event: self.refresh_jobs(reset=True))
        ttk.Button(run_filters, text="Search runs", style="Secondary.TButton", command=lambda: self.refresh_jobs(reset=True)).pack(side="left")
        self.compare_button = ttk.Button(run_filters, text="Compare batch", style="Secondary.TButton", command=self.open_comparison)
        self.compare_button.pack(side="right")
        self.rank_button = ttk.Button(run_filters, text="Rank batch", style="Secondary.TButton", command=self.open_ranking)
        self.rank_button.pack(side="right", padx=8)
        self.job_tree = self._table(body, 6, (
            ("id", "JOB", 65), ("status", "STATUS", 105), ("adapter", "ADAPTER", 90),
            ("inputs", "INPUTS", 400), ("attempts", "ATTEMPTS", 90),
        ))
        self.job_tree.bind("<Double-1>", self.open_job)
        self.job_tree.bind("<Return>", self.open_job)
        self.job_pager = TablePager(body, self.refresh_jobs)
        self.job_pager.grid(row=7, column=0, sticky="ew")
        ttk.Label(body, text="Counts are job records, not validated scenario coverage. Queue pause remains global.",
                  style="CardText.TLabel", wraplength=800).grid(row=8, column=0, sticky="w")
        self.refresh_batches()

    @staticmethod
    def _table(parent, row, columns):
        frame = ttk.Frame(parent, style="Card.TFrame")
        frame.grid(row=row, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=[item[0] for item in columns], show="headings", height=5,
                            selectmode="browse")
        for name, title, width in columns:
            tree.heading(name, text=title)
            tree.column(name, width=width, minwidth=60, stretch=name in {"batch", "inputs"})
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        return tree

    def refresh_batches(self, *, reset=True):
        offset = 0 if reset else self.batch_pager.offset
        page = self.store.page_batches(search=self.search_var.get(), limit=30, offset=offset)
        self.batch_pager.set_total(page.total, reset=reset)
        if self.batch_pager.offset != page.offset:
            page = self.store.page_batches(search=self.search_var.get(), limit=30, offset=self.batch_pager.offset)
        previous = self.selected_batch
        self.batch_tree.delete(*self.batch_tree.get_children())
        self.batch_names.clear()
        selected_item = None
        for index, batch in enumerate(page.items):
            item = str(index)
            self.batch_names[item] = batch.batch_name
            self.batch_tree.insert("", "end", iid=item, values=(batch.batch_name, batch.total,
                                  *[batch.counts[name] for name in ("succeeded", "failed", "queued", "running", "cancelled")]))
            if batch.batch_name == previous:
                selected_item = item
        if selected_item is not None:
            self.batch_tree.selection_set(selected_item)
            self.select_batch()
        else:
            self.selected_batch = None
            self.summary_var.set("Choose a batch to browse its runs." if page.total else "No batches match this search.")
            self.refresh_jobs(reset=True)

    def select_batch(self, _event=None):
        selected = self.batch_tree.selection()
        if not selected or selected[0] not in self.batch_names:
            return
        batch = self.batch_names[selected[0]]
        changed = batch != self.selected_batch
        self.selected_batch = batch
        values = self.batch_tree.item(selected[0], "values")
        self.summary_var.set(f"{batch} | {values[1]} jobs | {values[2]} succeeded | "
                             f"{values[3]} failed | {int(values[4]) + int(values[5])} remaining")
        self.refresh_jobs(reset=changed)

    def refresh_jobs(self, *, reset=False):
        self.job_tree.delete(*self.job_tree.get_children())
        enabled = self.selected_batch is not None
        for button in (self.compare_button, self.rank_button):
            button.configure(state="normal" if enabled else "disabled")
        if not enabled:
            self.job_pager.set_total(0, reset=True)
            return
        status = None if self.status_var.get() == "All statuses" else JobStatus(self.status_var.get())
        page = self.store.page_jobs(batch_name=self.selected_batch, status=status,
                                    search=self.job_search_var.get(), offset=0 if reset else self.job_pager.offset)
        self.job_pager.set_total(page.total, reset=reset)
        if page.offset != self.job_pager.offset:
            page = self.store.page_jobs(batch_name=self.selected_batch, status=status,
                                        search=self.job_search_var.get(), offset=self.job_pager.offset)
        for job in page.items:
            inputs = ", ".join(f"{name}={value}" for name, value in job.parameters.items())
            self.job_tree.insert("", "end", iid=str(job.id), values=(f"#{job.id}", job.status.value,
                                  job.adapter, inputs, job.attempts))

    def open_job(self, _event=None):
        selected = self.job_tree.selection()
        if selected:
            self.show_job(self.store.get(int(selected[0])))

    def open_comparison(self):
        if self.selected_batch is not None:
            self.compare_batch(self.selected_batch)

    def open_ranking(self):
        if self.selected_batch is not None:
            self.rank_batch(self.selected_batch)
