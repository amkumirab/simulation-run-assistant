import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
from simulation_assistant.geometry_inspector import (
    GeometryPart, GeometrySnapshot, inspect_geometry, read_geometry, validate_snapshot, z_separation,
)


def snapshot():
    return GeometrySnapshot('a'*64, 'comp1', 'geom1', 'm', '6.3', (
        GeometryPart(1, 'coil_tx', (-.1, .1, -.1, .1, 0., .005)),
        GeometryPart(2, 'coil_rx', (-.1, .1, -.1, .1, .155, .160)),
    ))


class GeometryInspectorTests(unittest.TestCase):
    def test_explicit_declaration_and_order_are_required_for_z_envelopes(self):
        lower, upper = snapshot().parts
        self.assertIsNone(z_separation(lower, upper, False))
        self.assertAlmostEqual(z_separation(lower, upper, True), .15)
        self.assertIsNone(z_separation(upper, lower, True))
        self.assertIsNone(z_separation(lower, lower, True))
        self.assertIsNone(z_separation(lower, replace(upper, bounds_m=(1.,2.,1.,2.,.155,.16)), True))

    def test_bounds_are_finite_ordered_unique_and_bounded(self):
        good = snapshot()
        validate_snapshot(good)
        for bounds in ((0.,1.,0.,1.,2.,1.), (0.,1.,0.,1.,0.,float('nan')), (0.,1.),
                       (0.,1.,0.,1.,0.,True), (0.,1.,0.,1.,0.,10**400)):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                validate_snapshot(replace(good, parts=(replace(good.parts[0], bounds_m=bounds),)))
        for bad in (replace(good, source_sha256=''), replace(good, component='../comp'),
                    replace(good, parts=good.parts+good.parts), replace(good, parts=()),
                    replace(good, length_unit='inch'), replace(good, length_unit=[])):
            with self.subTest(snapshot=bad), self.assertRaises(ValueError):
                validate_snapshot(bad)

    def test_protocol_normalizes_original_units_and_preserves_selection_tags(self):
        raw = (b'geometry\tcomp1\tgeom1\tmm\t6.3\n'
               b'domain\tselections\txmin\txmax\tymin\tymax\tzmin\tzmax\n'
               b'1\tcoil_tx\t-100\t100\t-100\t100\t0\t5\n')
        data = read_geometry(raw, 'a'*64)
        self.assertEqual(data.parts[0], snapshot().parts[0])
        for corrupt in (raw.replace(b'\tmm\t', b'\tft\t'), raw+raw.splitlines()[-1]+b'\n',
                        raw.replace(b'\t5\n', b'\tNaN\n'), raw.replace(b'domain\t', b'wrong\t')):
            with self.subTest(raw=corrupt), self.assertRaises(ValueError):
                read_geometry(corrupt, 'a'*64)

    def test_inspection_binds_original_and_rejects_changed_source(self):
        raw = (b'geometry\tcomp1\tgeom1\tm\t6.3\n'
               b'domain\tselections\txmin\txmax\tymin\tymax\tzmin\tzmax\n'
               b'1\tcoil_tx\t-.1\t.1\t-.1\t.1\t0\t.005\n')
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory)/'source.mph'
            model.write_bytes(b'private source bytes')
            with patch('simulation_assistant.geometry_inspector.run_helper', return_value=raw) as engine:
                result = inspect_geometry(model, 'batch')
            self.assertEqual(model.read_bytes(), b'private source bytes')
            self.assertEqual(engine.call_args.args[2:4], ('SavedGeometryInspector', 'geometry'))
            self.assertEqual(engine.call_args.kwargs['expected_sha256'], result.source_sha256)
            def changed(*_args, **_kwargs):
                model.write_bytes(b'changed by external process')
                return raw
            with patch('simulation_assistant.geometry_inspector.run_helper', side_effect=changed), self.assertRaisesRegex(ValueError, 'changed'):
                inspect_geometry(model, 'batch')

    def test_failed_or_cancelled_engine_never_returns_snapshot(self):
        with patch('simulation_assistant.geometry_inspector.model_digest', return_value='a'*64), \
                patch('simulation_assistant.geometry_inspector.run_helper', side_effect=RuntimeError('cancelled')) as engine:
            stop = lambda: True
            with self.assertRaisesRegex(RuntimeError, 'cancelled'):
                inspect_geometry('source.mph', 'batch', cancel_requested=stop)
            self.assertIs(engine.call_args.kwargs['cancel_requested'], stop)


if __name__ == '__main__':
    unittest.main()
