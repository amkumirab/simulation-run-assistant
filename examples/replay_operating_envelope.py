"""Calculate source-amplitude envelopes from the published stored COMSOL cases."""
from __future__ import annotations

import argparse
from pathlib import Path

from replay_design_campaign import replay
from simulation_assistant.envelope_reports import write_envelope_csv, write_envelope_html
from simulation_assistant.operating_envelopes import EnvelopeLimits, analyze_operating_envelope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(".sim-assistant/envelope-example"))
    parser.add_argument("--source-limit", type=float, default=400, help="Fundamental AC source ceiling in V RMS; provisional")
    parser.add_argument("--report-dir", type=Path, help="Optional directory for portable CSV/HTML reports")
    parser.add_argument("--desktop", action="store_true")
    args = parser.parse_args()
    limits = EnvelopeLimits(args.source_limit)
    store, campaign = replay(args.workspace)
    signatures = tuple(state.signature for state in campaign.plan.campaign.states)
    jobs_provider = lambda: store.list_by_run_signatures(signatures)
    report = analyze_operating_envelope(campaign, jobs_provider(), limits)
    destination = args.report_dir or args.workspace
    write_envelope_csv(destination / "wpt-operating-envelope.csv", report)
    write_envelope_html(destination / "wpt-operating-envelope.html", report)
    print("Stored COMSOL replay only; no new solve or hardware measurement.")
    for row in report.rows:
        power = f"{row.maximum_load_power_w:.3f} W" if row.maximum_load_power_w is not None else "Unavailable"
        print(f"{row.scenario}: {row.status}; maximum modeled power {power}; limits {', '.join(row.limiting_constraints)}")
    print(f"Reports: {destination.resolve()}")
    if args.desktop:
        import tkinter as tk
        from simulation_assistant.desktop import DesktopApp
        from simulation_assistant.envelope_ui import OperatingEnvelopeDialog
        root = tk.Tk()
        app = DesktopApp(root, store.path, args.workspace / "artifacts", args.workspace / "profiles.json")
        dialog = OperatingEnvelopeDialog(root, campaign, jobs_provider)
        dialog.variables["max_source_rms_v"].set(str(args.source_limit))
        dialog.analyze()
        root.mainloop()


if __name__ == "__main__":
    main()
