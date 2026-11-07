import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from test_geometry_inspector import snapshot
from simulation_assistant.geometry_files import save_snapshot, snapshot_digest


class GeometrySnapshotDigestTests(unittest.TestCase):
    def test_digest_matches_the_portable_snapshot_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            path = save_snapshot(Path(directory)/'snapshot.json', snapshot())
            self.assertEqual(snapshot_digest(snapshot()), json.loads(path.read_text())['snapshot_sha256'])

    def test_digest_covers_snapshot_content_not_only_the_model_hash(self):
        original = snapshot()
        altered = replace(original, parts=tuple(reversed(original.parts)))
        self.assertEqual(altered.source_sha256, original.source_sha256)
        self.assertNotEqual(snapshot_digest(altered), snapshot_digest(original))


if __name__ == '__main__':
    unittest.main()
