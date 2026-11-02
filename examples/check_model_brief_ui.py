"""Exercise the actual native brief editor with illustrative metadata only."""
import argparse
import tempfile
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from simulation_assistant.desktop import DesktopApp
from simulation_assistant.model_brief_ui import ModelBriefDialog
from simulation_assistant.model_briefs import load_model_brief


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-dir', type=Path, help='Optional screenshot using Pillow on Windows')
    parser.add_argument('--desktop', action='store_true', help='Keep the isolated example open')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='model-brief-review-') as directory:
        folder = Path(directory)
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        try:
            app = DesktopApp(root, folder/'jobs.db', folder/'artifacts', folder/'profiles.json')
            root.geometry('1120x840+20+20')
            app.notebook.select(1)
            dialog = ModelBriefDialog(root)
            fixture = Path(__file__).with_name('wpt_model_brief.json')
            with patch('simulation_assistant.model_brief_ui.filedialog.askopenfilename', return_value=str(fixture)):
                dialog.load()
            check(dialog.entries == load_model_brief(fixture).entries, 'Fixture did not load exactly')
            for size in ('920x700', '1160x780'):
                dialog.window.geometry(size+'+40+40')
                root.update()
                body = dialog.window.winfo_children()[0]
                for widget in body.winfo_children():
                    check(widget.winfo_y()+widget.winfo_height() <= body.winfo_height(), f'Clipped vertically: {widget}')
                    check(widget.winfo_x()+widget.winfo_width() <= body.winfo_width(), f'Clipped horizontally: {widget}')
                check(dialog.tree.winfo_ismapped(), 'Table is not visible')
                check(dialog.name_entry.tk_focusNext() is not None, 'Missing keyboard focus traversal')
            dialog.tree.selection_set('2')
            dialog.tree.focus_force()
            dialog.tree.event_generate('<Return>')
            root.update()
            check(dialog.selected == 2 and root.focus_get() == dialog.entry_name, 'Enter did not open the selected entry')
            dialog.fields['value'].set('2')
            dialog.tree.selection_set('0')
            root.update()
            check(dialog.selected == 2 and dialog.fields['value'].get() == '2', 'Pending entry was discarded')
            check(not dialog.save(), 'Pending edits were silently saved')
            check(dialog.apply_entry(), dialog.status.get())
            target = folder/'round-trip.json'
            with patch('simulation_assistant.model_brief_ui.filedialog.asksaveasfilename', return_value=str(target)):
                check(dialog.save(), dialog.status.get())
            check(load_model_brief(target).entries[2].value == '2', 'Edited value did not round-trip')
            with patch('simulation_assistant.model_brief_ui.filedialog.askopenfilename', return_value=str(fixture)):
                dialog.load()
            check(not dialog.dirty(), 'Loaded example should be clean')
            if args.capture_dir:
                import ctypes
                from PIL import ImageGrab
                args.capture_dir.mkdir(parents=True, exist_ok=True)
                dialog.window.lift()
                root.update()
                handle = ctypes.windll.user32.GetAncestor(dialog.window.winfo_id(), 2)
                ImageGrab.grab(window=handle).save(args.capture_dir/'model-brief.png')
            check(app.store.page_jobs().total == 0 and app.connection_report is None, 'Production workflow was touched')
            check(not errors, f'Native callback errors: {errors}')
            print('PASS: illustrative metadata, native sizes/keyboard, pending-edit protection, JSON round trip; no model or solver actions')
            if args.desktop:
                root.mainloop()
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == '__main__':
    main()
