"""Actual stored COMSOL fields screened against explicitly hypothetical limits."""
import argparse
import tempfile
from pathlib import Path

from simulation_assistant.geometry_files import load_snapshot
from simulation_assistant.saved_field_bundles import load_saved_field_bundle
from simulation_assistant.sensor_field_overlay import analyze_overlay
from simulation_assistant.sensor_limit_checks import assess_sensor_limits
from simulation_assistant.sensor_limit_reports import save_sensor_assessment
from simulation_assistant.sensor_profile_files import save_sensor_profile
from simulation_assistant.sensor_profiles import SensorProfile, StatedRange

FIXTURE = Path(__file__).with_name('saved_field_wpt')


def example_profile(case):
    bound = 100. if case == 'wide' else 35.
    return SensorProfile('Hypothetical '+case+' design envelope', target_field='charging-coil-ac',
        frequency=StatedRange(0., 100., 'kHz', 'Illustrative design assumption, not an MTJ datasheet', 'Single-frequency screening'),
        field=StatedRange(-bound, bound, 'uT', 'Illustrative design assumption, not an MTJ datasheet', 'Signed sensitivity-axis B only'),
        notes='No physical sensor selected. These limits cannot establish hardware detectability.')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def show_native(bundle, geometry, profile, case, capture_dir, desktop):
    import tkinter as tk
    from simulation_assistant.desktop import DesktopApp
    from simulation_assistant.sensor_placement_ui import SensorPlacementDialog

    with tempfile.TemporaryDirectory(prefix='sensor-profile-replay-') as temporary:
        root = tk.Tk()
        folder = Path(temporary)
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        try:
            app = DesktopApp(root, folder/'jobs.db', folder/'artifacts', folder/'profiles.json')
            placement = SensorPlacementDialog(root)
            placement.set_snapshot(geometry)
            fields = placement.field_overlay
            fields.set_bundle(bundle)
            fields.use_layout()
            placement.domains_tree.selection_set('6', '7')
            root.update()
            fields.current.set('Position 2')
            fields.reference.set('Position 1')
            placement.frames.set(True)
            fields.state_matches.set(True)  # Explicit CLI declaration required before this function.
            require(fields.analyze(), placement.status.get())
            dialog = fields.open_sensor_profiles()
            dialog.window.title('HYPOTHETICAL SENSOR LIMITS - actual stored COMSOL fields - no hardware claim')
            dialog.set_profile(profile)
            dialog.context['sampled_field'].set('charging-coil-ac')
            if case != 'unknown':
                for axis in 'xyz':
                    dialog.context['dc_'+axis].set('0')  # Explicit illustrative uniform-zero-DC assumption.
            dialog.confirmed.set(True)
            require(dialog.evaluate(), dialog.status.get())
            dialog.tree.selection_set('8')  # S5, current Position 2.
            dialog.show_detail()
            for size in ('1040x780', '1240x900'):
                dialog.window.geometry(size+'+30+30')
                for tab in (0, 1):
                    dialog.tabs.select(tab)
                    root.update()
                    body = dialog.window.winfo_children()[0]
                    require(all(w.winfo_y()+w.winfo_height() <= body.winfo_height() for w in body.winfo_children()),
                            'Native control clipped at '+size)
                    require(dialog.valid_result() is not None, 'Resize lost current assessment')
            if capture_dir:
                import ctypes
                from PIL import ImageGrab
                capture_dir.mkdir(parents=True, exist_ok=True)
                for tab, name in ((0, 'profile-editor.png'), (1, 'declared-limit-screening.png')):
                    target = capture_dir/name
                    require(not target.exists(), 'Capture already exists: '+str(target))
                    dialog.tabs.select(tab)
                    root.update()
                    handle = ctypes.windll.user32.GetAncestor(dialog.window.winfo_id(), 2)
                    ImageGrab.grab(window=handle).save(target)
            require(app.store.page_jobs().total == 0 and app.connection_report is None, 'Unexpected queue/connection mutation')
            require(not errors, 'Native callback errors: '+str(errors))
            if desktop:
                def close_demo():
                    if dialog.can_close():
                        root.destroy()
                dialog.window.protocol('WM_DELETE_WINDOW', close_demo)
                dialog.window.bind('<Escape>', lambda _event: close_demo())
                root.mainloop()
                require(not errors, 'Native callback errors: '+str(errors))
        finally:
            try:
                for timer in root.tk.call('after', 'info'):
                    root.after_cancel(timer)
                root.destroy()
            except tk.TclError:
                pass  # The user may close the isolated demonstration first.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=('wide', 'narrow', 'unknown'), default='narrow')
    parser.add_argument('--confirm-assumptions', action='store_true', help='Confirm reviewed example frames/state, hypothetical limits, field purpose and uniform-zero-DC assumption (unknown case keeps bias unknown)')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--capture-dir', type=Path, help='Actual Windows capture, requires existing Pillow')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args(argv)
    if args.headless and (args.desktop or args.capture_dir):
        parser.error('--headless cannot be combined with --desktop or --capture-dir')
    if not args.confirm_assumptions:
        parser.error('Review the worked example, then explicitly use --confirm-assumptions; this is not a physical sensor profile')
    try:
        bundle = load_saved_field_bundle(FIXTURE)
        geometry = load_snapshot(FIXTURE/'geometry-position-2.json')
        overlay = analyze_overlay(geometry, bundle.sensors, bundle, 'Position 2', 'Position 1',
                                  comparable_frames=True, geometry_matches_state=True)
        profile = example_profile(args.case)
        result = assess_sensor_limits(profile, overlay, sampled_field='charging-coil-ac',
                                      dc_bias_t=None if args.case == 'unknown' else (0., 0., 0.), conditions_confirmed=True)
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            targets = [args.output_dir/(kind+'-'+args.case+'.json') for kind in ('profile', 'assessment')]
            require(not any(p.exists() for p in targets), 'Output already exists; choose a new directory')
            save_sensor_profile(targets[0], profile)
            save_sensor_assessment(targets[1], result)
        if not args.headless:
            show_native(bundle, geometry, profile, args.case, args.capture_dir, args.desktop)
        print('PASS:', result.scope, '|', args.case, '|', ', '.join(sorted({r.status for r in result.rows})))
        print('No COMSOL process, new solve, physical sensor specification or production queue change. Sensitivity/noise not evaluated.')
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
