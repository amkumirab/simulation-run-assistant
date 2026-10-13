import math
import unittest
from dataclasses import replace

from simulation_assistant.field_samples import (
    FieldMetadata, FieldSample, FieldDataset, Sensor, analyze_field_samples,
    make_sensor_grid, validate_dataset, validate_layout,
)


def metadata(**changes):
    return replace(FieldMetadata("Test", "synthetic", "fixture-v1", "solution-1",
                                "Global XYZ", "mm", "uT", 85000.0, "peak", "TX 1 A peak", "TX phase zero"), **changes)


def dataset(samples=None):
    return FieldDataset(metadata(), tuple(samples or [
        FieldSample("Aligned", "S1", (0., 0., 0.), (1e-6+2e-6j, 0j, 0j)),
        FieldSample("Offset", "S1", (0., 0., 0.), (-2e-6+1e-6j, 0j, 0j)),
    ]), "a" * 64)


class FieldSampleTests(unittest.TestCase):
    def test_complex_projection_and_reference_changes(self):
        reading = analyze_field_samples(dataset(), (Sensor("S1", (0., 0., 0.), (2., 0., 0.)),), "Offset", "Aligned")[0]
        self.assertEqual(reading.status, "available")
        self.assertEqual(reading.projected_t, -2e-6+1e-6j)
        self.assertAlmostEqual(reading.amplitude_t, math.sqrt(5)*1e-6)
        self.assertAlmostEqual(reading.amplitude_change_t, 0.)
        self.assertAlmostEqual(reading.phase_change_deg, 90.)

    def test_reversed_axis_and_zero_phase(self):
        sensor = Sensor("S1", (0., 0., 0.), (-1., 0., 0.))
        reading = analyze_field_samples(dataset(), (sensor,), "Aligned", "Offset")[0]
        self.assertEqual(reading.projected_t, -1e-6-2e-6j)
        zero = dataset([FieldSample("Zero", "S1", (0., 0., 0.), (0j, 0j, 0j))])
        reading = analyze_field_samples(zero, (sensor,), "Zero", "Zero")[0]
        self.assertIsNone(reading.phase_deg)
        self.assertIsNone(reading.phase_change_deg)
        self.assertEqual(reading.amplitude_t, 0.)

    def test_missing_and_coordinate_mismatch_are_not_zero(self):
        sensors = (Sensor("S2", (0., 0., 0.), (0., 0., 1.)),
                   Sensor("S1", (.001, 0., 0.), (1., 0., 0.)))
        readings = analyze_field_samples(dataset(), sensors, "Offset", "Aligned")
        self.assertEqual([r.status for r in readings], ["missing point", "position mismatch"])
        self.assertTrue(all(r.projected_t is None for r in readings))

    def test_missing_reference_remains_unavailable(self):
        value = dataset([FieldSample("Aligned", "Other", (1., 0., 0.), (0j, 0j, 0j)),
                         FieldSample("Offset", "S1", (0., 0., 0.), (1e-6+0j, 0j, 0j))])
        reading = analyze_field_samples(value, (Sensor("S1", (0., 0., 0.), (1., 0., 0.)),), "Offset", "Aligned")[0]
        self.assertEqual(reading.status, "available")
        self.assertEqual(reading.reference_status, "missing point")
        self.assertIsNone(reading.amplitude_change_t)

    def test_duplicate_nonfinite_and_invalid_metadata_rejected(self):
        point = dataset().samples[0]
        bad = [replace(dataset(), samples=(point, point)),
               replace(dataset(), samples=(replace(point, field=(complex(float('nan')), 0j, 0j)),)),
               replace(dataset(), metadata=metadata(frequency_hz=True)),
               replace(dataset(), metadata=metadata(phasor_convention="guess")),
               replace(dataset(), metadata=metadata(field_unit="gauss")),
               replace(dataset(), metadata=metadata(source_kind="real sensor")),
               replace(dataset(), metadata=metadata(solution_id="C:\\private\\x")),
               replace(dataset(), source_sha256="invalid")]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_dataset(value)
        for axis in [(0., 0., 0.), (float('inf'), 0., 0.)]:
            with self.assertRaises(ValueError):
                validate_layout((Sensor("S1", (0., 0., 0.), axis),))

    def test_grid_is_centered_bounded_and_deterministic(self):
        layout = make_sensor_grid(3, 3, .01, .02, (0., 0., 1.))
        self.assertEqual(len(layout), 9)
        self.assertEqual(layout[4].position_m, (0., 0., .02))
        self.assertEqual(layout[0].position_m, (-.01, -.01, .02))
        self.assertEqual(layout, make_sensor_grid(3, 3, .01, .02, (0., 0., 1.)))
        for rows, cols, spacing in [(0, 3, .01), (True, 3, .01), (17, 17, .01), (3, 3, 0.)]:
            with self.assertRaises(ValueError):
                make_sensor_grid(rows, cols, spacing, 0., (0., 0., 1.))

    def test_unknown_scenario_and_duplicate_layout_block_analysis(self):
        sensor = Sensor("S1", (0., 0., 0.), (0., 0., 1.))
        with self.assertRaises(ValueError):
            analyze_field_samples(dataset(), (sensor,), "Unknown", "Aligned")
        with self.assertRaises(ValueError):
            analyze_field_samples(dataset(), (sensor, sensor), "Aligned", "Aligned")

    def test_phase_wrap_and_normalized_oblique_direction(self):
        import cmath
        value = dataset([FieldSample("Before", "S1", (0., 0., 0.), (cmath.rect(1e-6, math.radians(179)), 0j, 0j)),
                         FieldSample("After", "S1", (0., 0., 0.), (cmath.rect(1e-6, math.radians(-179)), 0j, 0j))])
        sensor = Sensor("S1", (0., 0., 0.), (1., 1., 0.))
        reading = analyze_field_samples(value, (sensor,), "After", "Before")[0]
        self.assertAlmostEqual(reading.phase_change_deg, 2.)
        self.assertAlmostEqual(reading.amplitude_t, 1e-6/math.sqrt(2))

    def test_malformed_direct_metadata_and_huge_integer_are_clean_errors(self):
        for meta in [metadata(coordinate_unit=[]), metadata(frequency_hz=10**400)]:
            with self.subTest(meta=meta), self.assertRaises(ValueError):
                validate_dataset(replace(dataset(), metadata=meta))


if __name__ == "__main__":
    unittest.main()
