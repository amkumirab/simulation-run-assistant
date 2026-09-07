import unittest

from simulation_assistant.validation import (
    parse_validation_policy,
    validate_scientific_result,
)


class ScientificValidationTests(unittest.TestCase):
    def policy(self):
        return parse_validation_policy(
            {
                "required_metrics": [
                    "primary_inductance",
                    "secondary_inductance",
                    "coupling",
                    "efficiency",
                    "mutual_inductance_12",
                    "mutual_inductance_21",
                ],
                "require_fresh_pipeline": True,
                "bounds": [
                    {
                        "metric": "primary_inductance",
                        "min": 0,
                        "unit": "H",
                        "exclusive_min": True,
                    },
                    {"metric": "coupling", "min": 0, "max": 1},
                    {
                        "metric": "efficiency",
                        "min": 0,
                        "max": 100,
                        "unit": "%",
                    },
                ],
                "reciprocity": [
                    {
                        "left": "mutual_inductance_12",
                        "right": "mutual_inductance_21",
                        "relative_tolerance": 0.02,
                    }
                ],
            },
            metric_units={"primary_inductance": "H", "efficiency": "%"},
        )

    def test_accepts_fresh_bounded_reciprocal_wpt_result(self) -> None:
        report = validate_scientific_result(
            {
                "primary_inductance": 1.2e-6,
                "secondary_inductance": 1.1e-6,
                "coupling": 0.73,
                "efficiency": 91.0,
                "mutual_inductance_12": 0.8e-6,
                "mutual_inductance_21": 0.79e-6,
            },
            {
                "result_pipeline": {"status": "fresh"},
                "solver_diagnostics": {
                    "warnings": [],
                    "errors": [],
                    "convergence_issues": [],
                },
            },
            self.policy(),
        )

        self.assertEqual(report.status, "valid")
        self.assertEqual(report.findings, ())

    def test_rejects_stale_missing_unphysical_and_nonreciprocal_result(self) -> None:
        report = validate_scientific_result(
            {
                "primary_inductance": 0.0,
                "secondary_inductance": float("nan"),
                "coupling": 1.2,
                "efficiency": 105.0,
                "mutual_inductance_12": 1.0,
                "mutual_inductance_21": 0.8,
            },
            {
                "result_pipeline": {"status": "stale"},
                "solver_diagnostics": {
                    "warnings": [],
                    "errors": [],
                    "convergence_issues": ["Failed to find a solution"],
                },
            },
            self.policy(),
        )

        self.assertEqual(report.status, "rejected")
        codes = {finding.code for finding in report.findings}
        self.assertTrue(
            {
                "non_finite_metric",
                "required_metric_missing",
                "result_pipeline_not_fresh",
                "metric_out_of_bounds",
                "reciprocity_tolerance_exceeded",
                "convergence_issues_detected",
            }.issubset(codes)
        )

    def test_solver_and_formula_warnings_do_not_reject_by_default(self) -> None:
        report = validate_scientific_result(
            {"value": 1.0},
            {
                "solver_diagnostics": {
                    "warnings": ["Warning: mesh is coarse"],
                    "errors": [],
                    "convergence_issues": [],
                },
                "formula_errors": {"ratio": "missing symbol"},
            },
        )

        self.assertEqual(report.status, "warning")
        self.assertEqual(len(report.findings), 2)

    def test_rejects_invalid_policy_definitions(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires min or max"):
            parse_validation_policy({"bounds": [{"metric": "coupling"}]})
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            parse_validation_policy(
                {
                    "reciprocity": [
                        {
                            "left": "m12",
                            "right": "m21",
                            "relative_tolerance": 1.1,
                        }
                    ]
                }
            )
        with self.assertRaisesRegex(ValueError, "must match output unit"):
            parse_validation_policy(
                {"bounds": [{"metric": "efficiency", "max": 1, "unit": "1"}]},
                metric_units={"efficiency": "%"},
            )
        with self.assertRaisesRegex(ValueError, "supported unit"):
            parse_validation_policy(
                {"bounds": [{"metric": "coupling", "max": 1, "unit": "parsec"}]}
            )


if __name__ == "__main__":
    unittest.main()
