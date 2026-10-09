"""Verify native sweep history with stored COMSOL replay or an optional live solve.

Synthetic stress records test database/UI scale only. They are not physics data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
import time
import tkinter as tk
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from replay_design_campaign import replay
from simulation_assistant.adapters.comsol import ComsolAdapter, ComsolConfig, inspect_mph
from simulation_assistant.desktop import DesktopApp
from simulation_assistant.storage import JobStore
from simulation_assistant.sweep_workspace import SweepWorkspaceDialog


def live_replay(folder: Path, model: Path) -> JobStore:
    original_hash = hashlib.sha256(model.read_bytes()).hexdigest()
    info = inspect_mph(model)
    if "gap" not in info.parameters or not info.studies:
        raise ValueError("Live check requires a model with a gap parameter and a study")
    store = JobStore(folder / "jobs.db")
    store.initialize()
    config = ComsolConfig.from_environment(model_path=model, study_tag=info.studies[0]["tag"],
                                          timeout_seconds=300, cores=2)
    adapter = ComsolAdapter(config)
    ids = store.enqueue_batch("Live COMSOL gap smoke test", "comsol", [{"gap": "15[cm]"}, {"gap": "16[cm]"}],
                              run_context={"origin": "New live COMSOL study solves; solver metrics only"})
    try:
        for job_id in ids:
            job = store.claim(job_id)
            artifacts = folder / "artifacts" / f"job-{job_id:06d}"
            result = adapter.run(job.parameters, work_dir=artifacts)
            store.mark_succeeded(job_id, result.to_dict(), str(artifacts))
            print(f"Live Job #{job_id}: {result.metrics}", flush=True)
    finally:
        assert hashlib.sha256(model.read_bytes()).hexdigest() == original_hash, "Source model changed"
    evidence = {"source_model": model.name, "source_sha256": original_hash, "source_unchanged": True,
                "origin": "Two new live COMSOL solves; no two-port efficiency claim",
                "jobs": [{"id": job.id, "inputs": job.parameters, "metrics": job.result["metrics"]}
                         for job in store.iter_jobs()]}
    (folder / "live-evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, help="Optional live COMSOL model; runs two copied gap cases")
    parser.add_argument("--workspace", type=Path, help="Optional new isolated workspace to keep live outputs")
    parser.add_argument("--replay-workspace", type=Path, help="Reuse an existing check workspace without new solves")
    parser.add_argument("--capture-dir", type=Path, help="Optional native captures; requires Pillow on Windows")
    args = parser.parse_args()
    if args.capture_dir:
        # Fail before a live solve if the optional capture dependency is absent.
        from PIL import ImageGrab
    if args.replay_workspace and (args.workspace or args.model):
        raise ValueError("Replay workspace cannot be combined with model or new workspace")
    if args.replay_workspace and not (args.replay_workspace / "jobs.db").is_file():
        raise ValueError("Replay workspace must contain an existing check jobs.db")
    if args.workspace and args.workspace.exists():
        raise ValueError("Choose a new workspace so existing jobs are never overwritten")
    saved = args.replay_workspace or args.workspace
    context = nullcontext(saved) if saved else tempfile.TemporaryDirectory(prefix="sweep-ui-")
    with context as directory:
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        store = JobStore(folder / "jobs.db") if args.replay_workspace else (live_replay(folder, args.model) if args.model else replay(folder)[0])
        stress_batch = "Synthetic stress history (not COMSOL)"
        real_batch = next(name for name in store.batch_names() if name != stress_batch)
        real_count = store.page_jobs(batch_name=real_batch).total
        # Deliberately newer synthetic history, in a different batch and adapter.
        if not args.replay_workspace:
            store.enqueue_batch(stress_batch, "mock-em", [{"sample": i} for i in range(10000)],
                                run_context={"origin": "Synthetic scale fixture; no physics solve"})
            with store._connect() as connection:
                connection.execute("UPDATE jobs SET status='succeeded', result=? WHERE batch_name=?",
                                   ('{"metrics":{"fixture_value":1}}', stress_batch))
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        try:
            started = time.perf_counter()
            app = DesktopApp(root, store.path, folder / "artifacts", folder / "profiles.json")
            print(f"Desktop initialization, {10000 + real_count:,} jobs: {time.perf_counter() - started:.3f}s", flush=True)
            dialog = SweepWorkspaceDialog(root, store, app._show_job, app._compare_workspace_batch, app._rank_workspace_batch)
            dialog.search_var.set(real_batch)
            dialog.refresh_batches()
            item = dialog.batch_tree.get_children()[0]
            dialog.batch_tree.selection_set(item)
            dialog.select_batch()
            assert dialog.job_pager.total == real_count
            app._compare_workspace_batch(real_batch)
            if "k" in app.compare_metric.cget("values"):
                app.compare_metric_var.set("k")
                app.compare_x_var.set("xoff")
                app._refresh_comparison_rows()
            assert len(app.current_comparison_rows) == real_count
            app._rank_workspace_batch(real_batch)
            if "k" in app.ranking_objective.cget("values"):
                app.ranking_objective_var.set("k")
                app._calculate_ranking(show_errors=False)
            assert len(app.current_ranking_result.rows) == real_count
            for name, export in (("comparison", app._export_comparison), ("ranking", app._export_ranking)):
                target = folder / (name + ".csv")
                with patch("simulation_assistant.desktop.filedialog.asksaveasfilename", return_value=str(target)):
                    export()
                with target.open(newline="", encoding="utf-8") as stream:
                    assert len(list(csv.DictReader(stream))) == real_count
            root.deiconify()
            root.geometry("1440x900")
            for size in ("860x640", "1120x760"):
                dialog.window.geometry(size)
                root.update()
                assert dialog.job_tree.winfo_height() > 80
                assert dialog.job_pager.winfo_y() + dialog.job_pager.winfo_height() < dialog.window.winfo_height()
            if args.capture_dir:
                import ctypes
                from PIL import ImageGrab
                args.capture_dir.mkdir(parents=True, exist_ok=True)
                dialog.window.lift()
                root.update()
                handle = ctypes.windll.user32.GetAncestor(dialog.window.winfo_id(), 2)
                ImageGrab.grab(window=handle).save(args.capture_dir / "sweep-workspace.png")
                dialog.window.withdraw()
                app.notebook.select(2)
                root.update()
                handle = ctypes.windll.user32.GetAncestor(root.winfo_id(), 2)
                ImageGrab.grab(window=handle).save(args.capture_dir / "sweep-comparison.png")
            # Real keyboard event opens the original run-details workflow.
            dialog.window.deiconify()
            selected = dialog.job_tree.get_children()[0]
            dialog.job_tree.selection_set(selected)
            dialog.job_tree.focus_force()
            root.update()
            before = len(root.winfo_children())
            dialog.job_tree.event_generate("<Return>")
            root.update()
            assert len(root.winfo_children()) > before
            assert not errors, errors
            print(f"PASS: {real_count} real/stored records, 10,000 synthetic records, complete CSVs, layouts and Enter", flush=True)
        finally:
            root.destroy()


if __name__ == "__main__":
    main()
