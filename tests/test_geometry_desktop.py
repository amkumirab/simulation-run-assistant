import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    import tkinter as tk
except ImportError:
    tk = None
from test_geometry_inspector import snapshot
from simulation_assistant.geometry_files import load_snapshot
from native_test_support import destroy_root
from native_test_support import collect_native_garbage as tearDownModule


@unittest.skipIf(tk is None, 'Native checks require Tk')
class GeometryDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Native checks require a display')
        self.addCleanup(self.cleanup)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        from simulation_assistant.desktop import DesktopApp
        self.app = DesktopApp(self.root, self.folder/'jobs.db', self.folder/'artifacts', self.folder/'profiles.json')
        from simulation_assistant.geometry_ui import GeometryDialog
        self.dialog = GeometryDialog(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.root.update_idletasks()

    def cleanup(self):
        destroy_root(self.root)

    def test_empty_selection_cannot_export_and_draft_is_proposed_unsaved(self):
        dialog = self.dialog
        dialog.set_snapshot(snapshot(), 'Stored test snapshot')
        self.assertFalse(dialog.selected_domains())
        self.assertIsNone(dialog.new_brief())
        dialog.tree.selection_set('1', '2')
        brief = dialog.new_brief()
        self.assertEqual(len(brief.entries), 12)
        self.assertTrue(brief.dirty())
        self.assertTrue(all(entry.status == 'proposed' for entry in brief.entries))
        self.assertEqual(brief.header['model_sha256'].get(), 'a'*64)
        self.assertEqual(self.app.store.page_jobs().total, 0)
        self.assertFalse(self.errors)

    def test_change_inputs_invalidates_and_late_results_are_rejected(self):
        dialog = self.dialog
        revision = dialog.revision
        dialog.set_snapshot(snapshot(), 'Stored test snapshot')
        dialog.model.set('different.mph')
        self.assertIsNone(dialog.data)
        dialog.deliver(revision, snapshot(), '')
        self.assertIsNone(dialog.data)
        dialog.cancel()
        self.assertTrue(dialog.stop.is_set())

    def test_declaration_required_and_separation_not_called_clearance(self):
        dialog = self.dialog
        dialog.set_snapshot(snapshot(), 'Stored test snapshot')
        dialog.lower.set('1')
        dialog.upper.set('2')
        dialog.update_separation()
        self.assertIn('Unavailable', dialog.separation.get())
        dialog.parallel.set(True)
        dialog.update_separation()
        self.assertIn('150.000 mm', dialog.separation.get())
        self.assertIn('not clearance', dialog.separation.get())
        dialog.lower.set('2')
        dialog.update_separation()
        self.assertIn('Unavailable', dialog.separation.get())

    def test_save_load_and_resize_have_no_callback_errors(self):
        dialog = self.dialog
        dialog.set_snapshot(snapshot(), 'Stored test snapshot')
        path = self.folder/'geometry.json'
        with patch('simulation_assistant.geometry_ui.filedialog.asksaveasfilename', return_value=str(path)):
            dialog.save()
        self.assertEqual(load_snapshot(path), snapshot())
        dialog.model.set('new.mph')
        with patch('simulation_assistant.geometry_ui.filedialog.askopenfilename', return_value=str(path)):
            dialog.load()
        self.assertEqual(dialog.data, snapshot())
        dialog.tree.selection_set('1', '2')
        dialog.selected()
        dialog.window.geometry('1000x760')
        self.root.update()
        self.assertTrue(dialog.canvas.find_all())
        self.assertFalse(self.errors)

    def test_toolbar_and_close_cancel_pending_work(self):
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        button = next(w for w in widgets(self.root) if w.winfo_class() == 'TButton' and w.cget('text') == 'Geometry inspector')
        button.invoke()
        self.dialog.close()
        self.assertTrue(self.dialog.stop.is_set())
        self.assertTrue(self.dialog.closed)

    def test_background_result_is_accepted_only_for_unchanged_inputs(self):
        dialog = self.dialog
        started, release = threading.Event(), threading.Event()
        main_thread = threading.get_ident()
        def engine(*_args, **kwargs):
            self.assertNotEqual(threading.get_ident(), main_thread)
            started.set()
            if not release.wait(3):
                raise RuntimeError('test worker was not released')
            return snapshot()
        with patch('simulation_assistant.geometry_ui.inspect_geometry', side_effect=engine):
            dialog.inspect()
            self.assertTrue(started.wait(2))
            dialog.model.set('changed.mph')
            release.set()
            dialog.worker.join(3)
            self.assertFalse(dialog.worker.is_alive())
            dialog.deliver(*dialog.events.get_nowait())
            self.assertIsNone(dialog.data)
        with patch('simulation_assistant.geometry_ui.inspect_geometry', return_value=snapshot()):
            dialog.inspect()
            dialog.worker.join(3)
            dialog.deliver(*dialog.events.get_nowait())
            self.assertEqual(dialog.data, snapshot())
        self.assertFalse(self.errors)

    def test_invalid_load_and_empty_csv_preserve_snapshot(self):
        dialog = self.dialog
        dialog.set_snapshot(snapshot(), 'Stored test snapshot')
        broken = self.folder/'broken.json'
        broken.write_text('{}')
        with patch('simulation_assistant.geometry_ui.filedialog.askopenfilename', return_value=str(broken)):
            dialog.load()
        self.assertEqual(dialog.data, snapshot())
        with patch('simulation_assistant.geometry_ui.filedialog.asksaveasfilename') as chooser:
            dialog.export()
            chooser.assert_not_called()

    def test_new_unsaved_brief_survives_inspector_close(self):
        self.dialog.set_snapshot(snapshot(), 'Stored test snapshot')
        self.dialog.tree.selection_set('1')
        brief = self.dialog.new_brief()
        self.dialog.close()
        self.assertTrue(brief.window.winfo_exists())
        self.assertTrue(brief.dirty())


if __name__ == '__main__':
    unittest.main()
