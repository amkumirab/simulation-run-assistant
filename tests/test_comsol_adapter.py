import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from simulation_assistant.adapters.comsol import (
    ComsolAdapter,
    ComsolConfig,
    check_comsol,
    catalog_mph_output_symbols,
    extract_mph_tables,
    inspect_mph,
    validate_plot_selection,
)
from simulation_assistant.adapters.base import SimulationCancelled


class FakeComsolProcess:
    def __init__(self, *, failed_plot_tags: set[str] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.failed_plot_tags = failed_plot_tags or set()

    def __call__(self, command, **kwargs):
        command = [str(value) for value in command]
        self.commands.append(command)
        if "-version" in command:
            return subprocess.CompletedProcess(command, 0, "COMSOL 6.3\n", "")
        if "-checklicense" in command:
            return subprocess.CompletedProcess(command, 0, "COMSOL\nACDC\n", "")
        if Path(command[0]).stem == "comsolcompile":
            Path(command[-1]).with_suffix(".class").write_bytes(b"compiled")
            return subprocess.CompletedProcess(command, 0, "", "")
        if "-prodargs" in command:
            arguments = command[command.index("-prodargs") + 1 :]
            log_lines: list[str] = []
            for index in range(1, len(arguments), 2):
                tag = arguments[index]
                image_path = Path(arguments[index + 1])
                if tag in self.failed_plot_tags:
                    log_lines.append(
                        f"SIMULATION_ASSISTANT_PLOT_ERROR\t{tag}\tPlot data is unavailable"
                    )
                else:
                    image_path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
            batch_log = Path(command[command.index("-batchlog") + 1])
            batch_log.write_text(
                "COMSOL plot export completed\n" + "\n".join(log_lines),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

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
        self.compiler = self.root / "comsolcompile.exe"
        self.compiler.write_bytes(b"fake")
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
            plot_tags=("pg1",),
        )

    def test_inspects_model_contract(self) -> None:
        info = inspect_mph(self.model)

        self.assertEqual(info.comsol_version, "6.3.0.290")
        self.assertEqual(info.required_products, ["COMSOL", "ACDC"])
        self.assertEqual(info.parameters, {"frequency": "85[kHz]"})
        self.assertEqual(info.studies, [{"tag": "std1", "label": "Study 1"}])
        self.assertEqual(
            info.plot_groups,
            [
                {
                    "tag": "pg1",
                    "label": "Magnetic Flux Density",
                    "type": "PlotGroup2D",
                    "dimension": "2D",
                },
                {
                    "tag": "pg2",
                    "label": "Revolved Geometry",
                    "type": "PlotGroup3D",
                    "dimension": "3D",
                },
            ],
        )

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
        self.assertEqual(result.metadata["plot_export_status"], "succeeded")
        self.assertEqual(result.metadata["plot_exports"][0]["tag"], "pg1")
        self.assertTrue(Path(result.metadata["plot_exports"][0]["path"]).is_file())
        self.assertEqual(len(fake_process.commands), 3)

    def test_uses_cancellable_runner_for_an_active_queue_job(self) -> None:
        checks = iter([False, True])

        def cancel_requested():
            return next(checks)

        def stopped_process(command, **kwargs):
            self.assertTrue(kwargs["cancel_requested"]())
            raise SimulationCancelled("Stop requested by user")

        adapter = ComsolAdapter(
            self.config(),
            FakeComsolProcess(),
            cancellable_process_runner=stopped_process,
        )

        with self.assertRaisesRegex(SimulationCancelled, "Stop requested"):
            adapter.run(
                {"frequency": "90[kHz]"},
                work_dir=self.root / "stopped-job",
                cancel_requested=cancel_requested,
            )

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

    def test_plot_export_failure_does_not_discard_successful_solution(self) -> None:
        result = ComsolAdapter(
            self.config(),
            FakeComsolProcess(failed_plot_tags={"pg1"}),
        ).run(
            {"frequency": "90[kHz]"},
            work_dir=self.root / "plot-failure-job",
        )

        self.assertEqual(result.metadata["plot_export_status"], "failed")
        self.assertEqual(result.metadata["plot_exports"], [])
        self.assertEqual(
            result.metadata["plot_export_errors"]["pg1"],
            "Plot data is unavailable",
        )
        self.assertTrue(Path(result.metadata["output_model"]).is_file())

    def test_one_plot_failure_does_not_block_other_selected_plots(self) -> None:
        result = ComsolAdapter(
            replace(self.config(), plot_tags=("pg1", "pg2")),
            FakeComsolProcess(failed_plot_tags={"pg2"}),
        ).run(
            {"frequency": "90[kHz]"},
            work_dir=self.root / "partial-plot-job",
        )

        self.assertEqual(result.metadata["plot_export_status"], "partial")
        self.assertEqual(
            [item["tag"] for item in result.metadata["plot_exports"]],
            ["pg1"],
        )
        self.assertEqual(
            result.metadata["plot_export_errors"]["pg2"],
            "Plot data is unavailable",
        )

    def test_skips_plot_export_when_no_plot_is_selected(self) -> None:
        fake_process = FakeComsolProcess()
        result = ComsolAdapter(
            replace(self.config(), plot_tags=()),
            fake_process,
        ).run(
            {"frequency": "90[kHz]"},
            work_dir=self.root / "no-plot-job",
        )

        self.assertEqual(result.metadata["plot_export_status"], "not_requested")
        self.assertEqual(result.metadata["plot_exports"], [])
        self.assertEqual(len(fake_process.commands), 1)

    def test_missing_plot_compiler_is_reported_without_failing_the_job(self) -> None:
        self.compiler.unlink()
        result = ComsolAdapter(self.config(), FakeComsolProcess()).run(
            {"frequency": "90[kHz]"},
            work_dir=self.root / "missing-compiler-job",
        )

        self.assertEqual(result.metadata["plot_export_status"], "failed")
        self.assertIn(
            "compiler was not found",
            result.metadata["plot_export_errors"]["pg1"],
        )
        self.assertTrue(Path(result.metadata["output_model"]).is_file())

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
        self.assertEqual(report["output_symbols"][0]["key"], "tbl1_1_frequency_hz")
        self.assertEqual(report["selected_plot_groups"][0]["tag"], "pg1")
        self.assertEqual(len(report["model"]["plot_groups"]), 2)
        self.assertEqual(len(fake_process.commands), 2)

    def test_catalogs_formula_symbols_from_scalar_tables(self) -> None:
        symbols = catalog_mph_output_symbols(self.model)

        self.assertEqual(len(symbols), 2)
        self.assertEqual(symbols[1]["column"], "value (H)")
        self.assertEqual(symbols[1]["saved_value"], 1.2e-7)

    def test_validates_plot_group_selection(self) -> None:
        plots = inspect_mph(self.model).plot_groups

        selected = validate_plot_selection(["pg2", "pg1"], plots)

        self.assertEqual([plot["tag"] for plot in selected], ["pg2", "pg1"])
        with self.assertRaisesRegex(ValueError, "not found"):
            validate_plot_selection(["missing"], plots)
        with self.assertRaisesRegex(ValueError, "duplicated"):
            validate_plot_selection(["pg1", "pg1"], plots)
        with self.assertRaisesRegex(ValueError, "no more than"):
            validate_plot_selection([f"pg{index}" for index in range(13)], plots)


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
            {
                "apiClass": "ResultFeature",
                "apiType": "PlotGroup2D",
                "tag": "pg1",
                "label": "Magnetic Flux Density",
            },
            {
                "apiClass": "ResultFeature",
                "apiType": "PlotGroup3D",
                "tag": "pg2",
                "label": "Revolved Geometry",
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
