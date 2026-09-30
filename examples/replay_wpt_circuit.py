"""Replay stored COMSOL results in an isolated example workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from simulation_assistant.storage import JobStore
from simulation_assistant.types import Job
from simulation_assistant.wpt_circuit import (
    TwoPortMetricMap,
    analyze_fixed_control_scenarios,
    write_circuit_study_csv,
    write_circuit_study_html,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop", action="store_true", help="Open the native UI")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(".sim-assistant/wpt-example"),
        help="Isolated workspace for the example database and reports",
    )
    args = parser.parse_args()
    dataset = json.loads(
        Path(__file__).with_name("wpt_circuit_results.json").read_text(encoding="utf-8")
    )
    if dataset.get("schema") != "wpt.circuit.example.v1":
        raise ValueError("Unsupported example dataset")
    store = JobStore(args.workspace / "jobs.db")
    store.initialize()
    jobs_by_case: dict[str, Job] = {}
    for case in reversed(dataset["cases"]):
        if not case["source_valid"] or not all(case["source_checks"].values()):
            raise ValueError(f"Source checks did not pass for {case['name']}")
        existing = next(
            (
                job
                for job in store.list(limit=100)
                if (job.result or {}).get("metadata", {}).get("source_sha256")
                == case["source_sha256"]
            ),
            None,
        )
        if existing is not None:
            jobs_by_case[case["name"]] = existing
            continue
        job_id = store.enqueue_batch(
            "WPT real-data example",
            "comsol",
            [{"case": case["name"], **case["parameters"]}],
        )[0]
        store.claim(job_id)
        store.mark_succeeded(
            job_id,
            {
                "metrics": case["metrics"],
                "metadata": {
                    "origin": "Imported stored COMSOL result; replay only",
                    "source_sha256": case["source_sha256"],
                    "source_checks": case["source_checks"],
                    "scientific_validation": {
                        "status": "valid",
                        "basis": "All recorded source qualification checks passed",
                    },
                },
            },
            "",
        )
        jobs_by_case[case["name"]] = store.get(job_id)
    nominal = jobs_by_case[dataset["nominal_case"]]
    study = analyze_fixed_control_scenarios(
        nominal,
        jobs_by_case.values(),
        TwoPortMetricMap(
            "frequency_Hz", "L1_H", "L2_H", "M12_H", "M21_H",
            "R1_ohm", "R2_ohm", "R12_ohm", "R21_ohm",
        ),
    )
    csv_path = write_circuit_study_csv(args.workspace / "circuit-study.csv", study)
    html_path = write_circuit_study_html(args.workspace / "circuit-study.html", study)
    print(f"Replayed {len(study.scenarios)} stored simulation results")
    print(f"{study.passed_count} passed, {study.failed_count} failed")
    print(f"CSV: {csv_path}")
    print(f"HTML: {html_path}")
    if args.desktop:
        import tkinter as tk

        from simulation_assistant.desktop import DesktopApp

        root = tk.Tk()
        app = DesktopApp(
            root,
            store.path,
            args.workspace / "artifacts",
            args.workspace / "profiles.json",
        )
        app.notebook.select(1)
        root.mainloop()


if __name__ == "__main__":
    main()
