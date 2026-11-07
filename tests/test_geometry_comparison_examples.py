import csv
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class GeometryComparisonExampleTests(unittest.TestCase):
    def test_documented_headless_replays_and_existing_evidence_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            for candidate in ('overlap','control'):
                command=[sys.executable,'-X','utf8',str(ROOT/'examples/replay_geometry_comparison.py'),
                         '--candidate',candidate,'--headless','--output-dir',directory]
                result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=25)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                path=Path(directory)/('original-vs-'+candidate+'.csv')
                with path.open(encoding='utf-8',newline='') as stream:
                    rows=list(csv.DictReader(stream))
                self.assertEqual(len(rows),144)
                self.assertTrue(all(row['baseline_unmapped_domains']=='1' for row in rows))
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                refused=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=25)
                self.assertNotEqual(refused.returncode,0)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)


if __name__=='__main__':
    unittest.main()
