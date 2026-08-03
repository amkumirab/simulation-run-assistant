import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from simulation_assistant.adapters.comsol import (
    ComsolAdapter,
    ComsolConfig,
    check_comsol,
    extract_mph_tables,
    inspect_mph,
)


class FakeComsolProcess:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        command = [str(value) for value in command]
        self.commands.append(command)
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "COMSOL 6.3\n", "")
        if "-checklicense" in command:
            return subprocess.CompletedProcess(command, 0, "COMSOL\nACDC\n", "")

        input_model = Path(command[command.index("-inputfile") + 1])
        output_model = Path(command[command.index("-outputfile") + 1])
        batch_log = Path(command[command.index("-batchlog") + 1])
        shutil.copy2(input_model, output_model)
        batch_log.write_text("COMSOL batch completed\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")


class ComsolAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.executable = self.root / "comsolbatch.exe"
        self.executable.write_bytes(b"fake")
        self.model = self.root / "source.mph"
        _write_test_mph(self.model)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def config(self, *, use_job: bool = False) -> ComsolConfig:
        return ComsolConfig(
            executable=self.executable,
            model_path=self.model,
            study_tag=None if use_job else "std1",
            job_tag="batch1" if use_job else None,
            timeout_seconds=30,
            cores=2,
        )

    def test_inspects_model_contract(self) -> None:
        info = inspect_mph(self.model)

        self.assertEqual(info.comsol_version, "6.3.0.290")
        self.assertEqual(info.required_products, ["COMSOL", "ACDC"])
        self.assertEqual(info.parameters, {"frequency": "85[kHz]"})
        self.assertEqual(info.studies, [{"tag": "std1", "label": "Study 1"}])

    def test_extracts_scalar_metrics_and_series_tables(self) -> None:
        tables = extract_mph_tables(self.model)

        self.assertEqual(tables[0]["columns"], ["frequency (Hz)", "value (H)"])
        self.assertEqual(tables[0]["rows"], [[85000.0, 1.2e-7]])
        self.assertEqual(tables[1]["row_count"], 2)

    def test_runs_copied_model_with_parameters(self) -> None:
        fake_process = FakeComsolProcess()
        work_dir = self.root / "job"
        result = ComsolAdapter(self.config(use_job=True), fake_process).run(
            {"frequency": "90[kHz]", "turns": 12},
            work_dir=work_dir,
        )

        self.assertTrue((work_dir / "input.mph").exists())
        self.assertTrue((work_dir / "output.mph").exists())
        self.assertTrue((work_dir / "comsol.log").exists())
        command = fake_process.commands[0]
        self.assertIn("-job", command)
        self.assertIn("batch1", command)
        self.assertEqual(
            command[command.index("-pname") + 1],
            "frequency,turns",
        )
        self.assertEqual(
            command[command.index("-plist") + 1],
            "90[kHz],12",
        )
        self.assertIn("tbl1_1_frequency_hz", result.metrics)
        self.assertEqual(len(result.series), 2)

    def test_study_run_does_not_present_saved_tables_as_fresh(self) -> None:
        result = ComsolAdapter(self.config(), FakeComsolProcess()).run(
            {"frequency": "90[kHz]"},
            work_dir=self.root / "study-job",
        )

        self.assertNotIn("tbl1_1_frequency_hz", result.metrics)
        self.assertEqual(result.series, [])
        self.assertEqual(
            result.metadata["table_results_status"],
            "saved_not_recomputed_by_study_command",
        )
        self.assertEqual(result.metadata["output_model_parameters"]["frequency"], "85[kHz]")

    def test_rejects_ambiguous_parameter_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "comma or newline"):
            ComsolAdapter(self.config(), FakeComsolProcess()).run(
                {"frequency": "range(1,1,3)"},
                work_dir=self.root / "job",
            )

    def test_check_runs_version_and_license_validation(self) -> None:
        fake_process = FakeComsolProcess()

        report = check_comsol(self.config(), fake_process)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["selected_study"], "std1")
        self.assertEqual(report["license_requirements"], ["COMSOL", "ACDC"])
        self.assertEqual(len(fake_process.commands), 2)


def _write_test_mph(path: Path) -> None:
    model_info = """<?xml version="1.0" encoding="UTF-8"?>
<modelInfo comsolVersion="6.3.0.290" modelType="MODEL" isRunnable="true">
  <physicsInfo physics="Magnetic_fields" />
</modelInfo>
"""
    smodel = {
        "apiClass": "Model",
        "nodes": [
            {
                "apiClass": "ModelParamGroup",
                "settings": [{"name": "frequency", "value": "85[kHz]"}],
            },
            {"apiClass": "Study", "tag": "std1", "label": "Study 1"},
            {
                "apiClass": "NumericalFeature",
                "apiType": "EvalGlobal",
                "tag": "gev1",
                "label": "Global Evaluation 1",
            },
        ],
    }
    dmodel = """<?xml version="1.0" encoding="UTF-8"?>
<Model>
  <TableFeature tag="tbl1" name="Metrics">
    <realData>85000.0,1.2E-7</realData>
    <columnHeaders>2,'frequency (Hz)','value (H)'</columnHeaders>
  </TableFeature>
  <TableFeature tag="tbl2" name="Sweep">
    <realData>80000.0,1.0E-7,90000.0,1.4E-7</realData>
    <columnHeaders>2,'frequency (Hz)','value (H)'</columnHeaders>
  </TableFeature>
</Model>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("modelinfo.xml", model_info)
        archive.writestr("smodel.json", json.dumps(smodel))
        archive.writestr("dmodel.xml", dmodel)
        archive.writestr("usedlicenses.txt", "COMSOL\nACDC\n")


if __name__ == "__main__":
    unittest.main()
