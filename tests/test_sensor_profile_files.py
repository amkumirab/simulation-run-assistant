import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_sensor_profiles import hypothetical_profile
from simulation_assistant.sensor_profiles import SensorProfile, StatedRange, StatedValue
from simulation_assistant.sensor_profile_files import (
    load_sensor_profile, profile_digest, profile_document, read_profile_document, save_sensor_profile,
)


class SensorProfileFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'profile.json'

    def test_empty_and_known_profiles_roundtrip_without_saved_approvals(self):
        for profile in (SensorProfile('Unknown design'), hypothetical_profile()):
            save_sensor_profile(self.path, profile)
            self.assertEqual(load_sensor_profile(self.path), profile)
            document = profile_document(profile)
            self.assertEqual(document['profile_sha256'], profile_digest(profile))
            self.assertNotIn('conditions_confirmed', document)
        self.assertNotEqual(profile_digest(profile), profile_digest(replace(profile, notes='Changed rationale')))

    def test_nested_tampering_unknown_fields_and_wrong_shapes_fail(self):
        original = profile_document(hypothetical_profile())
        for key, value in (('name', 'Changed'), ('field', []), ('extra', 1), ('profile_sha256', '0'*64)):
            document = dict(original, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                read_profile_document(document)
        from simulation_assistant.geometry_files import _digest
        for row in (dict(original['field'], extra=1), dict(original['field'], high=True)):
            document = dict(original, field=row)
            document.pop('profile_sha256')
            document['profile_sha256'] = _digest(document)
            with self.assertRaises(ValueError):
                read_profile_document(document)

    def test_duplicate_deep_nonfinite_and_oversized_files_fail(self):
        valid = json.dumps(profile_document(hypothetical_profile()))
        for raw in ('{"schema":1,"schema":2}', valid.replace('100.0', 'NaN', 1), '['*1500+']'*1500,
                    '{}', ' '*262145, '\ud800'):
            self.path.write_bytes(raw.encode('utf8', errors='surrogatepass'))
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                load_sensor_profile(self.path)

    def test_failed_validation_or_atomic_replace_preserves_previous_file(self):
        profile = hypothetical_profile()
        save_sensor_profile(self.path, profile)
        raw = self.path.read_bytes()
        with self.assertRaises(ValueError):
            save_sensor_profile(self.path, replace(profile, name=''))
        with patch('simulation_assistant.geometry_files.os.replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                save_sensor_profile(self.path, replace(profile, notes='Changed'))
        self.assertEqual(self.path.read_bytes(), raw)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])
        with self.assertRaises(ValueError):
            save_sensor_profile(self.path.with_suffix('.mph'), profile)

    def test_generated_optional_specs_and_units_roundtrip_with_order_independent_digest(self):
        rng = random.Random(20261116)
        for index in range(120):
            bound = 10.**rng.randint(-12, 3)
            unit = rng.choice(('T', 'mT', 'uT'))
            profile = SensorProfile(f'Hypothetical {index}', field=StatedRange(-bound, bound, unit,
                                    'Generated design assumption', 'Axis-only test'),
                                    noise=None if index % 2 else StatedValue(bound, 'nT/sqrt(Hz)', 'Test assumption', 'Record only'))
            document = profile_document(profile)
            items = list(document.items())
            rng.shuffle(items)
            loaded = read_profile_document(json.loads(json.dumps(dict(items))))
            self.assertEqual(loaded, profile)
            self.assertEqual(profile_digest(loaded), document['profile_sha256'])


if __name__ == '__main__':
    unittest.main()
