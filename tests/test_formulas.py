import unittest

from simulation_assistant.formulas import (
    evaluate_output_formulas,
    validate_output_formulas,
)


class FormulaTests(unittest.TestCase):
    def test_evaluates_engineering_formula_and_dependencies(self) -> None:
        evaluation = evaluate_output_formulas(
            {
                "coupling": "mutual / sqrt(primary * secondary)",
                "coupling_percent": "coupling * 100",
            },
            {"mutual": 2.0, "primary": 4.0, "secondary": 9.0},
        )

        self.assertAlmostEqual(evaluation.values["coupling"], 1 / 3)
        self.assertAlmostEqual(evaluation.values["coupling_percent"], 100 / 3)
        self.assertEqual(evaluation.errors, {})

    def test_reports_missing_metrics_without_losing_other_values(self) -> None:
        evaluation = evaluate_output_formulas(
            {"valid": "duration * 2", "missing": "inductance * 10"},
            {"duration": 3.5},
        )

        self.assertEqual(evaluation.values, {"valid": 7.0})
        self.assertIn("not available", evaluation.errors["missing"])

    def test_rejects_code_execution_and_attribute_access(self) -> None:
        invalid = {
            "dangerous": "__import__('os').system('whoami')",
            "attribute": "value.real",
        }

        for name, expression in invalid.items():
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "unsupported syntax"):
                    validate_output_formulas({name: expression})

    def test_rejects_invalid_formula_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "Formula names"):
            validate_output_formulas({"coupling factor": "1 + 1"})


if __name__ == "__main__":
    unittest.main()
