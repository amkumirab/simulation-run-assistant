"""Replay checked saved COMSOL fields without COMSOL, model files or new solves."""
import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from simulation_assistant.comsol_field_sampling import FieldExtraction, save_source_bundle
from simulation_assistant.field_sample_files import load_field_csv, load_field_workspace, write_field_readings_csv
from simulation_assistant.field_samples import analyze_field_samples

DEFAULT_BUNDLE = Path(__file__).with_name('saved_field_wpt')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bounded_bytes(path, limit):
    with path.open('rb') as handle:
        raw = handle.read(limit+1)
    require(len(raw) <= limit, 'Bundle file exceeds size limit: '+path.name)
    return raw


def unique_keys(pairs):
    record = {}
    for key, value in pairs:
        require(key not in record, 'Duplicate source evidence key')
        record[key] = value
    return record


def read_bundle(folder):
    """Check hashes and compare normalized CSV to the exact portable workspace."""
    folder = Path(folder)
    require((folder/'COMPLETE').is_file(), 'Incomplete source bundle: missing COMPLETE')
    bounded_bytes(folder/'COMPLETE', 128)
    raw_csv = bounded_bytes(folder/'fields.csv', 5_000_000)
    raw_workspace = bounded_bytes(folder/'workspace.json', 8_000_000)
    evidence = json.loads(bounded_bytes(folder/'evidence.json', 500_000), object_pairs_hook=unique_keys)
    require(isinstance(evidence, dict) and evidence.get('schema') == 'wpt.saved-field-campaign.v1',
            'Unsupported saved-field campaign evidence')
    require(evidence.get('new_solve') is False, 'Expected saved-solution evidence with no new solve')
    require(isinstance(evidence.get('sources'), list) and 1 <= len(evidence['sources']) <= 32,
            'Expected bounded source records')
    require(hashlib.sha256(raw_csv).hexdigest() == evidence.get('source_csv_sha256'),
            'CSV failed source integrity check')
    require(hashlib.sha256(raw_workspace).hexdigest() == evidence.get('workspace_sha256'),
            'Workspace failed source integrity check')
    data, sensors = load_field_workspace(folder/'workspace.json')
    require(data.metadata.source_kind == 'comsol-export' and asdict(data.metadata) == evidence.get('metadata'),
            'Expected matching COMSOL export metadata')
    require(data == load_field_csv(folder/'fields.csv', data.metadata), 'CSV and workspace fields differ')
    require(data.source_sha256 == hashlib.sha256(raw_csv).hexdigest(), 'Workspace source digest differs')
    return FieldExtraction(data, sensors, raw_csv, evidence)


def show_native(result, capture_dir=None, desktop=False):
    import tempfile
    import tkinter as tk
    from simulation_assistant.desktop import DesktopApp
    from simulation_assistant.field_sample_ui import FieldSamplesDialog

    with tempfile.TemporaryDirectory(prefix='saved-field-replay-') as temporary:
        folder = Path(temporary)
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        try:
            app = DesktopApp(root, folder/'jobs.db', folder/'artifacts', folder/'profiles.json')
            owner = FieldSamplesDialog(root)
            owner.set_data(result.data, result.sensors)
            owner.analyze()
            owner.origin.set('STORED COMSOL RESULT REPLAY | No COMSOL process or new solve. '
                             'Characterization fields, not measured hardware or calibrated MTJ output.')
            owner.window.title('Saved COMSOL field replay - no new solve')
            for size in ('980x720', '1120x840'):
                owner.window.geometry(size+'+30+30')
                root.update()
                body = owner.window.winfo_children()[0]
                for widget in body.winfo_children():
                    require(widget.winfo_y()+widget.winfo_height() <= body.winfo_height(),
                            'Native control clipped at '+size)
            require(len(owner.readings) == len(result.sensors), 'Native comparison lost sensors')
            require(app.store.page_jobs().total == 0 and app.connection_report is None,
                    'Replay must not connect or queue jobs')
            if capture_dir:
                import ctypes
                from PIL import ImageGrab
                target = Path(capture_dir)
                target.mkdir(parents=True, exist_ok=True)
                handle = ctypes.windll.user32.GetAncestor(owner.window.winfo_id(), 2)
                ImageGrab.grab(window=handle).save(target/'stored-field-replay.png')
            require(not errors, 'Native callback error: '+str(errors))
            if desktop:
                owner.window.protocol('WM_DELETE_WINDOW', root.destroy)
                owner.window.bind('<Escape>', lambda _event: root.destroy())
                root.mainloop()
                require(not errors, 'Native callback error: '+str(errors))
        finally:
            try:
                for timer in root.tk.call('after', 'info'):
                    root.after_cancel(timer)
                root.destroy()
            except tk.TclError:
                pass  # The user may already have closed the demonstration.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', nargs='?', type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument('--output-dir', type=Path, help='Create a new verified bundle and comparison CSV here')
    parser.add_argument('--headless', action='store_true', help='Check and export without creating any native window')
    parser.add_argument('--desktop', action='store_true', help='Keep the isolated native comparison open')
    parser.add_argument('--capture-dir', type=Path, help='Optional Windows capture; requires Pillow already installed')
    args = parser.parse_args(argv)
    if args.headless and (args.desktop or args.capture_dir):
        parser.error('--headless cannot be combined with --desktop or --capture-dir')
    try:
        result = read_bundle(args.bundle)
        require(len(result.data.scenarios) >= 2, 'A comparison needs at least two stored scenarios')
        current, reference = result.data.scenarios[-1], result.data.scenarios[0]
        readings = analyze_field_samples(result.data, result.sensors, current, reference)
        require(all(row.status == row.reference_status == 'available' for row in readings),
                'Comparison has unavailable current or reference readings')
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            bundle = save_source_bundle(args.output_dir, result)
            report = write_field_readings_csv(bundle/'comparison.csv', result.data, result.sensors, current, reference)
            with report.open(newline='') as handle:
                require(len(list(csv.DictReader(handle))) == len(result.sensors), 'Comparison export lost sensors')
            print('Bundle:', bundle)
        if not args.headless:
            show_native(result, args.capture_dir, args.desktop)
        print('PASS: STORED COMSOL RESULT REPLAY; integrity, complex fields and reference comparison checked. '
              'No COMSOL process, new solve or production queue changes.')
        for row in readings:
            print(row.sensor.point_id, 'current_uT', row.amplitude_t*1e6, 'change_uT', row.amplitude_change_t*1e6)
        return 0
    except (OSError, ValueError, RecursionError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
