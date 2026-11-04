import unittest
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from simulation_assistant.geometry_files import load_snapshot
from simulation_assistant.geometry_inspector import z_separation


class SavedGeometryExampleTests(unittest.TestCase):
    def test_geometry_guide_and_replay_links_exist(self):
        root = Path(__file__).resolve().parents[1]
        for document in (root/'docs/GEOMETRY_INSPECTOR.md', root/'examples/saved_geometry_wpt/README.md'):
            for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', document.read_text(encoding='utf-8')):
                link = urlsplit(target)
                if not link.scheme and link.path:
                    self.assertTrue((document.parent/unquote(link.path)).is_file(), target)

    def test_real_saved_models_preserve_layout_differences(self):
        folder = Path(__file__).resolve().parents[1]/'examples'/'saved_geometry_wpt'
        for name, left_xmin, left_zmin in (('original', -.380, .155), ('overlap', -.240, .175), ('control', -.380, .175)):
            with self.subTest(model=name):
                data = load_snapshot(folder/(name+'.json'))
                self.assertEqual(len(data.parts), 13)
                parts = {p.domain: p for p in data.parts}
                self.assertIn('wpt_air', parts[1].selections)
                self.assertIn('mr_left_diff_dom', parts[4].selections)
                self.assertAlmostEqual(parts[4].bounds_m[0], left_xmin, places=6)
                self.assertAlmostEqual(parts[4].bounds_m[4], left_zmin, places=6)
                self.assertAlmostEqual(z_separation(parts[9], parts[10], True), .150, places=6)
                self.assertIsNone(z_separation(parts[9], parts[10], False))
                self.assertEqual(data.length_unit, 'm')


if __name__ == '__main__':
    unittest.main()
