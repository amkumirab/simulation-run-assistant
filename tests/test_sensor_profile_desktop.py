import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from native_test_support import destroy_root
from native_test_support import collect_native_garbage as tearDownModule
from test_sensor_profiles import hypothetical_profile
from simulation_assistant.geometry_files import load_snapshot
from simulation_assistant.saved_field_bundles import load_saved_field_bundle
from simulation_assistant.sensor_profile_files import load_sensor_profile
try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, 'Native checks require Tk')
class SensorProfileDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Native checks require a display')
        self.addCleanup(destroy_root, self.root)
        from simulation_assistant.sensor_placement_ui import SensorPlacementDialog
        self.placement = SensorPlacementDialog(self.root)
        self.fields = self.placement.field_overlay
        self.dialog = self.fields.open_sensor_profiles()
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def inputs(self):
        fixture = Path(__file__).resolve().parents[1]/'examples/saved_field_wpt'
        self.placement.set_snapshot(load_snapshot(fixture/'geometry-position-2.json'))
        self.fields.set_bundle(load_saved_field_bundle(fixture))
        self.fields.use_layout()
        self.placement.domains_tree.selection_set('6', '7')
        self.root.update()
        self.fields.current.set('Position 2')
        self.fields.reference.set('Position 1')
        self.placement.frames.set(True)
        self.fields.state_matches.set(True)
        self.assertTrue(self.fields.analyze())
        self.dialog.set_profile(hypothetical_profile())
        self.dialog.context['sampled_field'].set('charging-coil-ac')
        for axis in 'xyz':
            self.dialog.context['dc_'+axis].set('0')
        self.dialog.confirmed.set(True)

    def test_profile_save_load_works_without_fields_or_a_physical_sensor(self):
        self.assertFalse(self.dialog.evaluate())
        path = Path(self.temp.name)/'profile.json'
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(path)):
            self.assertTrue(self.dialog.save())
        self.assertIsNone(load_sensor_profile(path).frequency)
        self.assertFalse(self.dialog.dirty())
        self.dialog.form['name'].set('Edited design')
        with patch('tkinter.filedialog.askopenfilename', return_value=str(path)), patch('tkinter.messagebox.askyesno', return_value=True):
            self.assertTrue(self.dialog.load())
        self.assertIsNone(self.dialog.result)
        self.assertFalse(self.dialog.confirmed.get())
        self.assertFalse(self.errors)

    def test_real_fields_hypothetical_profile_and_report_workflow(self):
        self.inputs()
        self.assertTrue(self.dialog.evaluate(), self.dialog.status.get())
        self.root.update()
        self.assertEqual(len(self.dialog.tree.get_children()), 18)
        self.assertIn('ASSUMPTION', self.dialog.scope.get())
        self.dialog.tree.selection_set(self.dialog.tree.get_children()[8])
        self.root.update()
        self.assertIn('axis B', self.dialog.detail.get('1.0', 'end'))
        for size in ('1040x780', '1240x900'):
            self.dialog.window.geometry(size)
            for tab in (0, 1):
                self.dialog.tabs.select(tab)
                self.root.update()
                body = self.dialog.window.winfo_children()[0]
                self.assertTrue(all(w.winfo_y()+w.winfo_height() <= body.winfo_height() for w in body.winfo_children()))
                def check_wrap(widget):
                    if widget.winfo_class() == 'TLabel' and widget.winfo_ismapped():
                        wrap = int(widget.cget('wraplength') or 0)
                        if wrap:
                            self.assertLessEqual(wrap, widget.winfo_width(), widget.cget('text'))
                    for child in widget.winfo_children():
                        check_wrap(child)
                check_wrap(body)
        path = Path(self.temp.name)/'report.json'
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(path)):
            self.assertTrue(self.dialog.export())
        self.assertIn('wpt.sensor-limit-report.v1', path.read_text())
        self.assertFalse(self.errors)

    def test_profile_context_and_overlay_changes_clear_result_and_confirmation(self):
        self.inputs()
        self.assertTrue(self.dialog.evaluate())
        self.dialog.form['notes'].set('New assumption')
        self.assertIsNone(self.dialog.result)
        self.assertFalse(self.dialog.confirmed.get())
        self.dialog.confirmed.set(True)
        self.assertTrue(self.dialog.evaluate())
        self.dialog.context['dc_z'].set('10')
        self.assertIsNone(self.dialog.result)
        self.dialog.confirmed.set(True)
        self.assertTrue(self.dialog.evaluate())
        self.fields.current.set('Position 1')
        self.assertIsNone(self.dialog.result)
        self.assertFalse(self.dialog.confirmed.get())
        with patch('tkinter.filedialog.asksaveasfilename') as chooser:
            self.assertFalse(self.dialog.export())
            chooser.assert_not_called()
        self.assertFalse(self.errors)

    def test_failed_load_export_and_cancel_preserve_current_accepted_work(self):
        self.inputs()
        self.assertTrue(self.dialog.evaluate())
        result = self.dialog.result
        bad = Path(self.temp.name)/'bad.json'
        bad.write_text('{}')
        for path in ('', str(bad)):
            with patch('tkinter.filedialog.askopenfilename', return_value=path):
                self.assertFalse(self.dialog.load())
            self.assertEqual(self.dialog.result, result)
        for path in ('', str(Path(self.temp.name)/'missing'/'report.json')):
            with patch('tkinter.filedialog.asksaveasfilename', return_value=path):
                self.assertFalse(self.dialog.export())
            self.assertEqual(self.dialog.result, result)
        self.assertFalse(self.errors)

    def test_dirty_profiles_are_protected_on_new_close_and_parent_close(self):
        self.dialog.form['name'].set('Unsaved design')
        with patch('tkinter.messagebox.askyesno', return_value=False):
            self.assertFalse(self.dialog.new())
            self.assertFalse(self.dialog.close())
            self.assertFalse(self.placement.close())
        self.assertFalse(self.dialog.closed)
        with patch('tkinter.messagebox.askyesno', return_value=True):
            self.assertTrue(self.placement.close())
        self.assertTrue(self.dialog.closed)
        self.assertFalse(self.errors)

    def test_empty_profile_and_unknown_bias_show_insufficient_not_zero(self):
        self.inputs()
        for axis in 'xyz':
            self.dialog.context['dc_'+axis].set('')
        self.assertTrue(self.dialog.evaluate())
        self.assertIsNone(self.dialog.result.rows[0].minimum_t)
        self.assertEqual(self.dialog.result.rows[0].status, 'insufficient information')
        self.assertFalse(self.errors)

    def test_edits_during_file_dialog_cannot_export_or_save_stale_inputs(self):
        self.inputs()
        self.assertTrue(self.dialog.evaluate())
        path = Path(self.temp.name)/'kept.json'
        path.write_bytes(b'kept')
        def changed_source(**_options):
            self.fields.current.set('Position 1')
            return str(path)
        with patch('tkinter.filedialog.asksaveasfilename', side_effect=changed_source):
            self.assertFalse(self.dialog.export())
        self.assertEqual(path.read_bytes(), b'kept')
        def changed_profile(**_options):
            self.dialog.form['name'].set('Changed while choosing a destination')
            return str(path)
        with patch('tkinter.filedialog.asksaveasfilename', side_effect=changed_profile):
            self.assertFalse(self.dialog.save())
        self.assertEqual(path.read_bytes(), b'kept')
        self.assertTrue(self.dialog.dirty())
        self.assertFalse(self.errors)

    def test_partial_ranges_and_bias_are_not_silently_filled(self):
        self.dialog.spec_vars['field']['low'].set('-10')
        with patch('tkinter.filedialog.asksaveasfilename') as chooser:
            self.assertFalse(self.dialog.save())
            chooser.assert_not_called()
        self.inputs()
        self.dialog.context['dc_z'].set('')
        self.assertFalse(self.dialog.evaluate())
        self.assertIn('all three', self.dialog.status.get())
        self.assertIsNone(self.dialog.result)
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
