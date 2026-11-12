import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import test_sensor_field_overlay as overlay_tests
from simulation_assistant.field_samples import Sensor
from simulation_assistant.sensor_field_views import overlay_label, overlay_svg, save_overlay_svg


class SensorFieldViewTests(unittest.TestCase):
    def setUp(self):
        self.inputs = overlay_tests.SensorFieldOverlayTests()
        self.inputs.setUp()
        self.overlay = self.inputs.analyze()

    def test_svg_has_exact_sources_states_components_and_both_views_without_paths(self):
        text = overlay_svg(self.overlay, (1,), layout_label='Copied layout', selected_sensor='S5')
        root = ET.fromstring(text)
        ns = {'s': 'http://www.w3.org/2000/svg'}
        evidence = json.loads(root.find('s:metadata', ns).text)
        self.assertEqual(evidence['schema'], 'wpt.sensor-field-overlay.v1')
        self.assertTrue(evidence['geometry_matches_state'])
        self.assertEqual(evidence['current']['model_sha256'], self.overlay.current_source.model_sha256)
        self.assertEqual(evidence['reference']['state']['dataset'], 'dset1')
        self.assertEqual(evidence['readings'][4]['current_components_t'][2][0], self.overlay.readings[4].projected_t.real)
        self.assertEqual(len(root.findall('s:g', ns)), 2)
        self.assertIn('Current geometry only', text)
        self.assertIn('Not calibrated MTJ', text)
        self.assertNotIn('C:\\', text)
        self.assertNotIn('href=', text)
        self.assertIn('36.4984', overlay_label(self.overlay.readings[4]))
        self.assertIn('-1.03108', overlay_label(self.overlay.readings[4]))

    def test_missing_status_is_explicit_in_labels_numeric_table_and_metadata(self):
        overlay = self.inputs.analyze(sensors=(Sensor('Missing', (0., 0., 0.), (0., 0., 1.)),))
        self.assertIn('missing point', overlay_label(overlay.readings[0]))
        text = overlay_svg(overlay, (1,), layout_label='Copied layout')
        root = ET.fromstring(text)
        meta = json.loads(root.find('{http://www.w3.org/2000/svg}metadata').text)
        self.assertIsNone(meta['readings'][0]['current_components_t'])
        self.assertIsNone(meta['readings'][0]['amplitude_change_t'])
        self.assertIn('unavailable', text)

    def test_export_recomputes_result_and_rejects_invalid_domains_or_selected_sensor(self):
        for options in (dict(domains=()), dict(domains=(1,), selected_sensor='Unknown')):
            with self.assertRaises(ValueError):
                overlay_svg(self.overlay, layout_label='Copy', **options)
        tampered = replace(self.overlay, readings=())
        with self.assertRaises(ValueError):
            overlay_svg(tampered, (1,), layout_label='Copy')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'overlay.svg'
            save_overlay_svg(path, self.overlay, (1,), layout_label='Copy')
            self.assertTrue(path.is_file())


if __name__ == '__main__':
    unittest.main()
