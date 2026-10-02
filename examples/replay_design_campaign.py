"""Replay the published stored WPT cases as a resumable design campaign."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from simulation_assistant.design_campaigns import (
    Scenario, analyze_design_campaign, build_design_campaign, designs_from_jobs,
)
from simulation_assistant.design_campaign_reports import (
    save_design_campaign, write_design_campaign_csv, write_design_campaign_html,
)
from simulation_assistant.preflight import build_run_signature
from simulation_assistant.storage import JobStore
from simulation_assistant.wpt_circuit import TwoPortMetricMap


def replay(workspace: Path):
    dataset = json.loads(Path(__file__).with_name("wpt_circuit_results.json").read_text(encoding="utf-8"))
    if dataset.get("schema") != "wpt.circuit.example.v1":
        raise ValueError("Unsupported example dataset")
    context = {"origin": "Stored COMSOL replay only", "design": dataset["design_id"]}
    store = JobStore(workspace / "jobs.db")
    store.initialize()
    jobs = []
    nominal = next(case for case in dataset["cases"] if case["name"] == dataset["nominal_case"])
    cases = [nominal] + [case for case in dataset["cases"] if case != nominal]
    for case in cases:
        if not case["source_valid"] or not all(case["source_checks"].values()):
            raise ValueError("Source qualification did not pass")
        parameters = {**dataset["geometry"], **case["parameters"]}
        signature = build_run_signature("comsol", parameters, {}, context)
        existing = store.list_by_run_signatures([signature])
        if existing:
            item = existing[0]
        else:
            job_id = store.enqueue_batch("WPT design campaign replay", "comsol", [parameters], run_context=context)[0]
            store.claim(job_id)
            store.mark_succeeded(job_id, {
                "metrics": case["metrics"], "metadata": {
                    "origin": "Imported stored COMSOL result; no new solve",
                    "source_sha256": case["source_sha256"], "source_checks": case["source_checks"],
                    "scientific_validation": {"status": "valid", "basis": "Recorded source checks passed"},
                },
            }, "")
            item = store.get(job_id)
        jobs.append(item)
    designs = designs_from_jobs([jobs[0]])
    scenarios = [Scenario("Nominal", {})] + [Scenario(case["name"], case["parameters"]) for case in cases[1:]]
    plan = build_design_campaign(designs, scenarios, output_formulas={}, run_context=context, existing_jobs=jobs)
    mapping = TwoPortMetricMap("frequency_Hz", "L1_H", "L2_H", "M12_H", "M21_H",
                               "R1_ohm", "R2_ohm", "R12_ohm", "R21_ohm")
    report = analyze_design_campaign(plan, jobs, mapping)
    save_design_campaign(workspace / "design-campaign.json", plan, mapping)
    write_design_campaign_csv(workspace / "design-campaign.csv", report)
    write_design_campaign_html(workspace / "design-campaign.html", report)
    return store, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(".sim-assistant/design-example"))
    parser.add_argument("--desktop", action="store_true")
    args = parser.parse_args()
    store, report = replay(args.workspace)
    result = report.designs[0]
    print(f"Stored-result replay: {result.accepted_count}/{result.required_count} accepted, "
          f"{result.study.passed_count} circuit passes, {result.study.failed_count} failures")
    print(f"Configuration and reports: {args.workspace.resolve()}")
    if args.desktop:
        import tkinter as tk
        from simulation_assistant.desktop import DesktopApp
        from simulation_assistant.design_campaign_ui import DesignCampaignDialog
        root = tk.Tk()
        app = DesktopApp(root, store.path, args.workspace / "artifacts", args.workspace / "profiles.json")
        dialog = DesignCampaignDialog(app)
        dialog.design_tree.selection_set(str(result.design.source_job_id))
        dialog.scenarios = list(report.plan.scenarios)
        dialog.populate_scenarios()
        dialog.preview()
        dialog.design_tree.see(str(result.design.source_job_id))
        root.mainloop()


if __name__ == "__main__":
    main()
