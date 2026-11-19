import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_sensor_limit_checks import real_overlay
from test_sensor_profiles import hypothetical_profile
from simulation_assistant.sensor_limit_checks import assess_sensor_limits
from simulation_assistant.sensor_limit_reports import assessment_document, save_sensor_assessment


class SensorLimitReportTests(unittest.TestCase):
    def setUp(self):
        self.result = assess_sensor_limits(hypothetical_profile(), real_overlay(), sampled_field='charging-coil-ac',
                                          dc_bias_t=None, conditions_confirmed=True)

    def test_report_embeds_profile_assumptions_exact_states_and_unavailable_values(self):
        document = assessment_document(self.result)
        self.assertEqual(document['schema'], 'wpt.sensor-limit-report.v1')
        self.assertEqual(document['profile']['basis'], 'hypothetical')
        self.assertIn('ASSUMPTION', document['scope'])
        self.assertIsNone(document['context']['dc_bias_t'])
        self.assertIsNone(document['rows'][0]['minimum_t'])
        self.assertEqual(document['sources']['current']['state']['inner'], 1)
        self.assertEqual(document['sources']['csv_sha256'], self.result.overlay.bundle.data.source_sha256)
        self.assertEqual(len(document['rows']), 18)
        self.assertNotIn('model_path', json.dumps(document))
        self.assertNotIn('C:\\', json.dumps(document))

    def test_tampered_results_are_recomputed_not_blindly_exported(self):
        for result in (replace(self.result, rows=()), replace(self.result, conditions_confirmed=False),
                       replace(self.result, profile=replace(self.result.profile, name='Changed'))):
            with self.assertRaises(ValueError):
                assessment_document(result)

    def test_atomic_export_rejects_wrong_suffix_and_preserves_file_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'assessment.json'
            save_sensor_assessment(path, self.result)
            raw = path.read_bytes()
            with patch('simulation_assistant.geometry_files.os.replace', side_effect=OSError('storage unavailable')):
                with self.assertRaises(OSError):
                    save_sensor_assessment(path, self.result)
            self.assertEqual(path.read_bytes(), raw)
            with self.assertRaises(ValueError):
                save_sensor_assessment(path.with_suffix('.mph'), self.result)


if __name__ == '__main__':
    unittest.main()
