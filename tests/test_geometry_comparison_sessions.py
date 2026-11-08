import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_geometry_inspector import snapshot
from simulation_assistant.geometry_comparison import DomainPair, compare_geometry
from simulation_assistant.geometry_files import _digest
from simulation_assistant.geometry_comparison_sessions import (
    GeometryComparisonSession, load_session, save_session,
)


class GeometryComparisonSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'comparison-session.json'
        self.session = GeometryComparisonSession(snapshot(), snapshot(), (DomainPair('TX', 1, 2),), .125)

    def document(self):
        save_session(self.path, self.session)
        return json.loads(self.path.read_text())

    def write_document(self, document, *, rehash=True):
        if rehash:
            document.pop('session_sha256', None)
            document['session_sha256'] = _digest(document)
        self.path.write_text(json.dumps(document), encoding='utf-8')

    def test_roundtrip_is_self_contained_and_has_no_result_or_frame_approval(self):
        document = self.document()
        self.assertEqual(load_session(self.path), self.session)
        self.assertEqual(set(document), {'schema', 'baseline', 'candidate', 'pairs', 'tolerance_mm', 'session_sha256'})
        self.assertEqual(document['schema'], 'wpt.geometry-comparison-session.v1')
        self.assertEqual(document['baseline']['source_sha256'], snapshot().source_sha256)
        self.assertIn('snapshot_sha256', document['candidate'])
        self.assertNotIn('path', self.path.read_text())
        self.assertEqual(document['pairs'], [{'label': 'TX', 'baseline_domain': 1, 'candidate_domain': 2}])

    def test_zero_pair_draft_roundtrips_but_cannot_be_compared(self):
        draft = replace(self.session, pairs=())
        save_session(self.path, draft)
        self.assertEqual(load_session(self.path), draft)
        with self.assertRaises(ValueError):
            compare_geometry(draft.baseline, draft.candidate, draft.pairs, comparable_frames=True)

    def test_maximum_mapping_count_and_threshold_endpoints_roundtrip(self):
        source = replace(snapshot(), parts=tuple(replace(snapshot().parts[0], domain=i) for i in range(1, 257)))
        pairs = tuple(DomainPair('Part '+str(i), i, i) for i in range(1, 257))
        for threshold in (0, 1000):
            session = GeometryComparisonSession(source, source, pairs, threshold)
            save_session(self.path, session)
            self.assertEqual(load_session(self.path), session)

    def test_invalid_session_inputs_never_overwrite_existing_target(self):
        self.path.write_text('existing evidence')
        for changes in ({'tolerance_mm': True}, {'tolerance_mm': float('nan')},
                        {'tolerance_mm': float('inf')}, {'tolerance_mm': -1},
                        {'tolerance_mm': 1001}, {'tolerance_mm': 10**400},
                        {'tolerance_mm': '.01'}, {'pairs': []},
                        {'pairs': (DomainPair('TX', True, 1),)},
                        {'pairs': (DomainPair('TX', 1, 2), DomainPair('tx', 2, 1))},
                        {'pairs': (DomainPair('TX', 1, 2), DomainPair('RX', 1, 1))},
                        {'baseline': replace(snapshot(), source_sha256='bad')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                save_session(self.path, replace(self.session, **changes))
            self.assertEqual(self.path.read_text(), 'existing evidence')

    def test_session_checksum_covers_mapping_and_threshold(self):
        original = self.document()
        for key, value in (('tolerance_mm', .5), ('pairs', []), ('session_sha256', '0'*64)):
            document = copy.deepcopy(original)
            document[key] = value
            self.write_document(document, rehash=False)
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_session(self.path)

    def test_nested_snapshot_hash_is_checked_even_after_outer_rehash(self):
        document = self.document()
        document['candidate']['parts'][0]['bounds_m'][0] -= .1
        self.write_document(document)
        with self.assertRaisesRegex(ValueError, 'integrity'):
            load_session(self.path)

    def test_untrusted_fields_and_shapes_are_rejected_even_with_correct_hash(self):
        original = self.document()
        for changes in ({'schema': 'wpt.geometry-comparison-session.v2'},
                        {'comparable_frames': True}, {'results': []}, {'path': 'source.mph'},
                        {'pairs': None}, {'pairs': [{}]}, {'pairs': [{'label': 'TX', 'baseline_domain': True, 'candidate_domain': 1}]},
                        {'pairs': original['pairs']*257}, {'tolerance_mm': True},
                        {'baseline': {}}, {'candidate': None}):
            document = {**copy.deepcopy(original), **changes}
            self.write_document(document)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                load_session(self.path)
        document = copy.deepcopy(original)
        document['pairs'][0]['extra'] = 1
        self.write_document(document)
        with self.assertRaises(ValueError):
            load_session(self.path)

    def test_duplicate_fields_nonfinite_invalid_encoding_and_resource_caps(self):
        text = json.dumps(self.document())
        for raw in (text.replace('"schema":', '"schema":"duplicate","schema":', 1).encode(),
                    text.replace('"domain":', '"domain":999,"domain":', 1).encode(),
                    text.replace('0.125', 'NaN').encode(), b'\xff', b'[]', b'{',
                    b'['*1500+b']'*1500, b' '*2_100_001):
            self.path.write_bytes(raw)
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                load_session(self.path)

    def test_atomic_failure_and_wrong_suffix_preserve_evidence(self):
        self.path.write_text('existing evidence')
        with patch('simulation_assistant.geometry_files.os.replace', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                save_session(self.path, self.session)
        self.assertEqual(self.path.read_text(), 'existing evidence')
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        for suffix in ('.mph', '.csv', ''):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                save_session(self.path.with_suffix(suffix), self.session)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == '__main__':
    unittest.main()
