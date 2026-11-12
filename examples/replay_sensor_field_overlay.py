"""Offline replay of genuinely paired saved COMSOL fields and geometry envelopes."""
import argparse
import tempfile
from pathlib import Path

from simulation_assistant.geometry_files import load_snapshot
from simulation_assistant.saved_field_bundles import load_saved_field_bundle
from simulation_assistant.sensor_field_overlay import analyze_overlay
from simulation_assistant.sensor_field_views import save_overlay_svg

FIXTURE = Path(__file__).with_name('saved_field_wpt')
DOMAINS = (2, 3, 4, 5, 6, 7)  # Explicit saved solid domains; omit the large surrounding air envelope.


def require(condition, message):
    if not condition:
        raise ValueError(message)


def show_native(bundle, geometry, current, reference, capture_dir, desktop):
    import tkinter as tk
    from simulation_assistant.desktop import DesktopApp
    from simulation_assistant.sensor_placement_ui import SensorPlacementDialog

    with tempfile.TemporaryDirectory(prefix='sensor-field-replay-') as temporary:
        folder = Path(temporary)
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        try:
            app = DesktopApp(root, folder/'jobs.db', folder/'artifacts', folder/'profiles.json')
            owner = SensorPlacementDialog(root)
            owner.window.title('STORED COMSOL REPLAY - Sensor Field Overlay - no new solve')
            owner.set_snapshot(geometry)
            fields = owner.field_overlay
            fields.set_bundle(bundle)
            fields.use_layout()
            owner.domains_tree.selection_set(*(str(d) for d in DOMAINS))
            root.update()
            fields.current.set(current)
            fields.reference.set(reference)
            owner.frames.set(True)
            fields.state_matches.set(True)  # Only reached after the explicit CLI declaration.
            require(fields.analyze(), owner.status.get())
            owner.sensor_tree.selection_set('S5')
            owner.sensor_selected()
            for size in ('1000x760', '1240x850'):
                owner.window.geometry(size+'+30+30')
                for tab in (fields.tab, 2):
                    owner.tabs.select(tab)
                    root.update()
                    body = owner.window.winfo_children()[0]
                    require(all(w.winfo_y()+w.winfo_height() <= body.winfo_height() for w in body.winfo_children()),
                            'Native control clipped at '+size)
                    require(fields.valid_result() is not None, 'Resize lost accepted field overlay')
            if capture_dir:
                import ctypes
                from PIL import ImageGrab
                capture_dir.mkdir(parents=True, exist_ok=True)
                for tab, name in ((fields.tab, 'field-overlay-readings.png'), (2, 'field-overlay-views.png')):
                    target = capture_dir/name
                    require(not target.exists(), 'Capture already exists: '+str(target))
                    owner.tabs.select(tab)
                    root.update()
                    handle = ctypes.windll.user32.GetAncestor(owner.window.winfo_id(), 2)
                    ImageGrab.grab(window=handle).save(target)
            require(app.store.page_jobs().total == 0 and app.connection_report is None, 'Unexpected queue/connection change')
            require(not errors, 'Native callback errors: '+str(errors))
            if desktop:
                owner.window.protocol('WM_DELETE_WINDOW', root.destroy)
                owner.window.bind('<Escape>', lambda _event: root.destroy())
                root.mainloop()
                require(not errors, 'Native callback errors: '+str(errors))
        finally:
            try:
                for timer in root.tk.call('after', 'info'):
                    root.after_cancel(timer)
                root.destroy()
            except tk.TclError:
                pass  # A user can close the isolated demonstration first.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current', choices=('1', '2'), default='2')
    parser.add_argument('--confirm-frame-and-state', action='store_true',
                        help='Explicitly declare comparable frames and saved geometry appropriate to this current solution state')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--desktop', action='store_true', help='Keep the isolated native window open')
    parser.add_argument('--capture-dir', type=Path, help='Optional actual Windows capture; requires existing Pillow')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args(argv)
    if args.headless and (args.desktop or args.capture_dir):
        parser.error('--headless cannot be combined with --desktop or --capture-dir')
    if not args.confirm_frame_and_state:
        parser.error('Review the worked source/state notes, then explicitly use --confirm-frame-and-state; hashes alone are insufficient')
    try:
        bundle = load_saved_field_bundle(FIXTURE)
        geometry = load_snapshot(FIXTURE/('geometry-position-'+args.current+'.json'))
        current, reference = 'Position '+args.current, 'Position '+('1' if args.current == '2' else '2')
        overlay = analyze_overlay(geometry, bundle.sensors, bundle, current, reference,
                                  comparable_frames=True, geometry_matches_state=True)
        require(len(overlay.readings) == 9 and all(r.status == r.reference_status == 'available' for r in overlay.readings),
                'Worked example lost fixed sensor readings')
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            target = args.output_dir/('sensor-field-position-'+args.current+'.svg')
            require(not target.exists(), 'Output already exists: '+str(target))
            save_overlay_svg(target, overlay, DOMAINS, layout_label='STORED COMSOL RESULT REPLAY | fixed 3x3 sensor grid', selected_sensor='S5')
            print('SVG:', target)
        if not args.headless:
            show_native(bundle, geometry, current, reference, args.capture_dir, args.desktop)
        row = overlay.readings[4]
        print(f'PASS: 9 available readings | S5 {row.amplitude_t*1e6:.10f} uT | delta {row.amplitude_change_t*1e6:+.10f} uT')
        print('No COMSOL process, new solve or production queue changes. Current geometry only; user-declared state correspondence.')
        print('TX-only characterization fields, not calibrated MTJ output or a vehicle magnetic signature.')
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
