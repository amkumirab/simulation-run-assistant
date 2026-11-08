import copy
import json
import tempfile
import unittest
from pathlib import Path

from test_geometry_inspector import snapshot
from simulation_assistant.geometry_files import (
    load_snapshot, read_snapshot_document, save_snapshot, snapshot_document,
)


class SnapshotDocumentTests(unittest.TestCase):
    def test_document_roundtrip_does_not_mutate_input_and_matches_saved_v1(self):
        document = snapshot_document(snapshot())
        before = copy.deepcopy(document)
        self.assertEqual(read_snapshot_document(document), snapshot())
        self.assertEqual(document, before)
        with tempfile.TemporaryDirectory() as folder:
            path = save_snapshot(Path(folder)/'snapshot.json', snapshot())
            self.assertEqual(document, json.loads(path.read_text()))

    def test_existing_real_snapshots_keep_their_checksums(self):
        folder = Path(__file__).resolve().parents[1]/'examples/saved_geometry_wpt'
        for path in folder.glob('*.json'):
            with self.subTest(path=path.name):
                self.assertEqual(snapshot_document(load_snapshot(path)), json.loads(path.read_text()))


if __name__ == '__main__':
    unittest.main()
