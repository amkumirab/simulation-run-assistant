import contextlib
import csv
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'examples/replay_saved_comsol_fields.py'
FIXTURE = ROOT / 'examples/saved_field_wpt'


class SavedFieldExampleTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('saved_field_replay', SCRIPT)
        self.example = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.example)

    def test_checked_in_result_preserves_complex_fields_and_reference_delta(self):
        from simulation_assistant.field_samples import analyze_field_samples
        result = self.example.read_bundle(FIXTURE)
        self.assertEqual(len(result.sensors), 9)
        self.assertEqual(len(result.data.samples), 18)
        self.assertEqual(result.data.metadata.source_kind, 'comsol-export')
        self.assertTrue(any(v.imag for sample in result.data.samples for v in sample.field))
        readings = analyze_field_samples(result.data, result.sensors, 'Position 2', 'Position 1')
        center = next(row for row in readings if row.sensor.point_id == 'S5')
        self.assertAlmostEqual(center.amplitude_change_t*1e6, -1.0310806216, places=8)
        self.assertFalse(result.evidence['new_solve'])
        self.assertEqual(len(result.evidence['sources']), 2)

    def test_missing_marker_and_corrupted_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in ('COMPLETE', 'fields.csv', 'workspace.json', 'evidence.json'):
                with self.subTest(file=name):
                    target = Path(temporary)/name.replace('.', '-')
                    shutil.copytree(FIXTURE, target)
                    path = target/name
                    if name == 'COMPLETE':
                        path.unlink()
                    else:
                        path.write_bytes(path.read_bytes()+b'corruption')
                    with self.assertRaises(ValueError):
                        self.example.read_bundle(target)

    def test_valid_but_mismatching_workspace_is_rejected(self):
        from dataclasses import replace
        from simulation_assistant.field_sample_files import save_field_workspace
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'bundle'
            shutil.copytree(FIXTURE, target)
            result = self.example.read_bundle(target)
            changed = replace(result.data.samples[0], field=(0j, 0j, 0j))
            save_field_workspace(target/'workspace.json',
                                 replace(result.data, samples=(changed, *result.data.samples[1:])), result.sensors)
            evidence = json.loads((target/'evidence.json').read_text())
            evidence['workspace_sha256'] = hashlib.sha256((target/'workspace.json').read_bytes()).hexdigest()
            (target/'evidence.json').write_text(json.dumps(evidence))
            with self.assertRaisesRegex(ValueError, 'CSV and workspace'):
                self.example.read_bundle(target)

    def test_oversized_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'bundle'
            shutil.copytree(FIXTURE, target)
            (target/'evidence.json').write_bytes(b' '*500_001)
            with self.assertRaisesRegex(ValueError, 'size'):
                self.example.read_bundle(target)

    def test_duplicate_evidence_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'bundle'
            shutil.copytree(FIXTURE, target)
            path = target/'evidence.json'
            raw = path.read_text()
            path.write_text(raw.replace('"new_solve": false,', '"new_solve": false, "new_solve": false,', 1))
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                self.example.read_bundle(target)

    def test_invalid_evidence_shape_and_changed_metadata_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            for index, change in enumerate(([], {'schema': 'other'}, {'new_solve': True},
                                            {'metadata': {}}, {'sources': []})):
                with self.subTest(change=change):
                    target = Path(temporary)/str(index)
                    shutil.copytree(FIXTURE, target)
                    evidence = json.loads((target/'evidence.json').read_text())
                    evidence = {**evidence, **change} if isinstance(change, dict) else change
                    (target/'evidence.json').write_text(json.dumps(evidence))
                    with self.assertRaises(ValueError):
                        self.example.read_bundle(target)

    def test_headless_and_native_flags_are_mutually_exclusive(self):
        for flag in ('--desktop', '--capture-dir'):
            arguments = ['--headless', flag] + (['capture'] if flag == '--capture-dir' else [])
            with self.subTest(flag=flag), patch.object(self.example, 'read_bundle') as read, \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.example.main(arguments)
            read.assert_not_called()

    def test_headless_replay_uses_no_engine_or_production_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'results'
            output.mkdir()
            with patch('simulation_assistant.comsol_field_sampling._engine') as engine, \
                    patch('simulation_assistant.storage.JobStore') as database, \
                    contextlib.redirect_stdout(io.StringIO()) as transcript:
                self.example.main(['--headless', '--output-dir', str(output)])
            engine.assert_not_called()
            database.assert_not_called()
            self.assertIn('STORED COMSOL RESULT REPLAY', transcript.getvalue())
            report = next(output.glob('saved-field-*/comparison.csv'))
            with report.open(newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 9)
            self.assertTrue(all(row['status'] == 'available' for row in rows))

    def test_optimized_python_keeps_integrity_checks_enabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)/'bundle'
            shutil.copytree(FIXTURE, target)
            (target/'fields.csv').write_bytes(b'not a field CSV')
            run = subprocess.run([sys.executable, '-O', str(SCRIPT), str(target), '--headless'],
                                 cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertNotIn('PASS:', run.stdout)
            self.assertNotIn('Traceback', run.stderr)


if __name__ == '__main__':
    unittest.main()
