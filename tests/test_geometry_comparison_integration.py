import tempfile
import unittest
from pathlib import Path

from native_test_support import destroy_root
from native_test_support import collect_native_garbage as tearDownModule
from test_geometry_inspector import snapshot

try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, 'Native checks require Tk')
class GeometryComparisonIntegrationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Native checks require a display')
        self.addCleanup(destroy_root, self.root)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        from simulation_assistant.desktop import DesktopApp
        from simulation_assistant.geometry_ui import GeometryDialog
        self.app = DesktopApp(self.root, folder/'jobs.db', folder/'artifacts', folder/'profiles.json')
        self.inspector = GeometryDialog(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)

    def test_inspector_opens_independent_window_with_only_baseline_prefilled(self):
        self.inspector.set_snapshot(snapshot(), 'Stored snapshot')
        comparison = self.inspector.open_comparison()
        self.inspector.close()
        self.assertTrue(comparison.window.winfo_exists())
        self.assertEqual(comparison.sources['baseline'], snapshot())
        self.assertIsNone(comparison.sources['candidate'])
        self.assertFalse(comparison.frames.get())
        self.assertFalse(comparison.pairs)
        self.assertEqual(comparison.metrics_tree.heading('baseline_mm', 'text'), 'Baseline (mm)')
        self.assertEqual(comparison.metrics_tree.heading('candidate_mm', 'text'), 'Candidate (mm)')
        self.assertEqual(comparison.metrics_tree.heading('delta_mm', 'text'), 'Delta (mm)')
        self.assertFalse(self.errors)

    def test_actual_compare_action_opens_workspace_without_queue_changes(self):
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        button = next(w for w in widgets(self.inspector.window)
                      if w.winfo_class() == 'TButton' and w.cget('text') == 'Compare snapshots')
        before = set(self.root.winfo_children())
        button.invoke()
        opened = set(self.root.winfo_children())-before
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened.pop().title(), 'Geometry Comparison')
        self.assertEqual(self.app.store.page_jobs().total, 0)
        self.assertIsNone(self.app.connection_report)
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
