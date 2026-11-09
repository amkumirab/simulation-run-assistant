import math
import unittest
from dataclasses import replace

from test_geometry_inspector import snapshot
from simulation_assistant.field_samples import Sensor
from simulation_assistant.sensor_placement import layout_digest, project_placement, projected_hits


class SensorPlacementTests(unittest.TestCase):
    def setUp(self):
        self.sensors = (Sensor('S1', (.02, -.03, .08), (0., 0., 2.)),)

    def view(self, plane='XZ', **kwargs):
        return project_placement(snapshot(), self.sensors, (1,), plane,
                                 comparable_frames=True, width=580, height=420, **kwargs)

    def test_projection_retains_positions_and_normalized_full_3d_axis(self):
        xy, xz = self.view('XY'), self.view()
        self.assertEqual(xy.sensors[0].axis_uv, (0., 0.))
        self.assertEqual(xy.sensors[0].normal_component, 1.)
        self.assertEqual(xy.normal_axis, 'Z')
        self.assertEqual(xz.sensors[0].axis_uv, (0., 1.))
        self.assertEqual(xz.normal_axis, 'Y')
        self.assertEqual(xz.sensors[0].axis_xyz, (0., 0., 1.))
        self.assertEqual(xz.sensors[0].sensor, self.sensors[0])

    def test_equal_physical_scale_with_correct_screen_vertical_direction(self):
        view = self.view()
        x, y = view.point(0., 0.)
        self.assertAlmostEqual(view.point(10., 0.)[0]-x, view.scale*10)
        self.assertAlmostEqual(y-view.point(0., 10.)[1], view.scale*10)
        self.assertEqual(view.sensors[0].point, view.point(20., 80.))
        for envelope in view.envelopes:
            left, top, right, bottom = envelope.bounds
            self.assertLess(left, right)
            self.assertLess(top, bottom)

    def test_axis_projection_is_not_renormalized_and_reversal_is_retained(self):
        sensors = (Sensor('Oblique', (0., 0., 0.), (1., 2., 3.)),)
        view = project_placement(snapshot(), sensors, (1,), 'XY', comparable_frames=True)
        self.assertAlmostEqual(math.hypot(*view.sensors[0].axis_uv), math.sqrt(5/14))
        self.assertAlmostEqual(view.sensors[0].normal_component, 3/math.sqrt(14))
        reversed_sensor = (replace(sensors[0], axis=(-1., -2., -3.)),)
        other = project_placement(snapshot(), reversed_sensor, (1,), 'XY', comparable_frames=True)
        self.assertEqual(other.sensors[0].axis_uv, tuple(-v for v in view.sensors[0].axis_uv))

    def test_subnormal_axis_inputs_still_produce_a_unit_3d_direction(self):
        sensors = (Sensor('Tiny axis', (0., 0., 0.), (5e-324, 5e-324, 0.)),)
        view = project_placement(snapshot(), sensors, (1,), 'XY', comparable_frames=True)
        self.assertAlmostEqual(math.hypot(*view.sensors[0].axis_xyz), 1.)
        self.assertAlmostEqual(view.sensors[0].axis_xyz[0], 1/math.sqrt(2))

    def test_all_inputs_including_distant_and_projectively_coincident_sensors_fit(self):
        sensors = (Sensor('Far', (1e6, -1e6, 1e6), (1e100, 0., 0.)),
                   Sensor('Behind', (1e6, 0., 1e6), (0., 1., 0.)))
        view = project_placement(snapshot(), sensors, (1, 2), 'XZ', comparable_frames=True)
        for sensor in view.sensors:
            self.assertTrue(all(math.isfinite(v) for v in sensor.point))
            self.assertTrue(70 <= sensor.point[0] <= view.width-40)
            self.assertTrue(70 <= sensor.point[1] <= view.height-50)
        self.assertEqual(projected_hits(view, *view.sensors[0].point), ('Far', 'Behind'))
        self.assertEqual(projected_hits(view, -100, -100), ())

    def test_tiny_envelopes_and_identical_sensor_positions_have_finite_limits(self):
        source = replace(snapshot(), parts=(replace(snapshot().parts[0], bounds_m=(0., 1e-20, 0., 1e-20, 0., 1e-20)),))
        sensors = (Sensor('S1', (0., 0., 0.), (0., -1., 0.)),)
        view = project_placement(source, sensors, (1,), 'XZ', comparable_frames=True)
        self.assertTrue(math.isfinite(view.scale))
        self.assertGreater(view.scale, 0)
        self.assertEqual(view.sensors[0].normal_component, -1.)

    def test_frame_approval_explicit_domains_and_valid_inputs_are_mandatory(self):
        for declaration in (False, 1, 'yes', None):
            with self.subTest(declaration=declaration), self.assertRaises(ValueError):
                project_placement(snapshot(), self.sensors, (1,), 'XY', comparable_frames=declaration)
        for domains in ((), (True,), (3,), (1, 1), [1]):
            with self.subTest(domains=domains), self.assertRaises(ValueError):
                project_placement(snapshot(), self.sensors, domains, 'XY', comparable_frames=True)
        for changes in ({'plane': 'YZ'}, {'width': True}, {'width': 399}, {'height': 299}, {'height': 100_000}):
            arguments = dict(plane='XY', width=580, height=420, comparable_frames=True)
            arguments.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                project_placement(snapshot(), self.sensors, (1,), **arguments)
        for sensors in ((), (replace(self.sensors[0], axis=(0., 0., 0.)),),
                        (replace(self.sensors[0], position_m=(float('nan'), 0., 0.)),)):
            with self.assertRaises(ValueError):
                project_placement(snapshot(), sensors, (1,), 'XY', comparable_frames=True)

    def test_layout_fingerprint_covers_positions_axes_and_ids(self):
        original = layout_digest(self.sensors)
        self.assertEqual(len(original), 64)
        for sensor in (replace(self.sensors[0], point_id='S2'),
                       replace(self.sensors[0], axis=(1., 0., 0.)),
                       replace(self.sensors[0], position_m=(0., 0., 0.))):
            self.assertNotEqual(layout_digest((sensor,)), original)


if __name__ == '__main__':
    unittest.main()
