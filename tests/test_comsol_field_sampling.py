import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from simulation_assistant.comsol_field_sampling import (
    SavedState, FieldSelection, read_catalog, validate_selection, extract_saved_fields, _engine,
    SavedScenario, extract_scenarios, save_source_bundle,
)
from simulation_assistant.field_samples import Sensor


class SavedFieldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'source.mph'
        self.model.write_bytes(b'unchanged model fixture')
        self.sha = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.state = SavedState('dset1', 'sol1', 1, 2, 85000., 'freq=85000 Hz')
        self.selection = FieldSelection(self.sha, (('Aligned', self.state),),
                                        ('mf.Bx', 'mf.By', 'mf.Bz'), 'peak', 'TX 1 A peak', 'TX phase zero')
        self.sensors = (Sensor('S1', (0., 0., .01), (0., 0., 1.)),)

    def test_catalog_preserves_explicit_state_and_frequency(self):
        raw = b'dataset\tsolver\touter\tinner\tfrequency_hz\tparameters\ndset1\tsol1\t1\t2\t85000\tfreq=85000 Hz\n'
        self.assertEqual(read_catalog(raw), (self.state,))

    def test_catalog_rejects_duplicates_nonfinite_and_bad_shapes(self):
        header = b'dataset\tsolver\touter\tinner\tfrequency_hz\tparameters\n'
        row = b'dset1\tsol1\t1\t2\t85000\tfreq=85000 Hz\n'
        for raw in (header, header+row+row, header+row.replace(b'85000\t', b'nan\t'), header+row+b'extra\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                read_catalog(raw)

    def test_selection_blocks_expression_injection_and_mixed_frequencies(self):
        for selection in (replace(self.selection, expressions=('mf.Bx;quit()', 'mf.By', 'mf.Bz')),
                          replace(self.selection, states=(('Aligned', self.state), ('Other', replace(self.state, frequency_hz=1.)))),
                          replace(self.selection, states=(('Aligned', replace(self.state, inner=0)),)),
                          replace(self.selection, model_sha256='bad')):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                validate_selection(selection, self.sensors)

    def test_extraction_keeps_complex_fields_and_source_evidence(self):
        raw = b'scenario\tpoint_id\tbx_real\tbx_imag\tby_real\tby_imag\tbz_real\tbz_imag\nAligned\tS1\t1e-6\t2e-6\t0\t0\t3e-6\t-4e-6\n'
        with patch('simulation_assistant.comsol_field_sampling._engine', return_value=raw):
            result = extract_saved_fields(self.model, Path('engine'), self.selection, self.sensors)
        self.assertEqual(result.data.samples[0].field[2], 3e-6-4e-6j)
        self.assertEqual(result.evidence['model_sha256'], self.sha)
        self.assertEqual(result.evidence['states'][0]['inner'], 2)
        self.assertNotIn(str(self.root), str(result.evidence))
        self.assertEqual(hashlib.sha256(self.model.read_bytes()).hexdigest(), self.sha)

    def test_stale_model_is_rejected_before_engine_starts(self):
        self.model.write_bytes(b'changed')
        with patch('simulation_assistant.comsol_field_sampling._engine') as engine:
            with self.assertRaisesRegex(ValueError, 'changed'):
                extract_saved_fields(self.model, Path('engine'), self.selection, self.sensors)
        engine.assert_not_called()

    def test_engine_uses_stdout_without_weakening_file_security_preferences(self):
        import subprocess
        executable = self.root / 'comsolbatch.exe'
        executable.touch()
        (self.root/'comsolcompile.exe').touch()
        raw = 'dataset\tsolver\touter\tinner\tfrequency_hz\tparameters\ndset1\tsol1\t1\t2\t85000\tfreq=85000 Hz; FIELD_SAMPLING_OK=1\n'
        def run(command, **kwargs):
            if 'comsolcompile' in command[0]:
                Path(command[1]).with_suffix('.class').touch()
                return subprocess.CompletedProcess(command, 0, '', '')
            self.assertIn('-nosave', command)
            self.assertNotIn('-outputfile', command)
            self.assertNotIn('-prefsdir', command)
            import base64, gzip
            self.assertEqual(gzip.decompress(base64.b64decode(command[-3])), b'')
            self.assertEqual(gzip.decompress(base64.b64decode(command[-1])), b'')
            self.assertNotEqual(Path(command[-5]), self.model)
            self.assertEqual(Path(command[-5]).read_bytes(), self.model.read_bytes())
            return subprocess.CompletedProcess(command, 0, 'FIELD_SAMPLING_BEGIN\n'+raw+'FIELD_SAMPLING_OK\n', '')
        with patch('simulation_assistant.comsol_field_sampling.run_cancellable_process', side_effect=run):
            self.assertEqual(_engine(self.model, executable, 'catalog', expected_sha256=self.sha), raw.encode())

    def test_unavailable_incomplete_duplicate_or_wrong_point_rejects_entire_result(self):
        header = b'scenario\tpoint_id\tbx_real\tbx_imag\tby_real\tby_imag\tbz_real\tbz_imag\n'
        row = b'Aligned\tS1\t1\t2\t0\t0\t3\t4\n'
        for raw in (header, header+row+row, header+row.replace(b'S1', b'Other'), header+row.replace(b'1\t2', b'NaN\t2')):
            with self.subTest(raw=raw), patch('simulation_assistant.comsol_field_sampling._engine', return_value=raw):
                with self.assertRaises(ValueError):
                    extract_saved_fields(self.model, Path('engine'), self.selection, self.sensors)

    def test_multiple_models_keep_independent_provenance_and_portable_bundle(self):
        import json
        from simulation_assistant.field_sample_files import load_field_workspace
        rows = b'scenario\tpoint_id\tbx_real\tbx_imag\tby_real\tby_imag\tbz_real\tbz_imag\n'
        scenarios = (SavedScenario('Aligned', self.model, self.sha, self.state),
                     SavedScenario('Offset', self.model, self.sha, self.state))
        with patch('simulation_assistant.comsol_field_sampling._engine', side_effect=[
                rows+b'Aligned\tS1\t1\t2\t0\t0\t3\t4\n', rows+b'Offset\tS1\t1\t2\t0\t0\t5\t6\n']):
            result = extract_scenarios(scenarios, Path('engine'), self.selection.expressions,
                                      self.sensors, 'peak', 'TX 1 A peak', 'TX phase zero')
        self.assertEqual(result.data.scenarios, ('Aligned', 'Offset'))
        self.assertEqual(len(result.evidence['sources']), 2)
        target = save_source_bundle(self.root, result)
        self.assertTrue((target/'COMPLETE').is_file())
        loaded, sensors = load_field_workspace(target/'workspace.json')
        self.assertEqual((loaded, sensors), (result.data, self.sensors))
        evidence = json.loads((target/'evidence.json').read_text())
        self.assertEqual(evidence['source_csv_sha256'], hashlib.sha256((target/'fields.csv').read_bytes()).hexdigest())
        self.assertEqual(evidence['workspace_sha256'], hashlib.sha256((target/'workspace.json').read_bytes()).hexdigest())

    def test_changed_model_during_engine_work_rejects_output(self):
        def engine(*args, **kwargs):
            self.model.write_bytes(b'changed during read')
            return b''
        with patch('simulation_assistant.comsol_field_sampling._engine', side_effect=engine):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                extract_saved_fields(self.model, Path('engine'), self.selection, self.sensors)

    def test_bundle_refuses_mismatching_csv_before_creating_directory(self):
        from simulation_assistant.comsol_field_sampling import FieldExtraction
        from test_field_samples import dataset
        before = set(self.root.iterdir())
        with self.assertRaises(ValueError):
            save_source_bundle(self.root, FieldExtraction(dataset(), self.sensors, b'not matching data', {}))
        self.assertEqual(set(self.root.iterdir()), before)

    def test_engine_cancellation_timeout_and_compile_failure_do_not_touch_source(self):
        import subprocess
        from simulation_assistant.types import SimulationCancelled
        executable = self.root/'comsolbatch.exe'
        executable.touch()
        (self.root/'comsolcompile.exe').touch()
        for error in (SimulationCancelled('Stop requested'), subprocess.TimeoutExpired('compiler', 120)):
            with patch('simulation_assistant.comsol_field_sampling.run_cancellable_process', side_effect=error):
                with self.assertRaises(type(error)):
                    _engine(self.model, executable, 'catalog', expected_sha256=self.sha)
        with patch('simulation_assistant.comsol_field_sampling.run_cancellable_process',
                   return_value=subprocess.CompletedProcess([], 1, '', 'fixture compilation failure')):
            with self.assertRaisesRegex(RuntimeError, 'compilation failed'):
                _engine(self.model, executable, 'catalog', expected_sha256=self.sha)
        self.assertEqual(hashlib.sha256(self.model.read_bytes()).hexdigest(), self.sha)


if __name__ == '__main__':
    unittest.main()
