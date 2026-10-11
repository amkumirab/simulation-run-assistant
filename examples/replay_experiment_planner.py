"""Separate unsolved DOE samples from five imported stored COMSOL results."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from simulation_assistant.experiment_files import save_experiment
from simulation_assistant.experiments import ExperimentDesign, ExperimentSpec, InputRange, generate_experiments
from simulation_assistant.storage import JobStore
from simulation_assistant.preflight import build_run_signature


def replay(workspace: Path):
    marker = workspace / "experiment-example.txt"
    if workspace.exists() and any(workspace.iterdir()) and not marker.is_file():
        raise ValueError("Choose a new workspace; this directory is not an experiment example")
    workspace.mkdir(parents=True, exist_ok=True)
    marker.write_text("Isolated stored experiment example; no new physics solves.\n", encoding="utf-8")
    store = JobStore(workspace / "jobs.db")
    store.initialize()
    dataset = json.loads(Path(__file__).with_name("wpt_circuit_results.json").read_text(encoding="utf-8"))
    fixed = {key: str(value) for key, value in dataset["geometry"].items()}
    fixed["yoff"] = "0.0[mm]"
    context = {"origin": "Stored COMSOL example, scalar text normalized; no new solve", "design": dataset["design_id"]}
    points = []
    for case in dataset["cases"]:
        if not case["source_valid"] or not all(case["source_checks"].values()):
            raise ValueError("Stored source evidence did not pass its recorded checks")
        point = {**fixed, **case["parameters"]}
        points.append(point)
        signature = build_run_signature("comsol", point, {}, context)
        if not store.list_by_run_signatures([signature]):
            job_id = store.enqueue_batch("Stored WPT experiment replay (not new DOE solves)", "comsol", [point], run_context=context)[0]
            store.claim(job_id)
            store.mark_succeeded(job_id, {"metrics": case["metrics"], "metadata": {
                "origin": "Imported stored COMSOL data; not a new solve or hardware measurement",
                "source_sha256": case["source_sha256"], "source_checks": case["source_checks"],
                "scientific_validation": {"status": "valid", "basis": "Recorded stored source checks"}}}, "")
    spec = ExperimentSpec((InputRange("gap", "100[mm]", "200[mm]"),
                           InputRange("xoff", "0[mm]", "60[mm]"), InputRange("tilt", "0[deg]", "10[deg]")),
                          fixed, len(points))
    stored_path = save_experiment(workspace / "stored-evidence.json", ExperimentDesign(spec, tuple(points)), context, {}, method="stored-points-v1")
    demo = generate_experiments(ExperimentSpec((InputRange("r_out", "8[cm]", "12[cm]"),
                            InputRange("N1", "8", "16", "integer"), InputRange("gap", "10[cm]", "20[cm]")),
                            {"r_in": "4[cm]", "N2": "10", "f0": "85[kHz]"}, 30, 7, True))
    demo_path = save_experiment(workspace / "unsolved-doe.json", demo,
                                {"origin": "Unsolved sampling example only; no connected COMSOL identity"}, {})
    return store, stored_path, demo_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(".sim-assistant/experiment-example"))
    parser.add_argument("--desktop", action="store_true")
    args = parser.parse_args()
    store, path, demo = replay(args.workspace)
    print(f"Five stored COMSOL states: {path.resolve()}")
    print(f"Thirty unsolved sampling states: {demo.resolve()}")
    if args.desktop:
        import tkinter as tk
        from simulation_assistant.desktop import DesktopApp
        from simulation_assistant.experiment_ui import ExperimentDialog
        from unittest.mock import patch
        root = tk.Tk()
        app = DesktopApp(root, store.path, args.workspace / "artifacts", args.workspace / "profiles.json")
        dialog = ExperimentDialog(app)
        with patch("simulation_assistant.experiment_ui.filedialog.askopenfilename", return_value=str(path)):
            dialog.load()
        dialog.batch.set("Stored WPT replay - no new solves")
        root.mainloop()


if __name__ == "__main__":
    main()
