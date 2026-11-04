import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
try:
    import tkinter as tk
except ImportError:
    tk = None

from simulation_assistant.model_briefs import load_model_brief
from native_test_support import destroy_root
from native_test_support import collect_native_garbage as tearDownModule


@unittest.skipIf(tk is None, 'Native checks require Tk')
class ModelBriefDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Native checks require a display')
        self.addCleanup(self.close_root)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        from simulation_assistant.desktop import DesktopApp
        self.app = DesktopApp(self.root, self.folder/'jobs.db', self.folder/'artifacts', self.folder/'profiles.json')
        from simulation_assistant.model_brief_ui import ModelBriefDialog
        self.dialog = ModelBriefDialog(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.path = self.folder/'brief.json'

    def close_root(self):
        destroy_root(self.root)

    def add_entry(self, **changes):
        values = dict(section='Geometry', name='RX count', value='3', unit='1',
                      status='proposed', source='Illustrative proposal', reviewed_on='')
        values.update(changes)
        for key, value in values.items():
            self.dialog.fields[key].set(value)
        self.assertTrue(self.dialog.apply_entry(), self.dialog.status.get())

    def save(self):
        self.dialog.header['name'].set('Illustrative square layout')
        with patch('simulation_assistant.model_brief_ui.filedialog.asksaveasfilename', return_value=str(self.path)):
            return self.dialog.save()

    def test_edit_save_load_and_remove_without_queue_or_connection(self):
        self.add_entry()
        self.assertTrue(self.save(), self.dialog.status.get())
        self.assertFalse(self.dialog.dirty())
        self.assertEqual(load_model_brief(self.path).entries[0].value, '3')
        self.dialog.fields['value'].set('2')
        self.assertTrue(self.dialog.apply_entry())
        with patch('simulation_assistant.model_brief_ui.messagebox.askyesno', return_value=True), \
                patch('simulation_assistant.model_brief_ui.filedialog.askopenfilename', return_value=str(self.path)):
            self.dialog.load()
        self.assertEqual(self.dialog.entries[0].value, '3')
        self.dialog.tree.selection_set('0')
        self.dialog.select_entry()
        self.dialog.remove_entry()
        self.assertFalse(self.dialog.entries)
        self.assertEqual(self.app.store.page_jobs().total, 0)
        self.assertIsNone(self.app.connection_report)
        self.assertFalse(self.errors)

    def test_pending_entry_edits_block_save_remove_and_selection_loss(self):
        self.add_entry()
        self.dialog.new_entry()
        self.add_entry(name='TX count', value='1')
        self.dialog.fields['value'].set('2')
        self.assertFalse(self.save())
        self.assertFalse(self.path.exists())
        self.dialog.tree.selection_set('0')
        self.dialog.select_entry()
        self.assertEqual(self.dialog.selected, 1)
        self.assertEqual(self.dialog.fields['value'].get(), '2')
        self.dialog.remove_entry()
        self.assertEqual(len(self.dialog.entries), 2)

    def test_confirmation_and_unknown_validation_are_visible(self):
        self.add_entry()
        before = self.dialog.entries
        self.dialog.fields['status'].set('confirmed')
        self.assertFalse(self.dialog.apply_entry())
        self.assertIn('date', self.dialog.status.get())
        self.assertEqual(self.dialog.entries, before)
        self.dialog.fields['reviewed_on'].set('2026-11-02')
        self.assertTrue(self.dialog.apply_entry())
        self.dialog.new_entry()
        self.add_entry(name='Coil dimensions', value='', unit='mm', status='unknown', source='')
        self.assertEqual(self.dialog.entries[-1].value, '')

    def test_invalid_load_and_cancelled_file_dialogs_preserve_work(self):
        self.add_entry()
        self.assertTrue(self.save())
        before = self.dialog.entries
        broken = self.folder/'broken.json'
        broken.write_text('{}')
        with patch('simulation_assistant.model_brief_ui.filedialog.askopenfilename', return_value=str(broken)):
            self.dialog.load()
        self.assertEqual(self.dialog.entries, before)
        self.assertFalse(self.dialog.dirty())
        with patch('simulation_assistant.model_brief_ui.filedialog.asksaveasfilename', return_value=''):
            self.assertFalse(self.dialog.save())

    def test_new_and_close_require_discard_permission_for_unsaved_edits(self):
        self.dialog.fields['name'].set('Unapplied note')
        with patch('simulation_assistant.model_brief_ui.messagebox.askyesno', return_value=False):
            self.dialog.new_brief()
            self.dialog.close()
            self.dialog.new_entry()
        self.assertTrue(self.dialog.window.winfo_exists())
        self.assertEqual(self.dialog.fields['name'].get(), 'Unapplied note')
        with patch('simulation_assistant.model_brief_ui.messagebox.askyesno', return_value=True):
            self.dialog.new_brief()
        self.assertFalse(self.dialog.dirty())
        self.assertFalse(self.dialog.entries)

    def test_failed_save_preserves_dirty_state(self):
        self.add_entry()
        with patch('simulation_assistant.model_brief_ui.save_model_brief', side_effect=OSError('locked')):
            self.assertFalse(self.save())
        self.assertTrue(self.dialog.dirty())
        self.assertIn('locked', self.dialog.status.get())

    def test_toolbar_opens_native_editor_and_has_no_side_effects(self):
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        button = next(w for w in widgets(self.root)
                      if w.winfo_class() == 'TButton' and w.cget('text') == 'Model brief')
        before = set(self.root.winfo_children())
        button.invoke()
        opened = set(self.root.winfo_children())-before
        self.assertEqual(len(opened), 1)
        window = opened.pop()
        self.assertEqual(window.title(), 'WPT Model Brief')
        window.destroy()
        self.assertEqual(self.app.store.page_jobs().total, 0)


if __name__ == '__main__':
    unittest.main()
