import hashlib
import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from simulation_assistant.saved_field_bundles import load_saved_field_bundle
from simulation_assistant.comsol_field_sampling import FieldExtraction, _field_csv, save_source_bundle
from simulation_assistant.field_sample_files import save_field_workspace
from simulation_assistant.field_samples import FieldMetadata

FIXTURE = Path(__file__).resolve().parents[1]/'examples/saved_field_wpt'


class SavedFieldBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)/'bundle'
        shutil.copytree(FIXTURE, self.folder)

    def evidence(self):
        return json.loads((self.folder/'evidence.json').read_text())

    def write_evidence(self, data):
        (self.folder/'evidence.json').write_text(json.dumps(data), encoding='utf-8')

    def test_real_campaign_maps_each_scenario_to_its_exact_model_and_state(self):
        result = load_saved_field_bundle(self.folder)
        self.assertEqual(result.data.scenarios, ('Position 1', 'Position 2'))
        self.assertEqual(len(result.sensors), 9)
        self.assertEqual(tuple(s.scenario for s in result.sources), result.data.scenarios)
        self.assertEqual(result.sources[0].model_sha256, self.evidence()['sources'][0]['model_sha256'])
        state = result.sources[1].state
        self.assertEqual((state.dataset, state.solver, state.outer, state.inner), ('dset1', 'sol1', 1, 1))
        self.assertEqual(result.evidence_sha256, hashlib.sha256((self.folder/'evidence.json').read_bytes()).hexdigest())

    def test_single_source_bundle_written_by_existing_sampler_roundtrips(self):
        loaded = load_saved_field_bundle(self.folder)
        evidence = self.evidence()['sources'][0]
        raw = _field_csv(tuple(s for s in loaded.data.samples if s.scenario == 'Position 1'))
        data = replace(loaded.data, metadata=FieldMetadata(**evidence['metadata']),
                       samples=tuple(s for s in loaded.data.samples if s.scenario == 'Position 1'),
                       source_sha256=hashlib.sha256(raw).hexdigest())
        extraction = FieldExtraction(data, loaded.sensors, raw, evidence)
        target = save_source_bundle(Path(self.temp.name), extraction)
        result = load_saved_field_bundle(target)
        self.assertEqual(result.data, data)
        self.assertEqual(result.sources, loaded.sources[:1])

    def test_semantic_workspace_disagreement_is_rejected_even_with_updated_file_hash(self):
        loaded = load_saved_field_bundle(self.folder)
        sample = replace(loaded.data.samples[0], field=(1j, 0j, 0j))
        save_field_workspace(self.folder/'workspace.json', replace(loaded.data, samples=(sample,)+loaded.data.samples[1:]), loaded.sensors)
        evidence = self.evidence()
        evidence['workspace_sha256'] = hashlib.sha256((self.folder/'workspace.json').read_bytes()).hexdigest()
        self.write_evidence(evidence)
        with self.assertRaises(ValueError):
            load_saved_field_bundle(self.folder)

    def test_marker_and_leaf_symlink_are_rejected(self):
        marker = self.folder/'COMPLETE'
        raw = marker.read_bytes()
        marker.write_bytes(b'Incomplete')
        with self.assertRaises(ValueError):
            load_saved_field_bundle(self.folder)
        marker.write_bytes(raw)
        outside = Path(self.temp.name)/'outside.csv'
        csv = self.folder/'fields.csv'
        csv.replace(outside)
        try:
            csv.symlink_to(outside)
        except OSError:
            # Windows may forbid creating symlinks; the marker assertion above still ran.
            outside.replace(csv)
            return
        with self.assertRaises(ValueError):
            load_saved_field_bundle(self.folder)

    def test_individual_source_hash_and_semantic_tampering_are_rejected(self):
        original = self.evidence()
        for key, value in (('model_sha256', '0'*64), ('source_csv_sha256', '0'*64),
                           ('new_solve', True), ('extrapolation', True), ('phase_rotation_deg', 90),
                           ('method', 'Unspecified'), ('unexpected', 'value')):
            data = json.loads(json.dumps(original))
            data['sources'][0][key] = value
            self.write_evidence(data)
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_saved_field_bundle(self.folder)

    def test_unknown_duplicate_or_wrong_frequency_state_is_rejected(self):
        original = self.evidence()
        for key, value in (('scenario', 'Unknown'), ('outer', True), ('inner', 0), ('frequency_hz', 84000),
                           ('dataset', 'bad/tag'), ('parameters', 'bad\nline'), ('extra', 1)):
            data = json.loads(json.dumps(original))
            data['sources'][0]['states'][0][key] = value
            self.write_evidence(data)
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_saved_field_bundle(self.folder)
        data = json.loads(json.dumps(original))
        data['sources'][1]['states'][0]['scenario'] = 'Position 1'
        self.write_evidence(data)
        with self.assertRaises(ValueError):
            load_saved_field_bundle(self.folder)

    def test_incompatible_source_metadata_expressions_and_layout_are_rejected(self):
        original = self.evidence()
        for key, value in (('frequency_hz', 84000), ('excitation', 'Different TX'),
                           ('phase_reference', 'Other phase'), ('phasor_convention', 'rms'), ('coordinate_frame', 'Rotated frame')):
            data = json.loads(json.dumps(original))
            data['sources'][1]['metadata'][key] = value
            self.write_evidence(data)
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_saved_field_bundle(self.folder)
        data = json.loads(json.dumps(original))
        data['sources'][0]['expressions'] = ['other.Bx', 'other.By', 'other.Bz']
        self.write_evidence(data)
        with self.assertRaises(ValueError):
            load_saved_field_bundle(self.folder)
        data = json.loads(json.dumps(original))
        data['sources'][0]['sensors'][0]['position_m'][0] += .01
        self.write_evidence(data)
        with self.assertRaises(ValueError):
            load_saved_field_bundle(self.folder)

    def test_raw_file_corruption_and_missing_completion_are_rejected(self):
        for name in ('fields.csv', 'workspace.json'):
            path = self.folder/name
            original = path.read_bytes()
            path.write_bytes(original+b' ')
            with self.subTest(name=name), self.assertRaises(ValueError):
                load_saved_field_bundle(self.folder)
            path.write_bytes(original)
        (self.folder/'COMPLETE').unlink()
        with self.assertRaises((ValueError, OSError)):
            load_saved_field_bundle(self.folder)

    def test_duplicate_unknown_nonfinite_and_oversized_evidence_are_rejected(self):
        original = (self.folder/'evidence.json').read_text()
        for raw in (original.replace('"schema":', '"schema":"duplicate","schema":', 1),
                    original.replace('85000.0', 'NaN', 1), '{}', '['*1500+']'*1500, ' '*500_001):
            (self.folder/'evidence.json').write_text(raw, encoding='utf-8')
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                load_saved_field_bundle(self.folder)
        data = json.loads(original)
        data['model_path'] = 'unexpected.mph'
        self.write_evidence(data)
        with self.assertRaises(ValueError):
            load_saved_field_bundle(self.folder)


if __name__ == '__main__':
    unittest.main()
