import tempfile
import unittest
from pathlib import Path

from native_test_support import destroy_root
from native_test_support import collect_native_garbage as tearDownModule
from test_geometry_inspector import snapshot
from simulation_assistant.field_samples import Sensor
try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, 'Native checks require Tk')
class SensorPlacementIntegrationTests(unittest.TestCase):
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
        self.app = DesktopApp(self.root, folder/'jobs.db', folder/'artifacts', folder/'profiles.json')

    def test_geometry_action_prefills_snapshot_only_and_survives_inspector_close(self):
        from simulation_assistant.geometry_ui import GeometryDialog
        owner = GeometryDialog(self.root)
        owner.set_snapshot(snapshot(), 'Stored geometry')
        preview = owner.open_sensor_placement()
        owner.close()
        self.assertTrue(preview.window.winfo_exists())
        self.assertEqual(preview.snapshot, snapshot())
        self.assertEqual(preview.sensors, ())
        self.assertFalse(preview.domains())
        self.assertFalse(preview.frames.get())
        self.assertEqual(self.app.store.page_jobs().total, 0)

    def test_field_action_copies_only_applied_sensor_positions_and_survives_editor_close(self):
        from simulation_assistant.field_sample_ui import FieldSamplesDialog
        owner = FieldSamplesDialog(self.root)
        sensors = (Sensor('S1', (0., 0., .08), (0., 0., 1.)),)
        owner.layout.set_sensors(sensors)
        preview = owner.open_sensor_placement()
        self.assertEqual(preview.sensors, sensors)
        self.assertIsNone(preview.snapshot)
        self.assertFalse(preview.frames.get())
        owner.layout.variables['z_mm'].set('90')
        self.assertIsNone(owner.open_sensor_placement())
        self.assertIn('Apply', owner.summary.get())
        owner.window.destroy()
        self.assertTrue(preview.window.winfo_exists())
        self.assertEqual(preview.sensors[0].position_m[2], .08)

    def test_actual_native_toolbar_actions_are_connected(self):
        from simulation_assistant.geometry_ui import GeometryDialog
        from simulation_assistant.field_sample_ui import FieldSamplesDialog
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        for owner in (GeometryDialog(self.root), FieldSamplesDialog(self.root)):
            if hasattr(owner, 'layout'):
                owner.layout.set_sensors((Sensor('S1', (0., 0., 0.), (0., 0., 1.)),))
            button = next(w for w in widgets(owner.window) if w.winfo_class() == 'TButton'
                          and w.cget('text') == 'Sensor placement')
            before = set(self.root.winfo_children())
            button.invoke()
            opened = set(self.root.winfo_children())-before
            self.assertEqual(len(opened), 1)
            self.assertEqual(opened.pop().title(), 'Sensor Placement Preview')
        self.assertIsNone(self.app.connection_report)


if __name__ == '__main__':
    unittest.main()
