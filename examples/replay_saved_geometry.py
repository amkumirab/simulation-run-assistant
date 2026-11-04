"""Replay real stored geometry envelopes in an isolated native workspace (no COMSOL)."""
import argparse
import tempfile
import tkinter as tk
from pathlib import Path
from simulation_assistant.desktop import DesktopApp
from simulation_assistant.geometry_files import load_snapshot
from simulation_assistant.geometry_ui import GeometryDialog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=Path(__file__).with_name('saved_geometry_wpt')/'original.json')
    parser.add_argument('--capture-dir', type=Path, help='Optional actual-window screenshots using existing Pillow on Windows')
    parser.add_argument('--desktop', action='store_true')
    args = parser.parse_args()
    data = load_snapshot(args.snapshot)
    with tempfile.TemporaryDirectory(prefix='geometry-review-') as directory:
        folder = Path(directory)
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        try:
            app = DesktopApp(root, folder/'jobs.db', folder/'artifacts', folder/'profiles.json')
            app.notebook.select(1)
            dialog = GeometryDialog(root)
            dialog.set_snapshot(data, 'REAL STORED GEOMETRY | '+args.snapshot.stem+' | offline replay, not live')
            # Domain IDs are an explicit worked-example mapping, not a general role detector.
            known = data.source_sha256 in {
                'ffa0f12bc3b5877b0b039742ffab099795bc3d33fb188177112a896b8e56c3a8',
                '80b6f71b59e0d36224dff386864d287adb6c231bbee65ffd7076f42796df7917',
                'b5b4f573aee911b2249c7b1d34b6be2870b8d80aedc2b17d1cd6c90ffbef783a',
            }
            selected = tuple(str(part.domain) for part in data.parts if known and part.domain != 1)
            dialog.tree.selection_set(*selected)
            if known:
                dialog.lower.set('9')
                dialog.upper.set('10')
                dialog.parallel.set(True)
            for size in ('1000x760', '1240x850'):
                dialog.window.geometry(size+'+30+30')
                root.update()
                body = dialog.window.winfo_children()[0]
                for widget in body.winfo_children():
                    if widget.winfo_x()+widget.winfo_width() > body.winfo_width() or widget.winfo_y()+widget.winfo_height() > body.winfo_height():
                        raise RuntimeError('Clipped native control: '+str(widget))
            dialog.tree.focus_force()
            dialog.tree.event_generate('<Return>')
            root.update()
            if (known and not dialog.selected_domains()) or dialog.tree.tk_focusNext() is None:
                raise RuntimeError('Selection or keyboard traversal unavailable')
            if args.capture_dir:
                import ctypes
                from PIL import ImageGrab
                args.capture_dir.mkdir(parents=True, exist_ok=True)
                def capture(name):
                    dialog.window.lift()
                    root.update()
                    handle = ctypes.windll.user32.GetAncestor(dialog.window.winfo_id(), 2)
                    ImageGrab.grab(window=handle).save(args.capture_dir/name)
                capture('geometry-bounds-'+args.snapshot.stem+'.png')
                dialog.tabs.select(1)
                root.update()
                dialog.redraw()
                capture('geometry-xz-'+args.snapshot.stem+'.png')
            if errors or app.store.page_jobs().total != 0 or app.connection_report is not None:
                raise RuntimeError('Native callbacks or isolated-workspace check failed: '+str(errors))
            print(f'PASS: {len(data.parts)} real stored envelopes; keyboard and both native sizes; no model/queue/solver actions')
            if args.desktop:
                root.mainloop()
        finally:
            root.destroy()


if __name__ == '__main__':
    main()
