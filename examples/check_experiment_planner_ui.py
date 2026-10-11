"""Isolated native workflow; optional captures of real app windows, not mockups."""
from __future__ import annotations

import argparse
import csv
import tempfile
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from replay_experiment_planner import replay
from simulation_assistant.desktop import DesktopApp
from simulation_assistant.experiment_ui import ExperimentDialog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path)
    args = parser.parse_args()
    if args.capture_dir:
        from PIL import ImageGrab
        args.capture_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="experiment-ui-") as directory:
        workspace = Path(directory) / "replay"
        store, stored, unsolved = replay(workspace)
        root = tk.Tk()
        try:
            app = DesktopApp(root, store.path, workspace / "artifacts", workspace / "profiles.json")
            root.geometry("1080x800+40+40")
            dialog = ExperimentDialog(app)
            errors = []
            root.report_callback_exception = lambda *error: errors.append(error)
            for filename, path, expected, accepted in (("experiment-unsolved", unsolved, 30, 0),
                                                       ("experiment-stored", stored, 5, 5)):
                with patch("simulation_assistant.experiment_ui.filedialog.askopenfilename", return_value=str(path)):
                    dialog.load()
                assert len(dialog.tree.get_children()) == expected, dialog.summary.get()
                assert dialog.plan.completed_count == accepted
                dialog.batch.set("Stored COMSOL replay - no new solves" if accepted else "Unsolved DOE example - no physics results")
                output = workspace / (filename + ".csv")
                with patch("simulation_assistant.experiment_ui.filedialog.asksaveasfilename", return_value=str(output)):
                    dialog.export()
                with output.open(encoding="utf-8", newline="") as handle:
                    assert len(list(csv.DictReader(handle))) == expected
                dialog.refresh()
                for size in ("920x680", "1080x800"):
                    dialog.window.geometry(size + "+40+40")
                    dialog.window.deiconify()
                    dialog.window.lift()
                    root.update()
                    assert dialog.tree.winfo_ismapped()
                    for widget in dialog.window.winfo_children()[0].winfo_children():
                        if widget.winfo_manager() == "grid":
                            assert widget.winfo_y() + widget.winfo_height() <= dialog.window.winfo_height(), widget
                row = dialog.tree.get_children()[0]
                dialog.tree.selection_set(row)
                dialog.tree.focus(row)
                dialog.tree.focus_force()
                with patch.object(app, "_show_job") as show, patch("simulation_assistant.experiment_ui.messagebox.showinfo") as info:
                    dialog.tree.event_generate("<Return>")
                    root.update()
                    assert show.called if accepted else info.called
                if args.capture_dir:
                    import ctypes
                    root.update()
                    handle = ctypes.windll.user32.GetAncestor(dialog.window.winfo_id(), 2)
                    ImageGrab.grab(window=handle).save(
                        args.capture_dir / (filename + ".png"))
            before = store.page_jobs().total
            dialog.inputs["gap"][2].set("210[mm]")
            assert dialog.saved is None and not dialog.tree.get_children()
            dialog.submit(start=False)
            assert store.page_jobs().total == before == 5
            assert not errors, errors
            print("PASS: 30 unsolved samples, 5 stored COMSOL states, CSVs, layouts, Enter and edit invalidation; no solves")
        finally:
            root.destroy()


if __name__ == "__main__":
    main()
