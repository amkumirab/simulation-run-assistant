import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from native_test_support import destroy_root
from native_test_support import collect_native_garbage as tearDownModule
from test_geometry_inspector import snapshot
try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, 'Native checks require Tk')
class GeometryComparisonDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Native checks require a display')
        self.addCleanup(destroy_root,self.root)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        from simulation_assistant.desktop import DesktopApp
        from simulation_assistant.geometry_comparison_ui import GeometryComparisonDialog
        self.app = DesktopApp(self.root,self.folder/'jobs.db',self.folder/'artifacts',self.folder/'profiles.json')
        self.dialog = GeometryComparisonDialog(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *e:self.errors.append(e)

    def add_pair(self,label='TX envelope',base='1',candidate='1'):
        for key,value in (('label',label),('baseline',base),('candidate',candidate)):
            self.dialog.form[key].set(value)
        return self.dialog.add_pair()

    def load_sources(self):
        self.dialog.set_snapshot('baseline',snapshot(),'Stored baseline')
        self.dialog.set_snapshot('candidate',snapshot(),'Stored candidate')

    def test_explicit_pair_frame_and_csv_workflow_without_queue_changes(self):
        self.load_sources()
        self.assertFalse(self.dialog.pairs)
        self.assertFalse(self.dialog.compare())
        self.assertTrue(self.add_pair())
        self.assertFalse(self.dialog.compare())
        self.dialog.frames.set(True)
        self.assertTrue(self.dialog.compare(),self.dialog.status.get())
        self.assertEqual(len(self.dialog.metrics_tree.get_children()),12)
        path=self.folder/'report.csv'
        with patch('simulation_assistant.geometry_comparison_ui.filedialog.asksaveasfilename',return_value=str(path)):
            self.assertTrue(self.dialog.export())
        with path.open(newline='') as stream:
            self.assertEqual(len(list(csv.DictReader(stream))),12)
        self.assertFalse(self.dialog.dirty())
        self.assertEqual(self.app.store.page_jobs().total,0)
        self.assertFalse(self.errors)

    def test_threshold_pair_and_frame_edits_invalidate_results(self):
        self.load_sources()
        self.add_pair()
        self.dialog.frames.set(True)
        self.assertTrue(self.dialog.compare())
        self.dialog.threshold.set('nan')
        self.assertIsNone(self.dialog.result)
        self.assertFalse(self.dialog.compare())
        self.dialog.threshold.set('.01')
        self.assertTrue(self.dialog.compare())
        self.dialog.form['label'].set('Pending pair')
        self.assertIsNone(self.dialog.result)
        self.assertFalse(self.dialog.compare())
        self.dialog.clear_form()
        self.assertTrue(self.dialog.compare())
        self.dialog.frames.set(False)
        self.assertIsNone(self.dialog.result)
        with patch('simulation_assistant.geometry_comparison_ui.filedialog.asksaveasfilename') as chooser:
            self.assertFalse(self.dialog.export())
            chooser.assert_not_called()

    def test_failed_load_and_declined_replacement_keep_work(self):
        self.load_sources()
        self.add_pair()
        invalid=self.folder/'bad.json'
        invalid.write_text('{}')
        with patch('simulation_assistant.geometry_comparison_ui.filedialog.askopenfilename',return_value=str(invalid)):
            self.dialog.load('baseline')
        self.assertEqual(len(self.dialog.pairs),1)
        with patch('simulation_assistant.geometry_comparison_ui.messagebox.askyesno',return_value=False):
            self.assertFalse(self.dialog.set_snapshot('candidate',snapshot(),'Replacement'))
            self.dialog.close()
        self.assertTrue(self.dialog.window.winfo_exists())
        self.assertEqual(len(self.dialog.pairs),1)
        with patch('simulation_assistant.geometry_comparison_ui.messagebox.askyesno',return_value=True):
            self.assertTrue(self.dialog.set_snapshot('candidate',snapshot(),'Replacement'))
        self.assertFalse(self.dialog.pairs)
        self.assertFalse(self.dialog.frames.get())

    def test_duplicate_pair_rejected_and_remove_clears_computed_output(self):
        self.load_sources()
        self.assertTrue(self.add_pair())
        self.assertFalse(self.add_pair('Other part','1','2'))
        self.assertEqual(len(self.dialog.pairs),1)
        self.dialog.clear_form()
        self.dialog.frames.set(True)
        self.dialog.compare()
        self.dialog.pairs_tree.selection_set('0')
        self.dialog.remove_pair()
        self.assertFalse(self.dialog.pairs)
        self.assertIsNone(self.dialog.result)

    def test_enter_opens_selected_pair_and_moves_keyboard_focus(self):
        self.load_sources()
        self.add_pair()
        self.dialog.frames.set(True)
        self.dialog.compare()
        self.dialog.tabs.select(0)
        self.root.update()
        self.dialog.pairs_tree.selection_set('0')
        self.dialog.pairs_tree.focus_force()
        self.dialog.pairs_tree.event_generate('<Return>')
        self.root.update()
        self.assertEqual(self.root.focus_get(),self.dialog.result_box)
        self.assertFalse(self.errors)

    def test_failed_save_keeps_work_dirty_and_cancelled_dialog_does_not_export(self):
        self.load_sources()
        self.add_pair()
        self.dialog.frames.set(True)
        self.dialog.compare()
        path=self.folder/'locked.csv'
        with patch('simulation_assistant.geometry_comparison_ui.filedialog.asksaveasfilename',return_value=str(path)), \
                patch('simulation_assistant.geometry_comparison_ui.export_comparison_csv',side_effect=OSError('locked')):
            self.assertFalse(self.dialog.export())
        self.assertTrue(self.dialog.dirty())
        self.assertFalse(path.exists())
        with patch('simulation_assistant.geometry_comparison_ui.filedialog.asksaveasfilename',return_value=''):
            self.assertFalse(self.dialog.export())
        self.assertTrue(self.dialog.dirty())

    def test_minimum_normal_sizes_and_draft_close_protection(self):
        self.load_sources()
        self.dialog.form['label'].set('Unapplied proposal')
        with patch('simulation_assistant.geometry_comparison_ui.messagebox.askyesno',return_value=False):
            self.dialog.close()
        self.assertTrue(self.dialog.window.winfo_exists())
        for size in ('1000x760','1240x850'):
            self.dialog.window.geometry(size)
            self.root.update()
            body=self.dialog.window.winfo_children()[0]
            for child in body.winfo_children():
                self.assertLessEqual(child.winfo_x()+child.winfo_width(),body.winfo_width())
                self.assertLessEqual(child.winfo_y()+child.winfo_height(),body.winfo_height())
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
