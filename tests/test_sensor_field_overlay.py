"""Synthetic geometry bindings exercise gates; no claimed physical geometry."""
import math
import unittest
from dataclasses import replace
from pathlib import Path

from test_geometry_inspector import snapshot
from simulation_assistant.field_samples import Sensor
from simulation_assistant.saved_field_bundles import load_saved_field_bundle
from simulation_assistant.sensor_field_overlay import analyze_overlay, matching_sample

FIXTURE = Path(__file__).resolve().parents[1]/'examples/saved_field_wpt'


class SensorFieldOverlayTests(unittest.TestCase):
    def setUp(self):
        self.bundle = load_saved_field_bundle(FIXTURE)
        self.geometry = replace(snapshot(), source_sha256=self.bundle.sources[1].model_sha256)

    def analyze(self, **changes):
        args = dict(snapshot=self.geometry, sensors=self.bundle.sensors, bundle=self.bundle,
                    current='Position 2', reference='Position 1', comparable_frames=True,
                    geometry_matches_state=True)
        args.update(changes)
        return analyze_overlay(**args)

    def test_readings_use_complex_axis_projection_and_signed_amplitude_difference(self):
        overlay = self.analyze()
        self.assertEqual(overlay.current_source, self.bundle.sources[1])
        reading = overlay.readings[4]
        self.assertAlmostEqual(reading.amplitude_t*1e6, 36.4984380917, places=8)
        self.assertAlmostEqual(reading.amplitude_change_t*1e6, -1.0310806216, places=8)
        sample = matching_sample(overlay, 'S5', reference=False)
        self.assertEqual(sample.field[2], reading.projected_t)
        self.assertIsNotNone(reading.phase_deg)

    def test_matching_source_hash_never_substitutes_for_either_explicit_declaration(self):
        for value in (False, 1, None, 'yes'):
            for name in ('comparable_frames', 'geometry_matches_state'):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.analyze(**{name: value})
        for changes in (dict(snapshot=snapshot()), dict(current='Unknown'), dict(reference='Unknown')):
            with self.assertRaises(ValueError):
                self.analyze(**changes)

    def test_unavailable_values_are_not_zero_and_components_are_not_accepted(self):
        sensors = (replace(self.bundle.sensors[0], position_m=(1., 0., 0.)),
                   Sensor('Missing', (0., 0., 0.), (0., 0., 1.)))
        overlay = self.analyze(sensors=sensors)
        self.assertEqual(tuple(r.status for r in overlay.readings), ('position mismatch', 'missing point'))
        for row in overlay.readings:
            self.assertIsNone(row.projected_t)
            self.assertIsNone(row.amplitude_change_t)
            self.assertIsNone(matching_sample(overlay, row.sensor.point_id, reference=False))
        with self.assertRaises(ValueError):
            matching_sample(overlay, 'Unknown', reference=False)

    def test_subnormal_axes_are_normalized_robustly_without_changing_input_identity(self):
        sensor = replace(self.bundle.sensors[4], axis=(5e-324, 5e-324, 0.))
        overlay = self.analyze(sensors=(sensor,))
        sample = matching_sample(overlay, 'S5', reference=False)
        self.assertEqual(overlay.readings[0].sensor, sensor)
        self.assertAlmostEqual(abs(overlay.readings[0].projected_t-(sample.field[0]+sample.field[1])/math.sqrt(2)), 0.)

    def test_synthetic_zero_and_missing_reference_remain_distinct(self):
        # Altered in-memory test data only, not a claimed COMSOL extraction.
        samples = tuple(replace(s, field=(0j, 0j, 0j)) if s.scenario == 'Position 2' and s.point_id == 'S5' else s
                        for s in self.bundle.data.samples if not (s.scenario == 'Position 1' and s.point_id == 'S5'))
        bundle = replace(self.bundle, data=replace(self.bundle.data, samples=samples))
        row = self.analyze(bundle=bundle).readings[4]
        self.assertEqual(row.status, 'available')
        self.assertEqual(row.amplitude_t, 0.)
        self.assertIsNone(row.phase_deg)
        self.assertEqual(row.reference_status, 'missing point')
        self.assertIsNone(row.reference_t)
        self.assertIsNone(row.amplitude_change_t)
        self.assertIsNone(row.phase_change_deg)

    def test_mutable_layouts_cannot_enter_immutable_overlay_state(self):
        for sensors in (list(self.bundle.sensors), (), None):
            with self.subTest(kind=type(sensors).__name__), self.assertRaises(ValueError):
                self.analyze(sensors=sensors)


if __name__ == '__main__':
    unittest.main()
