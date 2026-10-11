import unittest
from dataclasses import replace

from simulation_assistant.experiments import InputRange, ExperimentSpec, generate_experiments
from simulation_assistant.quantities import parse_quantity
from simulation_assistant.model_contract import parse_model_contract


class ExperimentTests(unittest.TestCase):
    def spec(self, **changes):
        base = ExperimentSpec(
            ranges=(InputRange("gap", "100[mm]", "20[cm]"),
                    InputRange("N1", "8", "16", "integer")),
            fixed={"f0": "85[kHz]"}, budget=30, seed=7)
        return replace(base, **changes)

    def test_reproducible_unique_points_and_units(self):
        plan = generate_experiments(self.spec())
        self.assertEqual(plan, generate_experiments(self.spec()))
        self.assertNotEqual(plan.points, generate_experiments(self.spec(seed=8)).points)
        self.assertEqual(len(plan.points), 30)
        self.assertEqual(len({tuple(sorted(p.items())) for p in plan.points}), 30)
        for point in plan.points:
            self.assertEqual(point["f0"], "85[kHz]")
            gap = parse_quantity(point["gap"])
            self.assertGreaterEqual(gap.si_value, .1)
            self.assertLessEqual(gap.si_value, .2)
            self.assertIn(int(point["N1"]), range(8, 17))

    def test_continuous_strata_are_covered(self):
        plan = generate_experiments(self.spec(ranges=(InputRange("x", "0", "1"),), budget=30))
        self.assertEqual({min(29, int(float(p["x"]) * 30)) for p in plan.points}, set(range(30)))

    def test_small_discrete_space_exhaustion(self):
        plan = generate_experiments(self.spec(ranges=(InputRange("N1", "2", "3", "integer"),)))
        self.assertEqual(len(plan.points), 2)
        self.assertTrue(plan.shortfall)
        self.assertEqual({p["N1"] for p in plan.points}, {"2", "3"})

    def test_radius_constraint_uses_common_units(self):
        plan = generate_experiments(self.spec(
            ranges=(InputRange("r_out", "3[cm]", "6[cm]"),),
            fixed={"r_in": "40[mm]"}, radius_constraint=True))
        self.assertTrue(plan.points)
        self.assertTrue(all(parse_quantity(p["r_out"]).si_value > .04 for p in plan.points))
        with self.assertRaises(ValueError):
            generate_experiments(self.spec(ranges=(InputRange("r_out", "1[cm]", "2[cm]"),),
                                           fixed={"r_in": "40[mm]"}, radius_constraint=True))

    def test_invalid_ranges_and_limits(self):
        for spec in [self.spec(budget=0), self.spec(budget=501), self.spec(budget=True),
                     self.spec(seed=-1), self.spec(seed=True), self.spec(ranges=()),
                     self.spec(ranges=(InputRange("x", "2", "1"),)),
                     self.spec(ranges=(InputRange("x", "1[mm]", "2[A]"),)),
                     self.spec(ranges=(InputRange("x", "nan", "2"),)),
                     self.spec(ranges=(InputRange("N1", "2", "3"),)),
                     self.spec(ranges=(InputRange("N1", "2.5", "3", "integer"),)),
                     self.spec(ranges=(InputRange("x", "2[mm]", "3[mm]", "integer"),)),
                     self.spec(ranges=(InputRange("x", "2", "3", "bad"),)),
                     self.spec(ranges=(InputRange("x", "2", "3"), InputRange("x", "3", "4")))]:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                generate_experiments(spec)

    def test_contract_limits_protected_and_missing_inputs(self):
        contract = parse_model_contract({"schema_version": 1, "name": "example", "version": "1",
            "inputs": [{"name": "gap", "unit": "mm", "min": "50[mm]", "max": "150[mm]"}],
            "internal_parameters": ["N1"], "outputs": []})
        for spec in [self.spec(), self.spec(ranges=(InputRange("gap", "100[mm]", "200[mm]"),), fixed={}),
                     self.spec(ranges=(InputRange("N1", "2", "4", "integer"),), fixed={})]:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                generate_experiments(spec, contract)
        plan = generate_experiments(self.spec(ranges=(InputRange("gap", "100[mm]", "150[mm]"),), fixed={}), contract)
        self.assertEqual(len(plan.points), 30)

    def test_fixed_overflow_and_bad_names_fail_cleanly(self):
        for spec in [self.spec(fixed={"f0": "1e308[kHz]"}),
                     self.spec(ranges=(InputRange([], "0", "1"),)),
                     self.spec(ranges=("invalid",))]:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                generate_experiments(spec)


if __name__ == "__main__":
    unittest.main()
