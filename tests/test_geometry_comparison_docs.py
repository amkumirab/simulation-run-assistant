import re
import struct
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


class GeometryComparisonDocumentationTests(unittest.TestCase):
    def test_guide_links_and_native_png_dimensions(self):
        guide = Path(__file__).resolve().parents[1]/'docs/GEOMETRY_COMPARISON.md'
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', guide.read_text(encoding='utf-8')):
            link = urlsplit(target)
            if not link.scheme and link.path:
                path = guide.parent/unquote(link.path)
                self.assertTrue(path.is_file(), target)
                if path.suffix == '.png':
                    with path.open('rb') as stream:
                        header = stream.read(24)
                    self.assertEqual(header[:8], b'\x89PNG\r\n\x1a\n')
                    self.assertEqual(struct.unpack('>II', header[16:24]), (1240, 850))


if __name__ == '__main__':
    unittest.main()
