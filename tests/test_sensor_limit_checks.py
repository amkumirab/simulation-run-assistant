import math
import unittest
from dataclasses import replace
from pathlib import Path

from test_sensor_profiles import hypothetical_profile
from simulation_assistant.geometry_files import load_snapshot
from simulation_assistant.saved_field_bundles import load_saved_field_bundle
from simulation_assistant.sensor_field_overlay import analyze_overlay
from simulation_assistant.sensor_profiles import SensorProfile, StatedRange, StatedValue
from simulation_assistant.sensor_limit_checks import assess_sensor_limits, WITHIN, OUTSIDE, UNKNOWN


def real_overlay():
    fixture = Path(__file__).resolve().parents[1]/'examples/saved_field_wpt'
    bundle = load_saved_field_bundle(fixture)
    return analyze_overlay(load_snapshot(fixture/'geometry-position-2.json'), bundle.sensors, bundle,
                           'Position 2', 'Position 1', comparable_frames=True, geometry_matches_state=True)


class SensorLimitCheckTests(unittest.TestCase):
    def setUp(self):
        self.overlay = real_overlay()

    def assess(self, **changes):
        args = dict(profile=hypothetical_profile(), overlay=self.overlay, sampled_field='charging-coil-ac',
                    dc_bias_t=(0., 0., 0.), conditions_confirmed=True)
        args.update(changes)
        return assess_sensor_limits(**args)

    def test_hypothetical_limits_are_usable_but_never_hardware_evidence(self):
        result = self.assess()
        self.assertEqual(len(result.rows), 18)
        self.assertTrue(all(r.status == WITHIN for r in result.rows))
        self.assertIn('ASSUMPTION', result.scope)
        self.assertIn('no physical sensor', result.scope)
        row = next(r for r in result.rows if r.sensor_id == 'S5' and r.scenario == 'Position 2')
        self.assertAlmostEqual(row.peak_axis_t*1e6, 36.4984380917, places=8)
        self.assertEqual((row.minimum_t, row.maximum_t), (-row.peak_axis_t, row.peak_axis_t))

    def test_unknown_specs_bias_and_purpose_do_not_become_zero_or_approval(self):
        for changes in ({'profile': SensorProfile('Unknown design')}, {'dc_bias_t': None},
                        {'sampled_field': 'unknown'}, {'sampled_field': 'vehicle-signature'}, {'conditions_confirmed': False}):
            result = self.assess(**changes)
            self.assertTrue(all(r.status == UNKNOWN for r in result.rows), changes)
        result = self.assess(dc_bias_t=None)
        self.assertIsNone(result.rows[0].minimum_t)
        self.assertEqual(result.rows[0].frequency.status, WITHIN)

    def test_known_violation_wins_over_missing_other_check(self):
        profile = replace(hypothetical_profile(), frequency=StatedRange(0., 1., 'kHz', 'Test assumption', 'AC screening'))
        result = self.assess(profile=profile, dc_bias_t=None)
        self.assertTrue(all(r.status == OUTSIDE for r in result.rows))
        self.assertEqual(result.rows[0].field.status, UNKNOWN)

    def test_signed_bias_range_and_inclusive_exact_boundary(self):
        peak = self.overlay.readings[4].amplitude_t
        profile = replace(hypothetical_profile(), field=StatedRange(2e-6-peak, 2e-6+peak, 'T', 'Test assumption', 'Axis range'))
        result = self.assess(profile=profile, dc_bias_t=(0., 0., 2e-6))
        row = next(r for r in result.rows if r.sensor_id == 'S5' and r.scenario == 'Position 2')
        self.assertEqual(row.field.status, WITHIN)
        profile = replace(profile, field=replace(profile.field, high=math.nextafter(profile.field.high, -math.inf)))
        result = self.assess(profile=profile, dc_bias_t=(0., 0., 2e-6))
        row = next(r for r in result.rows if r.sensor_id == 'S5' and r.scenario == 'Position 2')
        self.assertEqual(row.field.status, OUTSIDE)

    def test_rms_conversion_and_axis_reversal_use_complex_projection_not_component_norm(self):
        # Altered in-memory metadata/layout only; no claimed COMSOL extraction.
        bundle = replace(self.overlay.bundle, data=replace(self.overlay.bundle.data,
                         metadata=replace(self.overlay.bundle.data.metadata, phasor_convention='rms')))
        sensors = tuple(replace(s, axis=(0., 0., -2.)) for s in self.overlay.sensors)
        overlay = analyze_overlay(self.overlay.snapshot, sensors, bundle, 'Position 2', 'Position 1',
                                  comparable_frames=True, geometry_matches_state=True)
        row = self.assess(overlay=overlay, dc_bias_t=(0., 0., 3e-6)).rows[0]
        self.assertAlmostEqual(row.peak_axis_t, self.overlay.readings[0].amplitude_t*math.sqrt(2))
        self.assertEqual(row.dc_axis_t, -3e-6)

    def test_missing_current_reference_and_position_mismatch_stay_unavailable(self):
        sensors = (replace(self.overlay.sensors[0], position_m=(1., 0., 0.)),)
        overlay = analyze_overlay(self.overlay.snapshot, sensors, self.overlay.bundle, 'Position 2', 'Position 1',
                                  comparable_frames=True, geometry_matches_state=True)
        result = self.assess(overlay=overlay)
        for row in result.rows:
            self.assertEqual(row.sample_status, 'position mismatch')
            self.assertIsNone(row.peak_axis_t)
            self.assertEqual(row.field.status, UNKNOWN)

    def test_invalid_context_and_tampered_overlay_are_rejected(self):
        for changes in ({'conditions_confirmed': 1}, {'dc_bias_t': (True, 0., 0.)}, {'dc_bias_t': [0., 0., 0.]},
                        {'dc_bias_t': (float('inf'), 0., 0.)}, {'sampled_field': 'auto'},
                        {'overlay': replace(self.overlay, readings=())}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.assess(**changes)

    def test_synthetic_zero_current_and_missing_reference_do_not_share_a_value(self):
        samples = tuple(replace(s, field=(0j, 0j, 0j)) if s.scenario == 'Position 2' and s.point_id == 'S5' else s
                        for s in self.overlay.bundle.data.samples if not (s.scenario == 'Position 1' and s.point_id == 'S5'))
        bundle = replace(self.overlay.bundle, data=replace(self.overlay.bundle.data, samples=samples))
        overlay = analyze_overlay(self.overlay.snapshot, self.overlay.sensors, bundle, 'Position 2', 'Position 1',
                                  comparable_frames=True, geometry_matches_state=True)
        current, reference = [r for r in self.assess(overlay=overlay).rows if r.sensor_id == 'S5']
        self.assertEqual(current.peak_axis_t, 0.)
        self.assertEqual(current.status, WITHIN)
        self.assertIsNone(reference.peak_axis_t)
        self.assertEqual(reference.field.status, UNKNOWN)
        self.assertEqual(reference.sample_status, 'missing point')

    def test_record_only_noise_and_sensitivity_never_invent_detectability(self):
        result = self.assess()
        profile = replace(result.profile, sensitivity=StatedValue(1e-20, 'arbitrary reported unit', 'Test assumption', 'Record only'),
                          noise=StatedValue(1e20, 'nT/sqrt(Hz)', 'Test assumption', 'Record only'))
        self.assertEqual(self.assess(profile=profile).rows, result.rows)


if __name__ == '__main__':
    unittest.main()
