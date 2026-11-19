import re
import struct
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from simulation_assistant.sensor_profile_files import load_sensor_profile


class SensorProfileDocumentationTests(unittest.TestCase):
    def test_guide_links_native_captures_and_scientific_boundaries_are_explicit(self):
        root = Path(__file__).resolve().parents[1]
        guide = root/'docs/SENSOR_PROFILES.md'
        content = guide.read_text(encoding='utf8')
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', content):
            link = urlsplit(target)
            if not link.scheme and link.path:
                path = guide.parent/unquote(link.path)
                self.assertTrue(path.is_file(), target)
                if path.suffix == '.png':
                    raw = path.read_bytes()[:24]
                    self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')
                    self.assertEqual(struct.unpack('>II', raw[16:24]), (1240, 900))
        for term in ('hypothetical', '--confirm-assumptions', 'not zero', 'not real sensor specifications', 'Sensitivity/noise'):
            self.assertIn(term, content)

    def test_portable_examples_never_impersonate_a_physical_device(self):
        root = Path(__file__).resolve().parents[1]/'examples/sensor_profiles'
        for path in root.glob('*.json'):
            profile = load_sensor_profile(path)
            self.assertEqual(profile.basis, 'hypothetical')
            self.assertEqual(profile.device, '')
            self.assertIsNone(profile.noise)
            self.assertIsNone(profile.sensitivity)
        blank = load_sensor_profile(root/'blank-hypothetical.json')
        self.assertIsNone(blank.field)
        self.assertIsNone(blank.frequency)
        self.assertEqual(blank.target_field, 'unknown')


if __name__ == '__main__':
    unittest.main()
