import re
import struct
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from simulation_assistant.geometry_files import load_snapshot
from simulation_assistant.saved_field_bundles import load_saved_field_bundle


class SensorFieldDocumentationTests(unittest.TestCase):
    def test_guide_links_and_actual_native_capture_dimensions(self):
        root = Path(__file__).resolve().parents[1]
        guide = root/'docs/SENSOR_FIELD_OVERLAY.md'
        content = guide.read_text(encoding='utf-8')
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', content):
            link = urlsplit(target)
            if not link.scheme and link.path:
                path = guide.parent/unquote(link.path)
                self.assertTrue(path.is_file(), target)
                if path.suffix == '.png':
                    header = path.read_bytes()[:24]
                    self.assertEqual(header[:8], b'\x89PNG\r\n\x1a\n')
                    self.assertEqual(struct.unpack('>II', header[16:24]), (1240, 850))
        for term in ('--confirm-frame-and-state', 'historical', 'unavailable', 'not calibrated', 'without geometry build'):
            self.assertIn(term, content)

    def test_real_geometry_sources_match_scenarios_and_rx_offset_is_retained(self):
        fixture = Path(__file__).resolve().parents[1]/'examples/saved_field_wpt'
        bundle = load_saved_field_bundle(fixture)
        snapshots = [load_snapshot(fixture/f'geometry-position-{i}.json') for i in (1, 2)]
        for source, geometry in zip(bundle.sources, snapshots):
            self.assertEqual(source.model_sha256, geometry.source_sha256)
            self.assertEqual(len(geometry.parts), 7)
        a, b = (g.parts[6].bounds_m for g in snapshots)
        self.assertAlmostEqual(((b[0]+b[1])-(a[0]+a[1]))/2, .03, places=7)
        self.assertEqual(a[4:], b[4:])


if __name__ == '__main__':
    unittest.main()
