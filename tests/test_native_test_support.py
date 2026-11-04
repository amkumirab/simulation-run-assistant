import unittest
from native_test_support import destroy_root
from native_test_support import collect_native_garbage as tearDownModule
try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, 'Native checks require Tk')
class NativeWorkspaceCleanupTests(unittest.TestCase):
    def test_cleanup_cancels_jobs_and_flushes_theme_before_destroy(self):
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest('Native checks require a display')
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        ttk.Frame(root).pack()
        ttk.Style(root).theme_use('clam')
        root.after(10000, lambda: errors.append('late job'))
        destroy_root(root)
        self.assertEqual(root.tk.splitlist(root.tk.call('after', 'info')), ())
        self.assertFalse(errors)


if __name__ == '__main__':
    unittest.main()
