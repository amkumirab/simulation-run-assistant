import unittest
from dataclasses import FrozenInstanceError, replace

from simulation_assistant.sensor_profiles import SensorProfile, StatedRange, StatedValue, validate_profile


def hypothetical_profile():
    return SensorProfile('Exploratory design', target_field='charging-coil-ac',
        frequency=StatedRange(0., 100., 'kHz', 'User design assumption', 'Single-frequency screening'),
        field=StatedRange(-100., 100., 'uT', 'User design assumption', 'Sensitivity-axis limits only'))


class SensorProfileTests(unittest.TestCase):
    def test_empty_hypothetical_profile_has_no_fabricated_device_or_values(self):
        profile = SensorProfile('My assumptions')
        validate_profile(profile)
        self.assertEqual(profile.basis, 'hypothetical')
        self.assertEqual(profile.device, '')
        self.assertIsNone(profile.frequency)
        self.assertIsNone(profile.field)
        self.assertIsNone(profile.sensitivity)
        self.assertIsNone(profile.noise)
        with self.assertRaises(FrozenInstanceError):
            profile.name = 'Changed'

    def test_record_only_values_retain_reported_units_and_conditions(self):
        profile = replace(hypothetical_profile(),
            sensitivity=StatedValue(12., 'mV/V/Oe', 'Hypothetical test value', 'Not a physical device'),
            noise=StatedValue(5., 'nT/sqrt(Hz)', 'Hypothetical test value', 'At 1 kHz; no integration'))
        validate_profile(profile)
        self.assertEqual(profile.sensitivity.unit, 'mV/V/Oe')
        self.assertEqual(profile.noise.value, 5.)

    def test_documented_mode_requires_named_device_but_does_not_authenticate_sources(self):
        profile = replace(hypothetical_profile(), basis='documented')
        with self.assertRaises(ValueError):
            validate_profile(profile)
        validate_profile(replace(profile, device='User named device - test fixture'))

    def test_invalid_bounds_units_numbers_and_missing_provenance_are_rejected(self):
        base = hypothetical_profile()
        for field, spec in (('frequency', replace(base.frequency, low=-1.)),
                            ('frequency', replace(base.frequency, high=1e100)),
                            ('frequency', replace(base.frequency, unit='mHz')),
                            ('field', replace(base.field, unit='Oe')),
                            ('field', replace(base.field, low=200.)),
                            ('field', replace(base.field, high=True)),
                            ('field', replace(base.field, source='')),
                            ('field', replace(base.field, conditions='')),
                            ('field', replace(base.field, high=float('nan')))):
            with self.subTest(field=field, spec=spec), self.assertRaises(ValueError):
                validate_profile(replace(base, **{field: spec}))
        for changes in ({'name': ''}, {'basis': 'verified'}, {'target_field': []}, {'notes': 'bad\nline'},
                        {'noise': StatedValue(0., 'nT', 'Reference', 'Conditions')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_profile(replace(base, **changes))


if __name__ == '__main__':
    unittest.main()
