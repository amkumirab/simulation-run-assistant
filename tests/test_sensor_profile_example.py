import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import json


class SensorProfileExampleTests(unittest.TestCase):
    def test_offline_replay_has_explicit_assumptions_and_all_three_outcomes(self):
        root = Path(__file__).resolve().parents[1]
        script = root/'examples/replay_sensor_profiles.py'
        with tempfile.TemporaryDirectory() as folder:
            for case, expected in (('wide', 'within declared limits'), ('narrow', 'outside declared limits'),
                                   ('unknown', 'insufficient information')):
                command = [sys.executable, '-X', 'utf8', str(script), '--headless', '--case', case, '--output-dir', folder]
                blocked = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=25)
                self.assertNotEqual(blocked.returncode, 0)
                command.append('--confirm-assumptions')
                result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                report = Path(folder)/('assessment-'+case+'.json')
                raw = report.read_bytes()
                data = json.loads(raw)
                self.assertEqual(data['profile']['basis'], 'hypothetical')
                self.assertIn(expected, {r['status'] for r in data['rows']})
                self.assertIn('No COMSOL process', result.stdout)
                self.assertIn('ASSUMPTION', result.stdout)
                refused = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=25)
                self.assertNotEqual(refused.returncode, 0)
                self.assertEqual(report.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
