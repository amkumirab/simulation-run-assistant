import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SensorFieldExampleTests(unittest.TestCase):
    def test_real_saved_field_geometry_pairs_replay_only_with_explicit_declarations(self):
        root = Path(__file__).resolve().parents[1]
        script = root/'examples/replay_sensor_field_overlay.py'
        with tempfile.TemporaryDirectory() as folder:
            for current in ('1', '2'):
                command = [sys.executable, '-X', 'utf8', str(script), '--headless', '--current', current,
                           '--output-dir', folder]
                blocked = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=25)
                self.assertNotEqual(blocked.returncode, 0)
                command.append('--confirm-frame-and-state')
                result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertIn('9 available readings', result.stdout)
                self.assertIn('No COMSOL process', result.stdout)
                path = Path(folder)/('sensor-field-position-'+current+'.svg')
                raw = path.read_bytes()
                refused = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=25)
                self.assertNotEqual(refused.returncode, 0)
                self.assertEqual(path.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
