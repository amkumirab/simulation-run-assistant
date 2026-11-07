import unittest
from dataclasses import replace
from pathlib import Path
from test_geometry_inspector import snapshot
from simulation_assistant.geometry_files import load_snapshot
from simulation_assistant.geometry_comparison import DomainPair, compare_geometry


class GeometryComparisonTests(unittest.TestCase):
    def test_explicit_pairs_survive_domain_renumbering_and_report_unmapped(self):
        base = snapshot()
        moved = replace(base.parts[0], domain=99, bounds_m=(0., .2, -.1, .1, .02, .025))
        candidate = replace(base, parts=(moved, base.parts[1]))
        result = compare_geometry(base, candidate, (DomainPair('TX envelope', 1, 99),), comparable_frames=True)
        metrics = {m.name: m for m in result.differences[0].metrics}
        self.assertAlmostEqual(metrics['midpoint_x'].delta_mm, 100.)
        self.assertAlmostEqual(metrics['midpoint_z'].delta_mm, 20.)
        self.assertAlmostEqual(metrics['span_x'].delta_mm, 0.)
        self.assertEqual(result.baseline_unmapped, (2,))
        self.assertEqual(result.candidate_unmapped, (2,))
        self.assertTrue(result.differences[0].changed)

    def test_frames_and_nonempty_unique_one_to_one_pairs_are_mandatory(self):
        data = snapshot()
        for pairs in ((), [DomainPair('TX', 1, 1)], (DomainPair('TX', True, 1),),
                      (DomainPair('', 1, 1),), (DomainPair('TX', 3, 1),),
                      (DomainPair('TX', 1, 1), DomainPair('tx', 2, 2)),
                      (DomainPair('A', 1, 1), DomainPair('B', 1, 2)),
                      (DomainPair('A', 1, 1), DomainPair('B', 2, 1))):
            with self.subTest(pairs=pairs), self.assertRaises(ValueError):
                compare_geometry(data, data, pairs, comparable_frames=True)
        for declaration in (False, 1, 'yes', None):
            with self.subTest(declaration=declaration), self.assertRaises(ValueError):
                compare_geometry(data, data, (DomainPair('TX', 1, 1),), comparable_frames=declaration)

    def test_absolute_threshold_is_not_relative_and_preserves_small_deltas(self):
        base = snapshot()
        candidate = replace(base, parts=(replace(base.parts[0], bounds_m=(-.1,.1,-.1,.1,0.,.005000001)), base.parts[1]))
        pair = (DomainPair('TX', 1, 1),)
        result = compare_geometry(base, candidate, pair, comparable_frames=True)
        self.assertFalse(result.differences[0].changed)
        self.assertNotEqual(result.differences[0].metrics[5].delta_mm, 0.)
        self.assertTrue(compare_geometry(base, candidate, pair, comparable_frames=True, tolerance_mm=0).differences[0].changed)
        for tolerance in (True, '1', -1, 1001, float('nan'), float('inf'), 10**400):
            with self.subTest(tolerance=tolerance), self.assertRaises(ValueError):
                compare_geometry(base, candidate, pair, comparable_frames=True, tolerance_mm=tolerance)

    def test_real_saved_overlaps_and_height_control_keep_signed_differences(self):
        folder = Path(__file__).resolve().parents[1]/'examples/saved_geometry_wpt'
        base = load_snapshot(folder/'original.json')
        for name, dx in (('overlap',140.), ('control',0.)):
            result = compare_geometry(base, load_snapshot(folder/(name+'.json')),
                                      (DomainPair('Left RX coil envelope',4,4),), comparable_frames=True)
            values = {m.name:m.delta_mm for m in result.differences[0].metrics}
            self.assertAlmostEqual(values['midpoint_x'], dx, places=4)
            self.assertAlmostEqual(values['midpoint_z'], 20., places=4)
            self.assertAlmostEqual(values['span_z'], 0., places=4)

    def test_inclusive_threshold_boundary_and_candidate_direction(self):
        base=snapshot()
        candidate=replace(base,parts=(replace(base.parts[0],bounds_m=(.025,.225,-.1,.1,0.,.005)),base.parts[1]))
        pair=(DomainPair('TX',1,1),)
        at_boundary=compare_geometry(base,candidate,pair,comparable_frames=True,tolerance_mm=125.)
        self.assertFalse(at_boundary.differences[0].changed)
        below=compare_geometry(base,candidate,pair,comparable_frames=True,tolerance_mm=124.)
        self.assertTrue(below.differences[0].changed)
        reverse=compare_geometry(candidate,base,pair,comparable_frames=True)
        self.assertAlmostEqual(reverse.differences[0].metrics[6].delta_mm,-125.)

    def test_equivalent_si_bounds_with_different_original_unit_metadata(self):
        base=snapshot()
        other=replace(base,length_unit='mm')
        result=compare_geometry(base,other,(DomainPair('TX',1,1),),comparable_frames=True)
        self.assertFalse(result.differences[0].changed)

    def test_full_256_pair_bound_and_invalid_labels(self):
        base=snapshot()
        full=replace(base,parts=tuple(replace(base.parts[0],domain=i) for i in range(1,257)))
        pairs=tuple(DomainPair(f'Part {i}',i,i) for i in range(1,257))
        result=compare_geometry(full,full,pairs,comparable_frames=True)
        self.assertEqual(len(result.differences),256)
        self.assertFalse(result.baseline_unmapped)
        for label in (' x','x ','x\ny','\u0622',False,'x'*81):
            with self.subTest(label=label),self.assertRaises(ValueError):
                compare_geometry(base,base,(DomainPair(label,1,1),),comparable_frames=True)
        with self.assertRaises(ValueError):
            compare_geometry(full,full,(*pairs,DomainPair('Extra',1,1)),comparable_frames=True)


if __name__ == '__main__':
    unittest.main()
