"""Read existing WPT solutions at fixed sensors; never compute or save an MPH."""
import argparse
import csv
import ctypes
import tempfile
import tkinter as tk
from pathlib import Path

from simulation_assistant.comsol_field_sampling import (
    SavedScenario, inspect_saved_fields, extract_scenarios, save_source_bundle, model_digest,
)
from simulation_assistant.field_samples import make_sensor_grid, analyze_field_samples
from simulation_assistant.field_sample_files import load_field_workspace, write_field_readings_csv
from simulation_assistant.desktop import DesktopApp
from simulation_assistant.field_sample_ui import FieldSamplesDialog
from simulation_assistant.comsol_field_ui import SavedFieldDialog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('models', type=Path, nargs='+', help='Existing solved 3D MPH files with the same excitation/frame')
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--inner', type=int, required=True, help='Explicit inner state to use in each model (for example TX-only case 1)')
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--solver', required=True)
    parser.add_argument('--outer', type=int, default=1)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--excitation', required=True)
    parser.add_argument('--phase-reference', required=True)
    parser.add_argument('--convention', choices=('peak', 'rms'), required=True)
    parser.add_argument('--z-mm', type=float, default=80.)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--capture-dir', type=Path)
    args = parser.parse_args()
    scenarios = []
    for index, model in enumerate(args.models, 1):
        digest, states = inspect_saved_fields(model, args.executable)
        matches = [s for s in states if (s.dataset, s.solver, s.outer, s.inner) == (args.dataset, args.solver, args.outer, args.inner)]
        if len(matches) != 1:
            raise ValueError('Explicit dataset/solver/outer/inner selection not found')
        scenarios.append(SavedScenario(f'Position {index}', model, digest, matches[0]))
        print(f'Inspected Position {index}: {matches[0]} | SHA-256 {digest}', flush=True)
    sensors = make_sensor_grid(3, 3, .02, args.z_mm/1000., (0., 0., 1.))
    result = extract_scenarios(tuple(scenarios), args.executable, tuple(args.prefix+'.B'+axis for axis in 'xyz'),
                               sensors, args.convention, args.excitation, args.phase_reference)
    readings = analyze_field_samples(result.data, sensors, scenarios[-1].name, scenarios[0].name)
    assert len(readings) == 9 and all(r.status == 'available' for r in readings)
    with tempfile.TemporaryDirectory(prefix='saved-field-native-check-') as directory:
        folder = Path(directory)
        bundle = save_source_bundle(args.output_dir or folder, result)
        loaded, layout = load_field_workspace(bundle/'workspace.json')
        assert loaded == result.data and layout == sensors
        report = write_field_readings_csv(bundle/'comparison.csv', result.data, sensors, scenarios[-1].name, scenarios[0].name)
        with report.open(newline='') as stream:
            assert len(list(csv.DictReader(stream))) == 9
        for scenario in scenarios:
            assert model_digest(scenario.model_path) == scenario.model_sha256
        root = tk.Tk()
        try:
            app = DesktopApp(root, folder/'jobs.db', folder/'artifacts', folder/'profiles.json')
            owner = FieldSamplesDialog(root)
            owner.set_data(result.data, sensors)
            owner.analyze()
            dialog = SavedFieldDialog(owner)
            errors = []
            root.report_callback_exception = lambda *error: errors.append(error)
            for name, value in (('executable', str(args.executable)), ('prefix', args.prefix), ('convention', args.convention),
                                ('excitation', args.excitation), ('phase_reference', args.phase_reference)):
                dialog.variables[name].set(value)
            for scenario in scenarios:
                dialog.variables['model'].set(str(scenario.model_path))
                dialog.accept_catalog((scenario.model_sha256, (scenario.state,)))
                dialog.state_combo.current(0)
                dialog.variables['scenario'].set(scenario.name)
                dialog.add_state()
            dialog.confirmed.set(True)
            # Exercise the same completion path used by background extraction.
            dialog.complete('extract', dialog.signature(), result)
            for size in ('980x760', '1080x820'):
                dialog.window.geometry(size+'+30+30')
                root.update()
                body = dialog.window.winfo_children()[0]
                for widget in body.winfo_children():
                    assert widget.winfo_y()+widget.winfo_height() <= body.winfo_height(), (widget, size)
            assert len(owner.readings) == 9
            assert app.store.page_jobs().total == 0 and app.connection_report is None
            if args.capture_dir:
                from PIL import ImageGrab
                args.capture_dir.mkdir(parents=True, exist_ok=True)
                def capture(window, name):
                    root.update()
                    handle = ctypes.windll.user32.GetAncestor(window.winfo_id(), 2)
                    ImageGrab.grab(window=handle).save(args.capture_dir/name)
                capture(dialog.window, 'saved-solution-selection.png')
                dialog.window.withdraw()
                owner.window.geometry('1120x840+30+30')
                owner.window.lift()
                capture(owner.window, 'saved-field-comparison.png')
            assert not errors, errors
            dialog.close()
        finally:
            for timer in root.tk.call('after', 'info'):
                root.after_cancel(timer)
            root.destroy()
        print('PASS: real saved fields, 9 fixed sensors, complex values, exact workspace, source bundle, native sizes, unchanged model hashes; no solve or production queue mutation', flush=True)
        for reading in readings:
            print(reading.sensor.point_id, 'current_uT', reading.amplitude_t*1e6,
                  'change_uT', reading.amplitude_change_t*1e6, flush=True)
        if args.output_dir:
            print('Bundle:', bundle, flush=True)


if __name__ == '__main__':
    main()
