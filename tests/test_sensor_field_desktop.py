"""Real Tk workflow with synthetic geometry bindings, no COMSOL solve."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from native_test_support import destroy_root
from native_test_support import collect_native_garbage as tearDownModule
from test_geometry_inspector import snapshot
from simulation_assistant.field_samples import Sensor
from simulation_assistant.saved_field_bundles import load_saved_field_bundle
try:
    import tkinter as tk
except ImportError:
    tk = None

FIXTURE = Path(__file__).resolve().parents[1]/'examples/saved_field_wpt'


@unittest.skipIf(tk is None, 'Native checks require Tk')
class SensorFieldDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Native checks require a display')
        self.addCleanup(destroy_root, self.root)
        from simulation_assistant.sensor_placement_ui import SensorPlacementDialog
        self.dialog = SensorPlacementDialog(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.bundle = load_saved_field_bundle(FIXTURE)
        self.fields = self.dialog.field_overlay
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def inputs(self):
        self.dialog.set_snapshot(replace(snapshot(), source_sha256=self.bundle.sources[0].model_sha256))
        with patch('tkinter.filedialog.askdirectory', return_value=str(FIXTURE)):
            self.assertTrue(self.fields.load())
        self.assertTrue(self.fields.use_layout())
        self.dialog.domains_tree.selection_set('1')
        self.root.update()
        self.dialog.frames.set(True)
        self.fields.state_matches.set(True)

    def test_workflow_selection_resize_components_and_export(self):
        self.inputs()
        self.assertTrue(self.fields.analyze(), self.dialog.status.get())
        self.root.update()
        self.assertTrue(self.fields.result)
        self.assertEqual(len(self.fields.tree.get_children()), 9)
        self.fields.tree.selection_set('S5')
        self.root.update()
        self.assertEqual(self.dialog.selected_sensor, 'S5')
        self.assertIn('Bz (T)', self.fields.detail.get('1.0', 'end'))
        self.dialog.window.geometry('1000x760')
        self.root.update()
        for canvas in self.dialog.canvases.values():
            self.assertTrue(canvas.find_withtag('field-overlay'))
        path = Path(self.temp.name)/'field.svg'
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(path)):
            self.assertTrue(self.fields.export())
        self.assertIn('wpt.sensor-field-overlay.v1', path.read_text())
        self.assertFalse(self.errors)

    def test_changes_clear_results_declarations_and_export_without_resurrection(self):
        self.inputs()
        self.assertTrue(self.fields.analyze())
        self.fields.current.set('Position 2')
        self.assertIsNone(self.fields.result)
        self.assertFalse(self.fields.state_matches.get())
        self.fields.state_matches.set(True)
        self.assertFalse(self.fields.analyze())  # Different current model identity.
        self.fields.current.set('Position 1')
        self.fields.state_matches.set(True)
        self.assertTrue(self.fields.analyze())
        self.dialog.frames.set(False)
        self.assertIsNone(self.fields.result)
        self.assertFalse(self.fields.state_matches.get())
        self.dialog.redraw()
        with patch('tkinter.filedialog.asksaveasfilename') as chooser:
            self.assertFalse(self.fields.export())
            chooser.assert_not_called()
        self.assertFalse(self.errors)

    def test_failed_or_cancelled_bundle_load_preserves_accepted_work(self):
        self.inputs()
        self.assertTrue(self.fields.analyze())
        accepted = self.fields.result
        for path in ('', self.temp.name):
            with patch('tkinter.filedialog.askdirectory', return_value=path):
                self.assertFalse(self.fields.load())
            self.assertEqual(self.fields.result, accepted)
            self.assertTrue(self.fields.state_matches.get())
        self.assertFalse(self.errors)

    def test_loading_does_not_replace_existing_layout_or_accept_unknown_geometry(self):
        sensors = (Sensor('Custom', (0., 0., 0.), (1., 0., 0.)),)
        self.dialog.set_layout(sensors, 'Custom copy')
        with patch('tkinter.filedialog.askdirectory', return_value=str(FIXTURE)):
            self.assertTrue(self.fields.load())
        self.assertEqual(self.dialog.sensors, sensors)
        self.assertFalse(self.fields.state_matches.get())
        self.assertFalse(self.fields.analyze())
        self.assertTrue(self.fields.use_layout())
        self.assertEqual(self.dialog.sensors, self.bundle.sensors)
        self.assertFalse(self.errors)

    def test_geometry_layout_domain_and_geometry_only_preview_clear_field_approval(self):
        for change in ('geometry', 'layout', 'domain', 'preview'):
            with self.subTest(change=change):
                self.inputs()
                self.assertTrue(self.fields.analyze())
                if change == 'geometry':
                    self.dialog.set_snapshot(self.dialog.snapshot)
                elif change == 'layout':
                    self.dialog.set_layout(self.dialog.sensors, 'New copied layout')
                elif change == 'domain':
                    self.dialog.domains_tree.selection_set('2')
                    self.root.update()
                else:
                    self.assertTrue(self.dialog.preview())
                self.assertIsNone(self.fields.valid_result())
                self.assertFalse(self.fields.state_matches.get())
                self.assertFalse(self.fields.tree.get_children())
        self.assertFalse(self.errors)

    def test_unavailable_rows_and_failed_exports_remain_honest(self):
        self.inputs()
        self.dialog.set_layout((Sensor('Missing', (0., 0., 0.), (0., 0., 1.)),), 'Unsampled layout')
        self.dialog.frames.set(True)
        self.fields.state_matches.set(True)
        self.assertTrue(self.fields.analyze())
        self.root.update()
        values = self.fields.tree.item('Missing', 'values')
        self.assertIn('missing point', values)
        self.assertIn('unavailable', values)
        self.assertNotIn('Bz (T)', self.fields.detail.get('1.0', 'end'))
        result = self.fields.result
        with patch('tkinter.filedialog.asksaveasfilename', return_value=''):
            self.assertFalse(self.fields.export())
        target = Path(self.temp.name)/'missing'/'export.svg'
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(target)):
            self.assertFalse(self.fields.export())
        self.assertEqual(self.fields.result, result)
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
