import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from native_test_support import destroy_root
from native_test_support import collect_native_garbage as tearDownModule
from test_geometry_inspector import snapshot
from simulation_assistant.field_samples import Sensor
from simulation_assistant.geometry_files import save_snapshot
try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, 'Native checks require Tk')
class SensorPlacementDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Native checks require a display')
        self.addCleanup(destroy_root, self.root)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        from simulation_assistant.desktop import DesktopApp
        from simulation_assistant.sensor_placement_ui import SensorPlacementDialog
        self.app = DesktopApp(self.root, self.folder/'jobs.db', self.folder/'artifacts', self.folder/'profiles.json')
        self.dialog = SensorPlacementDialog(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *e: self.errors.append(e)
        self.sensors = (Sensor('S1', (0., 0., .08), (0., 0., 1.)),
                        Sensor('S2', (.02, 0., .08), (1., 0., 0.)))

    def inputs(self):
        self.dialog.set_snapshot(snapshot())
        self.dialog.set_layout(self.sensors, 'Illustrative layout')
        self.dialog.domains_tree.selection_set('1')
        self.root.update()

    def render(self):
        self.dialog.frames.set(True)
        self.assertTrue(self.dialog.preview(), self.dialog.status.get())
        self.root.update()

    def test_explicit_selection_frame_and_export_workflow(self):
        self.assertFalse(self.dialog.preview())
        self.dialog.set_snapshot(snapshot())
        self.dialog.set_layout(self.sensors, 'Illustrative layout')
        self.dialog.frames.set(True)
        self.assertFalse(self.dialog.preview())
        self.dialog.domains_tree.selection_set('1')
        self.root.update()
        self.assertFalse(self.dialog.preview())
        self.render()
        self.assertEqual(set(self.dialog.views), {'XY', 'XZ'})
        self.assertEqual(self.dialog.views['XY'].sensors[0].axis_uv, (0., 0.))
        path = self.folder/'placement.svg'
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(path)):
            self.assertTrue(self.dialog.export())
        self.assertIn('Sensor Placement Preview', path.read_text())
        self.assertEqual(self.app.store.page_jobs().total, 0)
        self.assertIsNone(self.app.connection_report)
        self.assertFalse(self.errors)

    def test_source_domain_and_frame_changes_clear_accepted_export_state(self):
        self.inputs()
        self.render()
        self.dialog.domains_tree.selection_set('2')
        self.root.update()
        self.assertFalse(self.dialog.frames.get())
        self.assertFalse(self.dialog.views)
        with patch('tkinter.filedialog.asksaveasfilename') as chooser:
            self.assertFalse(self.dialog.export())
            chooser.assert_not_called()
        self.render()
        self.dialog.set_layout(self.sensors, 'New source')
        self.assertFalse(self.dialog.frames.get())
        self.assertFalse(self.dialog.views)
        self.render()
        self.dialog.set_snapshot(snapshot())
        self.assertFalse(self.dialog.frames.get())
        self.assertFalse(self.dialog.views)

    def test_failed_load_preserves_current_drawing_and_approval(self):
        self.inputs()
        self.render()
        original = self.dialog.signature()
        broken = self.folder/'bad.json'
        broken.write_text('{}')
        with patch('tkinter.filedialog.askopenfilename', return_value=str(broken)):
            self.assertFalse(self.dialog.load_geometry())
            self.assertFalse(self.dialog.load_layout())
        self.assertEqual(self.dialog.signature(), original)
        self.assertTrue(self.dialog.views)
        self.assertTrue(self.dialog.frames.get())

    def test_existing_workspace_imports_layout_only_and_clears_approval(self):
        self.inputs()
        self.render()
        path = Path(__file__).resolve().parents[1]/'examples/saved_field_wpt/workspace.json'
        with patch('tkinter.filedialog.askopenfilename', return_value=str(path)):
            self.assertTrue(self.dialog.load_layout())
        self.assertEqual(len(self.dialog.sensors), 9)
        self.assertFalse(self.dialog.frames.get())
        self.assertFalse(self.dialog.views)
        self.assertIn('layout only', self.dialog.layout_label)
        source = save_snapshot(self.folder/'snapshot.json', snapshot())
        with patch('tkinter.filedialog.askopenfilename', return_value=str(source)):
            self.assertTrue(self.dialog.load_geometry())
        self.assertFalse(self.dialog.domains_tree.selection())

    def test_sensor_table_and_plot_selection_highlight_both_views(self):
        self.inputs()
        self.render()
        self.dialog.sensor_tree.selection_set('S2')
        self.dialog.sensor_tree.focus_force()
        self.dialog.sensor_tree.event_generate('<Return>')
        self.root.update()
        self.assertEqual(self.dialog.selected_sensor, 'S2')
        self.assertIn('S2', self.dialog.details.get())
        x, y = self.dialog.views['XZ'].sensors[0].point
        self.dialog.canvases['XZ'].event_generate('<Button-1>', x=round(x), y=round(y))
        self.root.update()
        self.assertEqual(self.dialog.sensor_tree.selection(), ('S1',))
        self.assertEqual(self.dialog.selected_sensor, 'S1')
        self.assertTrue(self.dialog.frames.get())
        self.assertFalse(self.errors)

    def test_cancelled_failed_exports_keep_preview_and_minimum_layout_is_usable(self):
        self.inputs()
        self.render()
        with patch('tkinter.filedialog.asksaveasfilename', return_value=''):
            self.assertFalse(self.dialog.export())
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(self.folder/'locked.svg')), \
                patch('simulation_assistant.sensor_placement_ui.save_placement_svg', side_effect=OSError('locked')):
            self.assertFalse(self.dialog.export())
        self.assertTrue(self.dialog.views)
        for size in ('1000x760', '1240x850'):
            self.dialog.window.geometry(size)
            self.root.update()
            body = self.dialog.window.winfo_children()[0]
            for child in body.winfo_children():
                self.assertLessEqual(child.winfo_x()+child.winfo_width(), body.winfo_width())
                self.assertLessEqual(child.winfo_y()+child.winfo_height(), body.winfo_height())
            for plane, canvas in self.dialog.canvases.items():
                self.assertGreaterEqual(canvas.winfo_width(), 400)
                self.assertGreaterEqual(canvas.winfo_height(), 300)
                self.assertEqual(self.dialog.views[plane].width, canvas.winfo_width())
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
