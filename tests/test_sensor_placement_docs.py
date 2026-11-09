import re
import struct
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit


class SensorPlacementDocumentationTests(unittest.TestCase):
    def test_guide_links_actual_captures_and_static_example_are_valid(self):
        root = Path(__file__).resolve().parents[1]
        guide = root/'docs/SENSOR_PLACEMENT.md'
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', guide.read_text(encoding='utf-8')):
            link = urlsplit(target)
            if not link.scheme and link.path:
                path = guide.parent/unquote(link.path)
                self.assertTrue(path.is_file(), target)
                if path.suffix == '.png':
                    header = path.read_bytes()[:24]
                    self.assertEqual(header[:8], b'\x89PNG\r\n\x1a\n')
                    self.assertEqual(struct.unpack('>II', header[16:24]), (1240, 850))
        svg = ET.parse(root/'docs/images/sensor-placement/sensor-placement-original.svg')
        self.assertIn('ILLUSTRATIVE', ''.join(svg.getroot().itertext()))
        self.assertEqual(len(svg.findall('{http://www.w3.org/2000/svg}g')), 2)


if __name__ == '__main__':
    unittest.main()
