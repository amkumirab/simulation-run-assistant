import csv
import tempfile
try:
    import tkinter as tk
except ImportError:
    tk = None
import unittest
from pathlib import Path
from unittest.mock import patch

from simulation_assistant.storage import JobStore


@unittest.skipIf(tk is None, "Native checks require Tk; use the native workflow script on a desktop")
class SweepWorkspaceDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("Native checks require a display; database tests remain headless")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        from simulation_assistant.desktop import DesktopApp
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        store = JobStore(self.base / "jobs.db")
        store.initialize()
        self.ids = store.enqueue_batch("old sweep", "mock-em", [{"gap": i} for i in range(650)])
        store.enqueue_batch("recent sweep", "mock-em", [{"gap": i} for i in range(1200)])
        with store._connect() as connection:
            connection.execute("UPDATE jobs SET status='succeeded', result=?",
                               ('{"metrics":{"power":1}}',))
            connection.execute("UPDATE jobs SET result=? WHERE id=?",
                               ('{"metrics":{"power":999}}', self.ids[0]))
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.app = DesktopApp(self.root, store.path, self.base / "artifacts", self.base / "profiles.json")

    def test_chart_markers_are_bounded_and_selected_rows_readable(self):
        from tkinter import ttk
        self.assertNotIn(ttk.Style(self.root).lookup("Treeview", "foreground", ("selected",)), ("white", "#ffffff"))
        self.app.compare_x_var.set("Job ID")
        self.app._draw_comparison_chart()
        markers = [item for item in self.app.compare_chart.find_all() if self.app.compare_chart.type(item) == "oval"]
        self.assertLessEqual(len(markers), 1000)

    def test_small_fraction_axis_labels_fit_chart(self):
        self.app.current_comparison_rows = [
            {"job_id": 1, "value": 0.0573373653, "parameters": {}},
            {"job_id": 2, "value": 0.0356274729, "parameters": {}},
        ]
        self.app.compare_x_var.set("Job ID")
        self.app._draw_comparison_chart()
        canvas = self.app.compare_chart
        for item in canvas.find_all():
            if canvas.type(item) == "text":
                self.assertGreaterEqual(canvas.bbox(item)[0], 0)

    def test_complete_comparison_rank_and_csv_independent_of_page(self):
        self.assertIn("old sweep", self.app.compare_batch.cget("values"))
        self.app.compare_batch_var.set("old sweep")
        self.app.refresh_comparison()
        self.app.compare_metric_var.set("power")
        self.app._refresh_comparison_rows()
        self.assertEqual(len(self.app.current_comparison_rows), 650)
        self.assertIn("Job #1", self.app.compare_best_var.get())
        self.assertEqual(len(self.app.compare_tree.get_children()), 100)
        self.app.compare_pager.move(1)
        self.assertEqual(len(self.app.compare_tree.get_children()), 100)
        self.app.ranking_batch_var.set("old sweep")
        self.app._refresh_ranking_options()
        self.assertEqual(self.app.current_ranking_result.rows[0].job_id, self.ids[0])
        self.app.ranking_pager.move(1)
        self.assertEqual(len(self.app.ranking_tree.get_children()), 100)
        for name, export in (("comparison", self.app._export_comparison), ("ranking", self.app._export_ranking)):
            target = self.base / (name + ".csv")
            with patch("simulation_assistant.desktop.filedialog.asksaveasfilename", return_value=str(target)):
                export()
            with target.open(newline="", encoding="utf-8") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 650)
        self.assertFalse(self.errors)

    def test_workspace_search_paging_selection_and_empty_state(self):
        from simulation_assistant.sweep_workspace import SweepWorkspaceDialog
        dialog = SweepWorkspaceDialog(self.root, self.app.store, self.app._show_job,
                                      self.app._compare_workspace_batch, self.app._rank_workspace_batch)
        dialog.search_var.set("old sweep")
        dialog.refresh_batches()
        self.assertEqual(len(dialog.batch_tree.get_children()), 1)
        item = dialog.batch_tree.get_children()[0]
        dialog.batch_tree.selection_set(item)
        dialog.select_batch()
        self.assertEqual(dialog.job_pager.total, 650)
        dialog.job_pager.move(6)
        self.assertEqual(len(dialog.job_tree.get_children()), 50)
        dialog.job_search_var.set("never-exists")
        dialog.refresh_jobs(reset=True)
        self.assertEqual(dialog.job_pager.total, 0)
        dialog.search_var.set("never-exists")
        dialog.refresh_batches()
        self.assertIsNone(dialog.selected_batch)
        self.assertEqual(dialog.job_tree.get_children(), ())
        dialog.window.destroy()
        self.assertFalse(self.errors)

    def test_queued_only_batch_does_not_compare_another_batch(self):
        self.app.store.enqueue_batch("pending only", "mock-em", [{}])
        self.app._compare_workspace_batch("pending only")
        self.assertEqual(self.app.current_comparison_rows, [])
        self.app._rank_workspace_batch("pending only")
        self.assertIsNone(self.app.current_ranking_result)

    def test_reserved_batch_label_is_an_exact_batch(self):
        ids = self.app.store.enqueue_batch("All batches", "mock-em", [{}])
        self.app.store.claim(ids[0])
        self.app.store.mark_succeeded(ids[0], {"metrics": {"power": 42}}, "")
        self.app._compare_workspace_batch("All batches")
        self.assertEqual(len(self.app.current_comparison_rows), 1)
        self.assertEqual(self.app.current_comparison_rows[0]["job_id"], ids[0])
