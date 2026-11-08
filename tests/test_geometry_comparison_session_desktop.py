import os
import unittest
from unittest.mock import patch

import test_geometry_comparison_desktop as native
from simulation_assistant.geometry_comparison_sessions import load_session, save_session, GeometryComparisonSession
from simulation_assistant.geometry_files import save_snapshot
from test_geometry_inspector import snapshot
from native_test_support import collect_native_garbage as tearDownModule


@unittest.skipIf(native.tk is None, 'Native checks require Tk')
class GeometryComparisonSessionDesktopTests(unittest.TestCase):
    setUp = native.GeometryComparisonDesktopTests.setUp
    add_pair = native.GeometryComparisonDesktopTests.add_pair
    load_sources = native.GeometryComparisonDesktopTests.load_sources

    def ready(self):
        self.load_sources()
        self.add_pair()
        self.dialog.frames.set(True)
        self.assertTrue(self.dialog.compare())

    def save(self, path=None):
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(path or self.folder/'session.json')):
            return self.dialog.sessions.save()

    def load(self, path=None, discard=True):
        with patch('tkinter.filedialog.askopenfilename', return_value=str(path or self.folder/'session.json')), \
                patch('tkinter.messagebox.askyesno', return_value=discard):
            return self.dialog.sessions.load()

    def test_save_load_restores_inputs_but_never_imports_approval_or_results(self):
        self.ready()
        self.dialog.threshold.set('.25')
        self.dialog.compare()
        result = self.dialog.result
        self.assertTrue(self.save())
        expected = load_session(self.folder/'session.json')
        self.assertIs(self.dialog.result, result)
        self.assertTrue(self.dialog.frames.get())
        self.assertFalse(self.dialog.dirty())
        self.dialog.threshold.set('3')
        self.dialog.form['label'].set('Pending')
        self.assertTrue(self.load())
        self.assertEqual(self.dialog.pairs, expected.pairs)
        self.assertEqual(self.dialog.sources['baseline'], expected.baseline)
        self.assertEqual(self.dialog.threshold.get(), '0.25')
        self.assertFalse(self.dialog.frames.get())
        self.assertIsNone(self.dialog.result)
        self.assertFalse(self.dialog.pending())
        self.assertFalse(self.dialog.metrics_tree.get_children())
        self.assertEqual(self.dialog.pairs_tree.item('0', 'values')[-1], 'Not compared')
        self.assertEqual(self.dialog.tabs.index('current'), 0)
        self.assertFalse(self.dialog.dirty())
        self.assertFalse(self.dialog.compare())
        self.dialog.frames.set(True)
        self.assertTrue(self.dialog.compare())
        self.assertFalse(self.dialog.dirty())
        for size in ('1000x760', '1240x850'):
            self.dialog.window.geometry(size)
            self.root.update()
            body = self.dialog.window.winfo_children()[0]
            for child in body.winfo_children():
                self.assertLessEqual(child.winfo_x()+child.winfo_width(), body.winfo_width())
                self.assertLessEqual(child.winfo_y()+child.winfo_height(), body.winfo_height())
        self.assertEqual(self.app.store.page_jobs().total, 0)
        self.assertFalse(self.errors)

    def test_draft_without_pairs_is_saveable_and_can_reopen_in_a_new_window(self):
        self.load_sources()
        self.assertTrue(self.dialog.dirty())
        self.assertTrue(self.save())
        self.dialog.close()
        from simulation_assistant.geometry_comparison_ui import GeometryComparisonDialog
        self.dialog = GeometryComparisonDialog(self.root)
        self.assertTrue(self.load())
        self.assertEqual(self.dialog.pairs, ())
        self.assertFalse(self.dialog.dirty())
        self.assertFalse(self.dialog.compare())

    def test_pending_or_invalid_inputs_block_save_before_chooser(self):
        self.load_sources()
        for label, threshold in (('Pending', '.01'), ('', 'nan'), ('', '-1')):
            self.dialog.form['label'].set(label)
            self.dialog.threshold.set(threshold)
            with patch('tkinter.filedialog.asksaveasfilename') as chooser:
                self.assertFalse(self.dialog.sessions.save())
                chooser.assert_not_called()
        self.assertTrue(self.dialog.dirty())

    def test_failed_cancelled_or_declined_load_preserves_entire_current_work(self):
        self.ready()
        save_session(self.folder/'session.json', GeometryComparisonSession(snapshot(), snapshot(), ()))
        before = self.dialog.signature()
        result = self.dialog.result
        saved = self.dialog._saved
        self.assertFalse(self.load(discard=False))
        invalid = self.folder/'bad.json'
        invalid.write_text('{}')
        self.assertFalse(self.load(invalid))
        with patch('tkinter.filedialog.askopenfilename', return_value=''):
            self.assertFalse(self.dialog.sessions.load())
        self.assertEqual(self.dialog.signature(), before)
        self.assertIs(self.dialog.result, result)
        self.assertEqual(self.dialog._saved, saved)
        self.assertTrue(self.dialog.frames.get())

    def test_failed_cancelled_save_does_not_clear_dirty_state(self):
        self.ready()
        with patch('tkinter.filedialog.asksaveasfilename', return_value=''):
            self.assertFalse(self.dialog.sessions.save())
        with patch('simulation_assistant.geometry_comparison_session_ui.save_session', side_effect=OSError('locked')):
            self.assertFalse(self.save())
        self.assertTrue(self.dialog.dirty())
        self.assertTrue(self.dialog.frames.get())
        self.assertIsNotNone(self.dialog.result)
        self.assertFalse((self.folder/'session.json').exists())

    def test_loaded_source_snapshot_cannot_be_overwritten_even_via_alias(self):
        source = save_snapshot(self.folder/'baseline.json', snapshot())
        before = source.read_bytes()
        with patch('tkinter.filedialog.askopenfilename', return_value=str(source)):
            self.dialog.load('baseline')
        self.dialog.set_snapshot('candidate', snapshot(), 'Candidate')
        self.add_pair()
        for target in (source, source.parent/'unused'/'..'/source.name):
            with self.subTest(target=target):
                self.assertFalse(self.save(target))
                self.assertEqual(source.read_bytes(), before)
        alias = source.with_name('snapshot-alias.json')
        os.link(source, alias)
        self.assertFalse(self.save(alias))
        self.assertEqual(alias.read_bytes(), before)
        self.assertTrue(self.save())
        self.assertEqual(source.read_bytes(), before)

    def test_csv_export_does_not_replace_a_session_save(self):
        self.ready()
        with patch('tkinter.filedialog.asksaveasfilename', return_value=str(self.folder/'report.csv')):
            self.assertTrue(self.dialog.export())
        self.assertTrue(self.dialog.dirty())
        self.assertTrue(self.save())
        self.assertFalse(self.dialog.dirty())
        self.dialog.frames.set(False)
        self.assertFalse(self.dialog.dirty())
        self.dialog.threshold.set('1')
        self.assertTrue(self.dialog.dirty())

    def test_session_buttons_are_visible_and_keyboard_focusable_at_minimum_size(self):
        self.dialog.window.geometry('1000x760')
        self.root.update()
        buttons = (self.dialog.sessions.save_button, self.dialog.sessions.load_button)
        for button in buttons:
            self.assertTrue(button.winfo_viewable())
            button.focus_force()
            self.root.update()
            self.assertEqual(self.root.focus_get(), button)
        a, b = buttons
        self.assertLessEqual(a.winfo_x()+a.winfo_width(), b.winfo_x())
        parent = b.master
        for child in parent.winfo_children():
            self.assertLessEqual(child.winfo_x()+child.winfo_width(), parent.winfo_width())
        self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
