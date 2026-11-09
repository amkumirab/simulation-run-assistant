"""Real stored geometry with illustrative fixed sensors; no fields or solver."""
import argparse
import tempfile
from pathlib import Path
from unittest.mock import patch

from simulation_assistant.field_samples import Sensor
from simulation_assistant.geometry_files import load_snapshot
from simulation_assistant.sensor_placement import project_placement
from simulation_assistant.sensor_placement_views import save_placement_svg
from replay_geometry_comparison import HASHES, check, capture

DOMAINS = (4, 9, 10, 13)  # Explicit coil-envelope IDs for these exact saved fixtures only.
LABEL = 'ILLUSTRATIVE SENSOR POSITIONS | real stored geometry | no measured or simulated sensor readings'


def illustrative_sensors():
    sensors = []
    for y in (-.05, 0., .05):
        for x in (-.28, 0., .28):
            sensors.append(Sensor('S'+str(len(sensors)+1), (x, y, .08), (0., 0., 1.)))
    sensors[4] = Sensor('S5', sensors[4].position_m, (1., 1., 1.))
    sensors[7] = Sensor('S8', sensors[7].position_m, (0., 1., 0.))
    return tuple(sensors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geometry', choices=('original', 'overlap', 'control'), default='original')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--desktop', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--capture-dir', type=Path, help='Actual native Windows captures; requires existing Pillow')
    args = parser.parse_args()
    if args.headless and (args.desktop or args.capture_dir):
        parser.error('Headless replay cannot display or capture native windows')
    snapshot = load_snapshot(Path(__file__).with_name('saved_geometry_wpt')/(args.geometry+'.json'))
    check(snapshot.source_sha256 == HASHES[args.geometry], 'Stored fixture source changed')
    sensors = illustrative_sensors()
    views = [project_placement(snapshot, sensors, DOMAINS, plane, comparable_frames=True) for plane in ('XY', 'XZ')]
    check(views[0].sensors[0].axis_uv == (0., 0.), 'Normal +Z axis was projected incorrectly')
    check(views[1].sensors[7].axis_uv == (0., 0.), 'Normal +Y axis was projected incorrectly')
    with tempfile.TemporaryDirectory(prefix='sensor-placement-review-') as directory:
        folder = Path(directory)
        output = args.output_dir or folder
        output.mkdir(parents=True, exist_ok=True)
        path = output/('sensor-placement-'+args.geometry+'.svg')
        check(not path.exists(), 'Choose an output folder without an existing placement image')
        if args.headless:
            save_placement_svg(path, snapshot, sensors, DOMAINS, comparable_frames=True, layout_label=LABEL, selected_sensor='S5')
        else:
            import tkinter as tk
            from simulation_assistant.desktop import DesktopApp
            from simulation_assistant.sensor_placement_ui import SensorPlacementDialog
            root = tk.Tk()
            errors = []
            root.report_callback_exception = lambda *error: errors.append(error)
            try:
                app = DesktopApp(root, folder/'jobs.db', folder/'artifacts', folder/'profiles.json')
                dialog = SensorPlacementDialog(root)
                dialog.set_snapshot(snapshot)
                dialog.set_layout(sensors, LABEL)
                dialog.domains_tree.selection_set(*(str(d) for d in DOMAINS))
                root.update()
                check(not dialog.preview(), 'Preview accepted undeclared coordinate frames')
                dialog.frames.set(True)  # Deliberately defined illustrative positions in the fixture global frame.
                check(dialog.preview(), dialog.status.get())
                dialog.sensor_tree.selection_set('S5')
                dialog.sensor_selected()
                for size in ('1000x760', '1240x850'):
                    dialog.window.geometry(size+'+30+30')
                    root.update()
                    for canvas in dialog.canvases.values():
                        check(canvas.winfo_width() >= 400 and canvas.winfo_height() >= 300, 'Placement view clipped')
                with patch('tkinter.filedialog.asksaveasfilename', return_value=str(path)):
                    check(dialog.export(), dialog.status.get())
                if args.capture_dir:
                    for tab, name in ((2, 'views'), (1, 'coordinates')):
                        dialog.tabs.select(tab)
                        capture(root, dialog, args.capture_dir, 'sensor-placement-'+args.geometry+'-'+name+'.png')
                check(not errors, 'Native callback errors: '+str(errors))
                check(app.store.page_jobs().total == 0 and app.connection_report is None, 'Production workflow changed')
                if args.desktop:
                    root.mainloop()
            finally:
                try:
                    alive = root.winfo_exists()
                except tk.TclError:
                    alive = False
                if alive:
                    root.update_idletasks()
                    for child in list(root.winfo_children()):
                        if isinstance(child, tk.Toplevel):
                            child.destroy()
                    for timer in root.tk.call('after', 'info'):
                        root.after_cancel(timer)
                    root.destroy()
        print('PASS: '+args.geometry+' stored geometry | 4 explicit envelopes | 9 illustrative sensors | XY/XZ and SVG | no fields or solver')


if __name__ == '__main__':
    main()
