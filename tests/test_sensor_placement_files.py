import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from test_geometry_inspector import snapshot
from simulation_assistant.field_samples import Sensor
from simulation_assistant.sensor_placement_views import placement_items, placement_svg, save_placement_svg
from simulation_assistant.sensor_placement import project_placement, layout_digest
from simulation_assistant.geometry_files import snapshot_digest


class SensorPlacementFileTests(unittest.TestCase):
    def setUp(self):
        self.sensors = (Sensor('S1', (.012345678901234567, 0., .08), (0., 0., 2.)),)

    def test_svg_has_two_views_numeric_data_and_traceable_safe_provenance(self):
        text = placement_svg(snapshot(), self.sensors, (1,), comparable_frames=True,
                             layout_label='Illustrative <layout> & review', selected_sensor='S1')
        root = ET.fromstring(text)
        ns = {'s': 'http://www.w3.org/2000/svg'}
        metadata = json.loads(root.find('s:metadata', ns).text)
        self.assertEqual(metadata['source_sha256'], snapshot().source_sha256)
        self.assertEqual(metadata['snapshot_sha256'], snapshot_digest(snapshot()))
        self.assertEqual(metadata['layout_sha256'], layout_digest(self.sensors))
        self.assertEqual(metadata['domains'], [1])
        self.assertIs(metadata['comparable_frames'], True)
        self.assertEqual(metadata['sensors'][0]['position_m'], list(self.sensors[0].position_m))
        self.assertEqual(metadata['sensors'][0]['axis_normalized'], [0., 0., 1.])
        self.assertIn(repr(self.sensors[0].position_m[0]), text)
        labels = ' '.join(element.text or '' for element in root.iter())
        for label in ('XY', 'XZ', 'not CAD', 'Frame declaration', 'normal Z', 'x_m', 'nZ'):
            self.assertIn(label, labels)
        self.assertEqual(len(root.findall('s:g', ns)), 2)
        self.assertFalse(root.findall('.//s:script', ns))
        self.assertFalse(root.findall('.//*[@href]'))
        self.assertIn('&lt;layout&gt; &amp; review', text)
        self.assertNotIn('C:\\', text)
        self.assertNotIn('data:image', text)

    def test_scene_contains_projected_arrows_and_normal_axis_notice(self):
        view = project_placement(snapshot(), self.sensors, (1,), 'XY', comparable_frames=True)
        items = placement_items(view, 'S1')
        self.assertTrue(any('normal Z' in item.text for item in items))
        self.assertTrue(any(item.dashed for item in items))
        self.assertTrue(any(item.kind == 'oval' and item.width == 3 for item in items))
        self.assertTrue(all(item.coords for item in items))

    def test_export_requires_frames_selection_and_valid_label(self):
        for changes in ({'comparable_frames': False}, {'layout_label': ''},
                        {'layout_label': 'line\nbreak'}, {'selected_sensor': 'Missing'}):
            args = dict(comparable_frames=True, layout_label='Illustrative sensors')
            args.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                placement_svg(snapshot(), self.sensors, (1,), **args)

    def test_long_ids_are_shortened_only_on_the_plot_and_coincident_markers_are_explicit(self):
        name = 'S'+'a'*79
        sensors = (Sensor(name, (0., 0., 0.), (0., 0., 1.)), Sensor('S2', (0., 1., 0.), (0., 1., 0.)))
        view = project_placement(snapshot(), sensors, (1,), 'XZ', comparable_frames=True)
        labels = [item.text for item in placement_items(view) if item.kind == 'text']
        self.assertIn('2 projected sensors', labels)
        labels = [item.text for item in placement_items(view, name) if item.kind == 'text']
        self.assertNotIn(name, labels)
        text = placement_svg(snapshot(), sensors, (1,), comparable_frames=True, layout_label='Layout', selected_sensor=name)
        self.assertIn(name, text)  # Full input ID remains in provenance and the numeric table.

    def test_maximum_sensor_layout_is_retained_in_the_vector_export(self):
        sensors = tuple(Sensor('S'+str(i), (i*.001, 0., .08), (0., 0., 1.)) for i in range(256))
        root = ET.fromstring(placement_svg(snapshot(), sensors, (1,), comparable_frames=True, layout_label='Dense layout'))
        metadata = json.loads(root.find('{http://www.w3.org/2000/svg}metadata').text)
        self.assertEqual(len(metadata['sensors']), 256)
        self.assertIn('S255', ''.join(root.itertext()))

    def test_atomic_failure_and_invalid_suffix_leave_existing_evidence_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'placement.svg'
            path.write_text('existing evidence')
            with patch('simulation_assistant.geometry_files.os.replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    save_placement_svg(path, snapshot(), self.sensors, (1,), comparable_frames=True, layout_label='Layout')
            self.assertEqual(path.read_text(), 'existing evidence')
            self.assertEqual(list(path.parent.iterdir()), [path])
            with self.assertRaises(ValueError):
                save_placement_svg(path.with_suffix('.mph'), snapshot(), self.sensors, (1,), comparable_frames=True, layout_label='Layout')
            with self.assertRaises(ValueError):
                save_placement_svg(path, snapshot(), self.sensors, (1,), comparable_frames=False, layout_label='Layout')
            self.assertEqual(path.read_text(), 'existing evidence')


if __name__ == '__main__':
    unittest.main()
