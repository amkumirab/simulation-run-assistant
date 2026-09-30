import csv
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.types import Job, JobStatus
from simulation_assistant.wpt_circuit import (
    CircuitLimits,
    SeriesSeriesSettings,
    TwoPortData,
    TwoPortMetricMap,
    analyze_fixed_control_scenarios,
    extract_two_port,
    solve_series_series,
    suggest_two_port_metric_names,
    tune_series_series,
    write_circuit_study_csv,
    write_circuit_study_html,
)


class WptCircuitTests(unittest.TestCase):
    @staticmethod
    def _mapping() -> TwoPortMetricMap:
        return TwoPortMetricMap(
            frequency="frequency_Hz",
            primary_inductance="L1_H",
            secondary_inductance="L2_H",
            mutual_inductance_12="M12_H",
            mutual_inductance_21="M21_H",
            resistance_11="R1_ohm",
            resistance_22="R2_ohm",
            resistance_12="R12_ohm",
            resistance_21="R21_ohm",
        )

    @staticmethod
    def _metrics(mutual_h: float = 20e-6) -> dict[str, float]:
        return {
            "frequency_Hz": 85_000.0,
            "L1_H": 100e-6,
            "L2_H": 100e-6,
            "M12_H": mutual_h,
            "M21_H": mutual_h,
            "R1_ohm": 0.2,
            "R2_ohm": 0.2,
            "R12_ohm": 0.0,
            "R21_ohm": 0.0,
        }

    @classmethod
    def _job(
        cls,
        job_id: int,
        mutual_h: float = 20e-6,
        *,
        validation: str = "valid",
        status: JobStatus = JobStatus.SUCCEEDED,
        metrics: dict[str, float] | None = None,
    ) -> Job:
        result = None
        if status == JobStatus.SUCCEEDED:
            result = {
                "metrics": metrics if metrics is not None else cls._metrics(mutual_h),
                "metadata": {"scientific_validation": {"status": validation}},
            }
        return Job(
            id=job_id,
            batch_name="wpt-operating-points",
            adapter="comsol",
            status=status,
            parameters={"xoff": f"{job_id - 1}[cm]", "label": "<nominal>"},
            output_formulas={},
            result=result,
            error=None,
            artifact_dir=None,
            attempts=1,
            created_at="2026-09-29T00:00:00+00:00",
            started_at=None,
            finished_at="2026-09-29T00:01:00+00:00",
        )

    @staticmethod
    def _two_port(mutual_h: float = 20e-6) -> TwoPortData:
        return TwoPortData(
            frequency_hz=85_000.0,
            primary_inductance_h=100e-6,
            secondary_inductance_h=100e-6,
            mutual_inductance_12_h=mutual_h,
            mutual_inductance_21_h=mutual_h,
            resistance_11_ohm=0.2,
            resistance_22_ohm=0.2,
            resistance_12_ohm=0.0,
            resistance_21_ohm=0.0,
        )

    def test_extracts_accepted_two_port_metrics(self) -> None:
        result = extract_two_port(self._job(1), self._mapping())

        self.assertEqual(result.frequency_hz, 85_000.0)
        self.assertEqual(result.mutual_inductance_12_h, 20e-6)
        self.assertEqual(result.reciprocity_relative, 0.0)

    def test_suggests_canonical_and_alternate_metric_names(self) -> None:
        names = list(self._metrics())
        names[names.index("R1_ohm")] = "R11_ohm"
        suggestions = suggest_two_port_metric_names(names)

        self.assertEqual(suggestions["frequency"], "frequency_Hz")
        self.assertEqual(suggestions["resistance_11"], "R11_ohm")
        self.assertEqual(len(suggestions), 9)

    def test_rejects_missing_or_unaccepted_job_results(self) -> None:
        missing = self._metrics()
        missing.pop("M21_H")
        with self.assertRaisesRegex(ValueError, "M21_H"):
            extract_two_port(self._job(1, metrics=missing), self._mapping())
        with self.assertRaisesRegex(ValueError, "accepted scientific result"):
            extract_two_port(
                self._job(2, validation="rejected"),
                self._mapping(),
            )
        with self.assertRaisesRegex(ValueError, "did not complete"):
            extract_two_port(
                self._job(3, status=JobStatus.FAILED),
                self._mapping(),
            )

    def test_tunes_nominal_power_and_closes_energy_balance(self) -> None:
        settings = SeriesSeriesSettings(
            target_load_power_w=3700.0,
            load_min_ohm=0.01,
            load_max_ohm=20.0,
            load_samples=300,
        )
        controls, point = tune_series_series(self._two_port(), settings)

        self.assertAlmostEqual(point.load_ac_w, 3700.0, places=8)
        self.assertGreater(point.ac_efficiency, 0.95)
        self.assertLess(point.energy_balance_relative, 1e-12)
        self.assertGreater(controls.primary_capacitance_f, 0.0)
        self.assertGreater(controls.source_rms_v, 0.0)

    def test_series_series_solver_matches_power_accounting(self) -> None:
        controls, _point = tune_series_series(self._two_port(), SeriesSeriesSettings())
        point = solve_series_series(
            self._two_port(),
            controls.primary_capacitance_f,
            controls.secondary_capacitance_f,
            controls.load_ohm,
            source_rms_v=controls.source_rms_v,
            capacitor_esr_each_ohm=controls.capacitor_esr_each_ohm,
        )

        accounted = (
            point.load_ac_w
            + point.modeled_fem_loss_w
            + point.capacitor_esr_loss_w
        )
        self.assertAlmostEqual(point.input_ac_w, accounted, places=8)
        self.assertAlmostEqual(point.input_impedance_ohm[1], 0.0, places=9)

    def test_fixed_controls_flag_degraded_coupling_limits(self) -> None:
        limits = CircuitLimits(
            max_coil_current_rms_a=100.0,
            max_capacitor_voltage_rms_v=1200.0,
            min_load_power_retention=0.8,
        )
        study = analyze_fixed_control_scenarios(
            self._job(1),
            [self._job(2, 5e-6), self._job(3, validation="rejected")],
            self._mapping(),
            limits=limits,
        )

        self.assertEqual(study.nominal_job_id, 1)
        self.assertEqual(study.passed_count, 1)
        self.assertEqual(study.failed_count, 1)
        self.assertEqual(study.ineligible_count, 1)
        degraded = next(item for item in study.scenarios if item.job_id == 2)
        self.assertEqual(degraded.status, "failed")
        self.assertFalse(degraded.checks["coil_current"])
        self.assertFalse(degraded.checks["capacitor_voltage"])

    def test_fixed_controls_reject_a_different_result_frequency(self) -> None:
        changed = self._metrics()
        changed["frequency_Hz"] = 90_000.0
        study = analyze_fixed_control_scenarios(
            self._job(1),
            [self._job(2, metrics=changed)],
            self._mapping(),
        )

        scenario = next(item for item in study.scenarios if item.job_id == 2)
        self.assertEqual(scenario.status, "ineligible")
        self.assertIn("fixed nominal frequency", scenario.message)

    def test_rejects_nonpassive_two_port(self) -> None:
        invalid = TwoPortData(
            frequency_hz=85_000.0,
            primary_inductance_h=100e-6,
            secondary_inductance_h=100e-6,
            mutual_inductance_12_h=20e-6,
            mutual_inductance_21_h=20e-6,
            resistance_11_ohm=0.2,
            resistance_22_ohm=0.2,
            resistance_12_ohm=0.5,
            resistance_21_ohm=0.5,
        )
        with self.assertRaisesRegex(ValueError, "not passive"):
            tune_series_series(invalid, SeriesSeriesSettings())

    def test_exports_portable_csv_and_escaped_html(self) -> None:
        study = analyze_fixed_control_scenarios(
            self._job(1),
            [self._job(2, 15e-6)],
            self._mapping(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = write_circuit_study_csv(
                Path(temp_dir) / "circuit.csv",
                study,
            )
            html_path = write_circuit_study_html(
                Path(temp_dir) / "circuit.html",
                study,
            )
            with csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            html_text = html_path.read_text(encoding="utf-8")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["job_id"], "1")
        self.assertEqual(rows[0]["fixed_frequency_hz"], "85000.0")
        self.assertEqual(rows[0]["check_coil_current"], "True")
        self.assertIn("Series-Series Circuit Study", html_text)
        self.assertIn("Current limit: 100 A RMS", html_text)
        self.assertIn("&lt;nominal&gt;", html_text)
        self.assertNotIn(".mph", html_text)

    def test_rejects_invalid_configuration(self) -> None:
        with self.assertRaisesRegex(ValueError, "unique"):
            TwoPortMetricMap(*(["same"] * 9))
        with self.assertRaisesRegex(ValueError, "at least 20"):
            SeriesSeriesSettings(load_samples=19)
        with self.assertRaisesRegex(ValueError, "at least 20"):
            SeriesSeriesSettings(load_samples=20.5)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "between zero and one"):
            CircuitLimits(min_load_power_retention=1.1)


if __name__ == "__main__":
    unittest.main()
