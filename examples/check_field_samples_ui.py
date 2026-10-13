"""Verify actual native field review using explicitly synthetic phasors; no solves."""
import argparse
import csv
import json
import tempfile
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from simulation_assistant.desktop import DesktopApp
from simulation_assistant.field_samples import FieldMetadata, make_sensor_grid
from simulation_assistant.field_sample_files import load_field_csv, save_field_workspace
from simulation_assistant.field_sample_ui import FieldSamplesDialog


def synthetic_workspace(path):
    source = Path(__file__).with_name("synthetic_field_samples.csv")
    meta = FieldMetadata(**json.loads(source.with_name("synthetic_field_metadata.json").read_text(encoding="utf-8")))
    data = load_field_csv(source, meta)
    save_field_workspace(path, data, make_sensor_grid(3, 3, .02, 0., (0., 0., 1.)))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path)
    parser.add_argument("--desktop", action="store_true", help="Keep an isolated demonstration open")
    args = parser.parse_args()
    if args.capture_dir:
        from PIL import ImageGrab
        args.capture_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="field-review-") as directory:
        folder = Path(directory)
        workspace = synthetic_workspace(folder / "example.json")
        root = tk.Tk()
        try:
            app = DesktopApp(root, folder / "jobs.db", folder / "artifacts", folder / "profiles.json")
            root.geometry("1120x840+40+40")
            app.notebook.select(1)
            def widgets(parent):
                for child in parent.winfo_children():
                    yield child
                    yield from widgets(child)
            field_button = next(widget for widget in widgets(root)
                                if widget.winfo_class() == "TButton" and widget.cget("text") == "Field samples")
            root.update()
            assert field_button.winfo_ismapped()
            before = set(root.winfo_children())
            field_button.invoke()
            root.update()
            opened = set(root.winfo_children()) - before
            assert len(opened) == 1
            opened.pop().destroy()
            dialog = FieldSamplesDialog(root)
            errors = []
            root.report_callback_exception = lambda *error: errors.append(error)
            with patch("simulation_assistant.field_sample_ui.filedialog.askopenfilename", return_value=str(workspace)):
                dialog.load()
            assert len(dialog.readings) == 9
            assert sum(row.status == "available" for row in dialog.readings) == 8
            assert dialog.readings[-1].projected_t is None
            assert "SYNTHETIC" in dialog.origin.get()
            report = folder / "comparison.csv"
            with patch("simulation_assistant.field_sample_ui.filedialog.asksaveasfilename", return_value=str(report)):
                dialog.export()
            with report.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == 9 and rows[-1]["amplitude_t"] == ""
            dialog.analyze()
            for size in ("980x720", "1120x840"):
                dialog.window.geometry(size+"+40+40")
                root.update()
                assert dialog.tree.winfo_ismapped()
                body = dialog.window.winfo_children()[0]
                for widget in body.winfo_children():
                    assert widget.winfo_y()+widget.winfo_height() <= body.winfo_height(), widget
            dialog.tree.selection_set("0")
            dialog.tree.focus_force()
            with patch("simulation_assistant.field_sample_ui.messagebox.showinfo") as details:
                dialog.tree.event_generate("<Return>")
                root.update()
                assert details.called
            if args.capture_dir:
                import ctypes
                handle = ctypes.windll.user32.GetAncestor(dialog.window.winfo_id(), 2)
                ImageGrab.grab(window=handle).save(args.capture_dir / "field-comparison.png")
                dialog.tabs.select(1)
                root.update()
                ImageGrab.grab(window=handle).save(args.capture_dir / "sensor-layout.png")
                dialog.tabs.select(2)
            assert app.store.page_jobs().total == 0 and app.connection_report is None
            assert not errors, errors
            print("PASS: synthetic 3x3 layout, 8/9 available readings, CSV, sizes, keyboard evidence; no queue/model/solver actions")
            if args.desktop:
                root.mainloop()
            else:
                dialog.layout.select_sensor("S1")
                dialog.layout.variables["z_mm"].set("100")
                assert not dialog.readings and not dialog.tree.get_children()
                dialog.meta_vars["field_unit"].set("T")
                assert dialog.data is None
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass  # The user may already have closed the demonstration root.


if __name__ == "__main__":
    main()
