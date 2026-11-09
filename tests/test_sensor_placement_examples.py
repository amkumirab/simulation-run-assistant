import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SensorPlacementExampleTests(unittest.TestCase):
    def test_real_saved_geometry_replay_is_bounded_and_does_not_overwrite_outputs(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            for name in ('original', 'overlap', 'control'):
                command = [sys.executable, '-X', 'utf8', str(root/'examples/replay_sensor_placement.py'),
                           '--geometry', name, '--headless', '--output-dir', folder]
                result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertIn('illustrative sensors', result.stdout)
                path = Path(folder)/('sensor-placement-'+name+'.svg')
                original = path.read_bytes()
                self.assertIn(b'ILLUSTRATIVE', original)
                refused = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=25)
                self.assertNotEqual(refused.returncode, 0)
                self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
