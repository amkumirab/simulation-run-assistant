import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, 'Native checks require Tk')
class SavedFieldUITests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Native checks require a display')
        self.addCleanup(self.close_root)
        from simulation_assistant.desktop import DesktopApp
        from simulation_assistant.field_sample_ui import FieldSamplesDialog
        from simulation_assistant.comsol_field_ui import SavedFieldDialog
        from simulation_assistant.field_samples import make_sensor_grid
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        self.app = DesktopApp(self.root, folder/'jobs.db', folder/'artifacts', folder/'profiles.json')
        self.owner = FieldSamplesDialog(self.root)
        self.owner.layout.set_sensors(make_sensor_grid(3, 3, .02, .08, (0., 0., 1.)))
        self.dialog = SavedFieldDialog(self.owner)

    def close_root(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.after_cancel(timer)
        self.root.destroy()

    def test_empty_state_and_missing_declarations_never_start_engine(self):
        with patch.object(self.dialog, 'submit') as submit:
            self.dialog.extract()
        submit.assert_not_called()
        self.assertIn('Confirm', self.dialog.status.get())
        self.assertEqual(self.app.store.page_jobs().total, 0)

    def test_explicit_state_added_and_source_path_edit_invalidates_inspection(self):
        from simulation_assistant.comsol_field_sampling import SavedState
        self.dialog.variables['model'].set(str(Path(self.temp.name)/'example.mph'))
        state = SavedState('dset1', 'sol1', 1, 2, 85000., 'freq=85000 Hz')
        self.dialog.accept_catalog(('a'*64, (state,)))
        self.dialog.state_combo.current(0)
        self.dialog.variables['scenario'].set('Offset 30 mm')
        self.dialog.add_state()
        self.assertEqual(self.dialog.scenarios[0].state.inner, 2)
        self.dialog.variables['model'].set('other.mph')
        self.assertIsNone(self.dialog.inspected)
        self.assertEqual(len(self.dialog.scenarios), 1)

    def test_stale_background_result_and_cancellation_are_discarded(self):
        snapshot = self.dialog.signature()
        self.owner.layout.variables['z_mm'].set('90')
        with patch.object(self.dialog, 'accept_catalog') as accept:
            self.dialog.complete('catalog', snapshot, ('a'*64, ()))
        accept.assert_not_called()
        self.assertIn('discarded', self.dialog.status.get())
        self.dialog.stop.set()
        with patch.object(self.dialog, 'accept_catalog') as accept:
            self.dialog.complete('catalog', self.dialog.signature(), ('a'*64, ()))
        accept.assert_not_called()

    def test_layout_entry_has_saved_comsol_action(self):
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        button = next(w for w in widgets(self.owner.window)
                      if w.winfo_class() == 'TButton' and w.cget('text') == 'Sample saved COMSOL fields')
        self.assertIsNotNone(button)

    def test_edit_then_revert_still_discards_pending_result(self):
        for variable in (self.dialog.variables['prefix'], self.owner.meta_vars['excitation']):
            with self.subTest(variable=str(variable)):
                snapshot = self.dialog.signature()
                previous = variable.get()
                variable.set('edited')
                variable.set(previous)
                self.dialog.complete('catalog', snapshot, ('a'*64, ()))
                self.assertIsNone(self.dialog.inspected)
                self.assertIn('discarded', self.dialog.status.get())

    def test_replaced_workspace_is_not_overwritten_by_pending_result(self):
        snapshot = self.dialog.signature()
        replacement = object()
        self.owner.data = replacement
        self.dialog.complete('catalog', snapshot, ('a'*64, ()))
        self.assertIs(self.owner.data, replacement)
        self.assertIsNone(self.dialog.inspected)
        self.assertIn('discarded', self.dialog.status.get())

    def test_repeated_inspect_does_not_clear_catalog_while_busy(self):
        catalog = (Path('example.mph'), 'a'*64, ())
        self.dialog.inspected = catalog
        self.dialog.busy = True
        with patch.object(self.dialog, 'submit') as submit:
            self.dialog.inspect()
        submit.assert_not_called()
        self.assertEqual(self.dialog.inspected, catalog)

    def test_completion_after_close_never_imports_data(self):
        snapshot = self.dialog.signature()
        self.dialog.close()
        self.dialog.complete('catalog', snapshot, ('a'*64, ()))
        self.assertIsNone(self.dialog.inspected)
        self.assertIsNone(self.owner.data)

    def test_successful_extraction_populates_comparison_and_edit_invalidates_it(self):
        from simulation_assistant.comsol_field_sampling import FieldExtraction
        from simulation_assistant.field_samples import Sensor
        from test_field_samples import dataset
        result = FieldExtraction(dataset(), (Sensor('S1', (0., 0., 0.), (1., 0., 0.)),), b'', {})
        self.dialog.complete('extract', self.dialog.signature(), result)
        self.assertIs(self.owner.data, result.data)
        self.assertEqual(self.owner.readings[0].projected_t, -2e-6+1e-6j)
        self.assertIs(self.dialog.result, result)
        self.dialog.variables['phase_reference'].set('New reference')
        self.assertIsNone(self.owner.data)
        self.assertEqual(self.owner.readings, ())
        self.assertIsNone(self.dialog.result)

    def test_engine_failure_preserves_previous_workspace_without_partial_import(self):
        from test_field_samples import dataset
        previous = dataset()
        self.owner.set_data(previous)
        self.dialog.complete('extract', self.dialog.signature(), RuntimeError('Unavailable field'))
        self.assertIs(self.owner.data, previous)
        self.assertIsNone(self.dialog.result)
        self.assertIn('no partial data', self.dialog.status.get())

    def test_export_rejects_dirty_layout_before_destination_prompt(self):
        from simulation_assistant.comsol_field_sampling import FieldExtraction
        from test_field_samples import dataset
        result = FieldExtraction(dataset(), self.owner.layout.sensors, b'', {})
        self.owner.data, self.dialog.result = result.data, result
        self.owner.layout.variables['z_mm'].set('90')
        with patch('simulation_assistant.comsol_field_ui.filedialog.askdirectory') as destination:
            self.dialog.export()
        destination.assert_not_called()
        self.assertIn('blocked', self.dialog.status.get())

    def test_closing_panel_releases_owner_variable_callbacks(self):
        variable = self.owner.meta_vars['excitation']
        before = len(variable.trace_info())
        self.dialog.close()
        self.assertEqual(len(variable.trace_info()), before-1)
        revision = self.dialog.revision
        variable.set('Changed after close')
        self.assertEqual(self.dialog.revision, revision)

    def test_background_catalog_returns_through_main_thread_poll(self):
        import threading
        from simulation_assistant.comsol_field_sampling import SavedState
        done = threading.Event()
        state = SavedState('dset1', 'sol1', 1, 1, 85000., 'freq=85000 Hz')
        original_put = self.dialog.events.put
        def put(value):
            original_put(value)
            done.set()
        with patch.object(self.dialog.events, 'put', side_effect=put):
            self.dialog.submit('catalog', lambda: ('a'*64, (state,)))
            self.assertTrue(done.wait(2))
            self.dialog.window.after_cancel(self.dialog.timer)
            self.dialog.poll()
        self.assertFalse(self.dialog.busy)
        self.assertEqual(self.dialog.inspected[2], (state,))
        self.assertEqual(self.dialog.state_combo.current(), -1)


if __name__ == '__main__':
    unittest.main()
