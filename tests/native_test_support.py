"""Dispose isolated Tk test workspaces without leaving interpreter callbacks."""


def destroy_root(root):
    # Theme changes are queued as idle callbacks; flush while widgets still exist.
    root.update_idletasks()
    # Dialogs must cancel their own timers before root-level jobs are cancelled.
    import tkinter as tk
    for child in list(root.winfo_children()):
        if isinstance(child, tk.Toplevel):
            child.destroy()
    for timer in root.tk.call('after', 'info'):
        root.after_cancel(timer)
    root.destroy()
    # Collect older released workspaces here, before any later worker can run GC.
    collect_native_garbage()


def collect_native_garbage():
    """Use as tearDownModule after unittest releases its last native test case."""
    import gc
    gc.collect()
