import csv
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
try:
    import tkinter as tk
except ImportError:
    tk = None

from test_field_samples import metadata
from simulation_assistant.field_sample_files import FIELD_COLUMNS


@unittest.skipIf(tk is None, "Native checks require Tk")
class FieldSampleDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("Native checks require a display")
        self.addCleanup(self.close_root)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        from simulation_assistant.desktop import DesktopApp
        self.app = DesktopApp(self.root, self.base / "jobs.db", self.base / "artifacts", self.base / "profiles.json")
        from simulation_assistant.field_sample_ui import FieldSamplesDialog
        self.dialog = FieldSamplesDialog(self.app.root)
        self.root.report_callback_exception = lambda *args: self.fail(str(args))
        self.csv = self.base / "fields.csv"
        self.csv.write_text(",".join(FIELD_COLUMNS)+"\nAligned,S1,0,0,0,1,0,0,0,2,1\nOffset,S1,0,0,0,2,0,0,0,1,2\n")

    def close_root(self):
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.root.destroy()

    def import_fixture(self):
        for name, value in asdict(metadata()).items():
            self.dialog.meta_vars[name].set(str(value))
        with patch("simulation_assistant.field_sample_ui.filedialog.askopenfilename", return_value=str(self.csv)):
            self.dialog.import_csv()
        self.assertIsNotNone(self.dialog.data, self.dialog.summary.get())
        self.dialog.use_points()

    def test_offline_import_projection_and_no_queue_mutation(self):
        self.import_fixture()
        self.dialog.scenario.set("Offset")
        readings = self.dialog.analyze()
        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].projected_t, 1e-6+2e-6j)
        self.assertIn("synthetic", self.dialog.origin.get().lower())
        self.assertEqual(self.app.store.page_jobs().total, 0)
        self.assertIsNone(self.app.connection_report)

    def test_save_load_export_and_metadata_invalidation(self):
        self.import_fixture()
        workspace = self.base / "workspace.json"
        with patch("simulation_assistant.field_sample_ui.filedialog.asksaveasfilename", return_value=str(workspace)):
            self.dialog.save()
        original = self.dialog.data
        self.dialog.meta_vars["excitation"].set("Different")
        self.assertIsNone(self.dialog.data)
        self.assertFalse(self.dialog.tree.get_children())
        with patch("simulation_assistant.field_sample_ui.filedialog.askopenfilename", return_value=str(workspace)):
            self.dialog.load()
        self.assertEqual(self.dialog.data, original)
        report = self.base / "report.csv"
        with patch("simulation_assistant.field_sample_ui.filedialog.asksaveasfilename", return_value=str(report)):
            self.dialog.export()
        with report.open(newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 1)

    def test_edit_requires_apply_and_failed_import_clears_results(self):
        self.import_fixture()
        self.dialog.analyze()
        self.dialog.layout.select_sensor("S1")
        self.dialog.layout.variables["z_mm"].set("100")
        self.assertFalse(self.dialog.tree.get_children())
        self.assertIsNone(self.dialog.analyze())
        self.assertIn("Apply", self.dialog.summary.get())
        self.dialog.layout.apply()
        self.assertEqual(self.dialog.analyze()[0].status, "position mismatch")
        self.csv.write_text("invalid")
        with patch("simulation_assistant.field_sample_ui.filedialog.askopenfilename", return_value=str(self.csv)):
            self.dialog.import_csv()
        self.assertIsNone(self.dialog.data)
        self.assertFalse(self.dialog.tree.get_children())

    def test_new_csv_import_requires_an_explicit_new_layout(self):
        self.import_fixture()
        self.dialog.analyze()
        with patch("simulation_assistant.field_sample_ui.filedialog.askopenfilename", return_value=str(self.csv)):
            self.dialog.import_csv()
        self.assertFalse(self.dialog.layout.sensors)
        self.assertIsNone(self.dialog.analyze())

    def test_runs_toolbar_opens_an_empty_offline_dialog(self):
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        button = next(widget for widget in widgets(self.app.root)
                      if widget.winfo_class() == "TButton" and widget.cget("text") == "Field samples")
        self.app.notebook.select(1)
        before = set(self.root.winfo_children())
        button.invoke()
        windows = set(self.root.winfo_children()) - before
        self.assertEqual(len(windows), 1)
        window = windows.pop()
        self.assertEqual(window.title(), "Field Samples & Sensor Layout")
        window.destroy()
        self.assertEqual(self.app.store.page_jobs().total, 0)


if __name__ == "__main__":
    unittest.main()
