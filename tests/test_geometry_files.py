import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from test_geometry_inspector import snapshot
from simulation_assistant.geometry_files import save_snapshot, load_snapshot, brief_from_geometry, export_geometry_csv
from simulation_assistant.model_briefs import validate_brief


class GeometryFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'geometry.json'

    def test_exact_round_trip_and_corruption_rejection(self):
        data = snapshot()
        save_snapshot(self.path, data)
        self.assertEqual(load_snapshot(self.path), data)
        document = json.loads(self.path.read_text())
        document['parts'][0]['bounds_m'][1] += .01
        self.path.write_text(json.dumps(document))
        with self.assertRaises(ValueError):
            load_snapshot(self.path)

    def test_oversize_wrong_schema_duplicate_keys_and_shapes_rejected(self):
        for raw in (' '*1_000_001, '{}', '[]', '{"schema":1,"schema":2}', '['*1100+']'*1100):
            with self.subTest(raw=raw[:20]), self.assertRaises(ValueError):
                self.path.write_text(raw)
                load_snapshot(self.path)

    def test_generated_brief_is_explicit_proposal_bound_to_source(self):
        data = snapshot()
        brief = brief_from_geometry(data, (1, 2), 'Geometry review', 'draft')
        validate_brief(brief)
        self.assertEqual(brief.model_sha256, data.source_sha256)
        self.assertEqual(len(brief.entries), 12)
        self.assertEqual({e.status for e in brief.entries}, {'proposed'})
        self.assertTrue(all(e.source and not e.reviewed_on for e in brief.entries))
        with self.assertRaises(ValueError):
            brief_from_geometry(data, (99,), 'Geometry review', 'draft')
        with self.assertRaises(ValueError):
            brief_from_geometry(data, (), 'Geometry review', 'draft')

    def test_csv_is_bounded_and_guards_formula_cells(self):
        import csv
        data = replace(snapshot(), parts=(replace(snapshot().parts[0], selections='=malicious()'),))
        target = self.path.with_suffix('.csv')
        export_geometry_csv(target, data, (1,))
        with target.open(newline='') as stream:
            row = next(csv.DictReader(stream))
        self.assertTrue(row['selections'].startswith("'="))
        self.assertEqual(float(row['zmax_mm']), 5.)
        with self.assertRaises(ValueError):
            save_snapshot(self.path.with_suffix('.mph'), snapshot())


if __name__ == '__main__':
    unittest.main()
