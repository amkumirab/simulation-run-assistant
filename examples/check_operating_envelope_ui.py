"""Verify the native envelope workflow against stored COMSOL data, without solves."""
from __future__ import annotations

import tempfile
import argparse
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from replay_design_campaign import replay
from simulation_assistant.design_campaign_ui import DesignCampaignDialog
from simulation_assistant.desktop import DesktopApp
from simulation_assistant.envelope_ui import OperatingEnvelopeDialog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path, help="Optional native-window captures; requires Pillow on Windows")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="envelope-ui-check-") as directory:
        folder = Path(directory)
        store, campaign = replay(folder)
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        app = DesktopApp(root, store.path, folder / "artifacts", folder / "profiles.json")
        before = len(store.list())
        parent = DesignCampaignDialog(app)
        parent.design_tree.selection_set(str(campaign.plan.designs[0].source_job_id))
        parent.scenarios = list(campaign.plan.scenarios)
        parent.populate_scenarios()
        assert parent.preview() is not None
        dialog = parent.open_envelope()
        assert isinstance(dialog, OperatingEnvelopeDialog)
        assert len(dialog.report.rows) == 5
        assert [row.status for row in dialog.report.rows].count("derated") == 2
        dialog.variables["max_source_rms_v"].set("1")
        assert dialog.report is None and not dialog.tree.get_children()
        dialog.analyze()
        assert all(row.status == "derated" for row in dialog.report.rows)
        dialog.variables["max_source_rms_v"].set("nan")
        assert dialog.analyze() is None and "finite" in dialog.summary.get()
        assert not dialog.chart.find_all()
        dialog.variables["max_source_rms_v"].set("400")
        dialog.analyze()
        for suffix in (".csv", ".html"):
            destination = folder / ("envelope" + suffix)
            with patch("simulation_assistant.envelope_ui.filedialog.asksaveasfilename", return_value=str(destination)):
                dialog.export(suffix)
            assert destination.exists()
        root.deiconify()
        for size in ("960x700", "1440x900"):
            dialog.window.geometry(size)
            root.update()
            assert dialog.tree.winfo_height() > 120
            assert dialog.chart.winfo_width() > 600
            assert dialog.actions.winfo_y() + dialog.actions.winfo_height() <= dialog.body.winfo_height()
        dialog.tree.selection_set("0")
        dialog.tree.focus("0")
        dialog.window.lift()
        dialog.tree.focus_force()
        root.update()
        dialog.tree.event_generate("<Return>")
        root.update()
        assert dialog.detail_window.winfo_exists()
        first_details = dialog.detail_window
        dialog.show_details()
        second_details = dialog.detail_window
        first_details.focus_force()
        root.update()
        first_details.event_generate("<Escape>")
        root.update()
        assert not first_details.winfo_exists() and second_details.winfo_exists()
        second_details.destroy()
        if args.capture_dir:
            import ctypes
            from PIL import ImageGrab
            args.capture_dir.mkdir(parents=True, exist_ok=True)
            dialog.window.geometry("1440x900+60+40")
            dialog.window.lift()
            for source, name in (("400", "wpt-envelope-results.png"), ("25", "wpt-envelope-source-limit.png")):
                dialog.variables["max_source_rms_v"].set(source)
                dialog.analyze()
                root.update()
                window_api = ctypes.windll.user32
                window_api.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                window_api.GetAncestor.restype = ctypes.c_void_p
                window = window_api.GetAncestor(dialog.window.winfo_id(), 2)
                ImageGrab.grab(window=window).save(args.capture_dir / name)
        assert len(store.list()) == before, "Offline analysis must not enqueue jobs"
        assert not errors, errors
        dialog.window.destroy()
        parent.window.destroy()
        root.destroy()
    print("Native envelope checks passed: campaign integration, real-data replay, invalid-input clearing,")
    print("limit editing, CSV/HTML exports, keyboard details, offline isolation and minimum-size layout.")


if __name__ == "__main__":
    main()
