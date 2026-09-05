import json
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.model_contract import (
    apply_output_bindings,
    evaluate_model_contract,
    load_model_contract,
    parse_model_contract,
    validate_contract_parameters,
)


def contract_data() -> dict:
    return {
        "schema_version": 1,
        "name": "wpt-baseline",
        "version": "1.0.0",
        "required_physics": ["Magnetic_fields"],
        "require_runnable": True,
        "target": {"kind": "job", "tag": "batch1"},
        "dataset_tag": "dset1",
        "inputs": [
            {
                "name": "frequency",
                "unit": "kHz",
                "min": "70[kHz]",
                "max": "100[kHz]",
            },
            {"name": "gap", "unit": "mm", "required": False},
        ],
        "internal_parameters": ["coil_turns"],
        "outputs": [
            {
                "name": "inductance",
                "table_tag": "tbl1",
                "column": "value (H)",
                "unit": "H",
            }
        ],
    }


def model_data() -> dict:
    return {
        "runnable": True,
        "physics": ["Magnetic_fields"],
        "parameters": {
            "frequency": "85[kHz]",
            "gap": "15[mm]",
            "coil_turns": "10",
        },
        "studies": [{"tag": "std1"}],
        "jobs": [
            {
                "tag": "batch1",
                "steps": [
                    {"tag": "solve1", "category": "solve"},
                    {"tag": "eval1", "category": "evaluation"},
                ],
            }
        ],
        "datasets": [{"tag": "dset1", "study_tag": "std1"}],
        "numerical_features": [
            {
                "tag": "gev1",
                "dataset_tag": "dset1",
                "table_tag": "tbl1",
            }
        ],
        "tables": [{"tag": "tbl1", "columns": ["value (H)"]}],
    }


class ModelContractTests(unittest.TestCase):
    def test_loads_versioned_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "contract.json"
            path.write_text(json.dumps(contract_data()), encoding="utf-8")
            contract = load_model_contract(path)

        self.assertEqual(contract.name, "wpt-baseline")
        self.assertEqual(contract.inputs[0].minimum, "70[kHz]")
        self.assertEqual(contract.outputs[0].table_tag, "tbl1")

    def test_reports_ready_and_builds_stable_output_binding(self) -> None:
        contract = parse_model_contract(contract_data())
        report = evaluate_model_contract(
            contract,
            model_data(),
            [
                {
                    "key": "tbl1_2_value_h",
                    "table_tag": "tbl1",
                    "column": "value (H)",
                    "unit": "H",
                }
            ],
            selected_study=None,
            selected_job="batch1",
        )

        self.assertEqual(report.status, "ready")
        self.assertEqual(report.design_inputs, ("frequency", "gap"))
        self.assertEqual(
            apply_output_bindings({"tbl1_2_value_h": 1.2e-7}, report)["inductance"],
            1.2e-7,
        )

    def test_blocks_missing_model_features_and_study_output_freshness(self) -> None:
        data = contract_data()
        data["target"] = {"kind": "study", "tag": "std1"}
        contract = parse_model_contract(data)
        model = model_data()
        model["runnable"] = False
        model["parameters"].pop("frequency")
        model["parameters"].pop("coil_turns")
        model["datasets"] = []
        report = evaluate_model_contract(
            contract,
            model,
            [],
            selected_study="std1",
            selected_job=None,
        )

        self.assertEqual(report.status, "blocked")
        codes = {issue.code for issue in report.issues}
        self.assertTrue(
            {
                "model_not_runnable",
                "dataset_not_found",
                "missing_input",
                "missing_internal_parameter",
                "missing_output",
            }.issubset(codes)
        )

    def test_blocks_an_output_scale_change(self) -> None:
        data = contract_data()
        data["outputs"][0]["unit"] = "mH"
        report = evaluate_model_contract(
            parse_model_contract(data),
            model_data(),
            [
                {
                    "key": "tbl1_2_value_h",
                    "table_tag": "tbl1",
                    "column": "value (H)",
                    "unit": "H",
                }
            ],
            selected_study=None,
            selected_job="batch1",
        )

        self.assertEqual(report.status, "blocked")
        self.assertIn("output_unit_mismatch", {issue.code for issue in report.issues})

    def test_blocks_job_outputs_when_evaluation_step_is_missing(self) -> None:
        model = model_data()
        model["jobs"][0]["steps"] = [{"tag": "solve1", "category": "solve"}]
        report = evaluate_model_contract(
            parse_model_contract(contract_data()),
            model,
            [
                {
                    "key": "tbl1_2_value_h",
                    "table_tag": "tbl1",
                    "column": "value (H)",
                    "unit": "H",
                }
            ],
            selected_study=None,
            selected_job="batch1",
        )

        self.assertEqual(report.status, "blocked")
        self.assertIn(
            "fresh_output_pipeline_unverified",
            {issue.code for issue in report.issues},
        )

    def test_rejects_invalid_run_units_limits_and_internal_overrides(self) -> None:
        contract = parse_model_contract(contract_data())

        with self.assertRaisesRegex(ValueError, "below the minimum"):
            validate_contract_parameters(contract, [{"frequency": "60[kHz]"}])
        with self.assertRaisesRegex(ValueError, "compatible"):
            validate_contract_parameters(contract, [{"frequency": "85[mm]"}])
        with self.assertRaisesRegex(ValueError, "internal parameter"):
            validate_contract_parameters(
                contract,
                [{"frequency": "85[kHz]", "coil_turns": "12"}],
            )

    def test_rejects_invalid_contract_definitions(self) -> None:
        invalid = contract_data()
        invalid["inputs"][0]["min"] = "100[kHz]"
        invalid["inputs"][0]["max"] = "70[kHz]"
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            parse_model_contract(invalid)

        invalid = contract_data()
        invalid["outputs"][0]["unit"] = "not-a-unit"
        with self.assertRaisesRegex(ValueError, "supported unit"):
            parse_model_contract(invalid)


if __name__ == "__main__":
    unittest.main()
