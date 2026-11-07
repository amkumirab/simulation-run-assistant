import csv
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from test_geometry_inspector import snapshot
from simulation_assistant.geometry_comparison import DomainPair, compare_geometry
from simulation_assistant.geometry_comparison_files import export_comparison_csv
from simulation_assistant.geometry_files import snapshot_digest


class GeometryComparisonFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        data = snapshot()
        self.result = compare_geometry(data, data, (DomainPair('=TX',1,1),), comparable_frames=True)

    def test_csv_contains_exact_metrics_mapping_coverage_and_both_identities(self):
        path = export_comparison_csv(self.folder/'comparison.csv', self.result)
        with path.open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows),12)
        self.assertEqual(rows[0]['schema'],'wpt.geometry-comparison.v1')
        self.assertEqual(rows[0]['pair_label'], "'=TX")
        self.assertEqual(rows[0]['baseline_unmapped_domains'],'2')
        self.assertEqual(rows[0]['baseline_model_sha256'],'a'*64)
        self.assertEqual(rows[0]['baseline_snapshot_sha256'], snapshot_digest(snapshot()))
        self.assertEqual(rows[0]['comparable_frames_declared'],'True')
        self.assertTrue(all(float(row['delta_mm']) == 0 and row['state'] == 'within_threshold' for row in rows))
        self.assertNotIn(str(self.folder), path.read_text())

    def test_modified_result_or_false_declaration_cannot_be_exported(self):
        metric = replace(self.result.differences[0].metrics[0], delta_mm=99)
        difference = replace(self.result.differences[0], metrics=(metric,*self.result.differences[0].metrics[1:]))
        for result in (replace(self.result,differences=(difference,)), replace(self.result,comparable_frames=False),
                       replace(self.result,baseline_unmapped=())):
            with self.subTest(result=result), self.assertRaises(ValueError):
                export_comparison_csv(self.folder/'bad.csv',result)
        self.assertFalse((self.folder/'bad.csv').exists())

    def test_wrong_suffix_and_atomic_failure_preserve_existing_file(self):
        path = self.folder/'comparison.csv'
        path.write_text('existing report')
        with self.assertRaises(ValueError):
            export_comparison_csv(self.folder/'research.mph',self.result)
        with patch('simulation_assistant.geometry_files.os.replace',side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                export_comparison_csv(path,self.result)
        self.assertEqual(path.read_text(),'existing report')
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['comparison.csv'])


if __name__ == '__main__':
    unittest.main()
