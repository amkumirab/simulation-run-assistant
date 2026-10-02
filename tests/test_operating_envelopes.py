import math
import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from simulation_assistant.design_campaigns import (
    DesignCandidate, Scenario, analyze_design_campaign, build_design_campaign,
)
from simulation_assistant.operating_envelopes import EnvelopeLimits, analyze_operating_envelope
from simulation_assistant.envelope_reports import write_envelope_csv, write_envelope_html
from simulation_assistant.wpt_circuit import CircuitLimits, extract_two_port, solve_with_controls
import test_design_campaigns as fixtures

MAPPING, job = fixtures.MAPPING, fixtures.job


class OperatingEnvelopeTests(unittest.TestCase):
    def fixture(self, circuit_limits=None):
        initial = fixtures.DesignCampaignTests().plan()
        jobs = [job(index + 1, state.parameters) for index, state in enumerate(initial.campaign.states)]
        plan = fixtures.DesignCampaignTests().plan(jobs=jobs)
        report = analyze_design_campaign(plan, jobs, MAPPING, limits=circuit_limits)
        return report, jobs

    def test_target_power_is_reached_without_retuning(self):
        campaign, jobs = self.fixture()
        result = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(1000))
        self.assertEqual(result.designs[0].status, "target_met")
        self.assertEqual(len(result.rows), 2)
        point = result.rows[0].operating_point
        self.assertAlmostEqual(point.load_ac_w, 3700, places=7)
        controls = result.designs[0].controls
        self.assertEqual(controls, campaign.designs[0].study.controls)
        direct = solve_with_controls(extract_two_port(jobs[0], MAPPING),
                                     replace(controls, source_rms_v=point.source_rms_v))
        self.assertEqual(point, direct)

    def test_source_voltage_can_force_derating(self):
        campaign, jobs = self.fixture()
        row = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(1)).rows[0]
        self.assertEqual(row.status, "derated")
        self.assertEqual(row.limiting_constraints, ("source_voltage",))
        self.assertAlmostEqual(row.operating_point.source_rms_v, 1)
        self.assertLess(row.maximum_load_power_w, 3700)
        self.assertFalse(row.minimum_retention_met)

    def test_each_component_bounds_maximum_voltage(self):
        campaign, jobs = self.fixture(CircuitLimits(1000, 1e6))
        first = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(1e5)).rows[0]
        self.assertEqual(len(first.source_ceilings_rms_v), 5)
        self.assertAlmostEqual(first.maximum_source_rms_v, min(first.source_ceilings_rms_v.values()))
        for name in ("primary_current", "secondary_current", "primary_capacitor", "secondary_capacitor"):
            self.assertGreater(first.source_ceilings_rms_v[name], 0)

    def test_invalid_limits_are_rejected(self):
        for value in (0, -1, True, "400", math.inf, math.nan, 10**400):
            with self.subTest(value=value), self.assertRaises(ValueError):
                EnvelopeLimits(value)

    def test_current_and_capacitor_limits_independently_force_derating(self):
        for limits, binding in ((CircuitLimits(1, 1e9), "current"),
                                (CircuitLimits(1e9, 1), "capacitor")):
            with self.subTest(binding=binding):
                campaign, jobs = self.fixture(limits)
                row = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(1e6)).rows[0]
                self.assertEqual(row.status, "derated")
                self.assertTrue(any(binding in name for name in row.limiting_constraints))
                self.assertTrue(all(row.checks.values()))
                self.assertLessEqual(row.operating_point.max_coil_current_rms_a, limits.max_coil_current_rms_a * (1+1e-10))
                self.assertLessEqual(row.operating_point.max_capacitor_voltage_rms_v, limits.max_capacitor_voltage_rms_v * (1+1e-10))

    def test_all_four_component_ceilings_match_direct_unit_solution(self):
        campaign, jobs = self.fixture()
        controls = campaign.designs[0].study.controls
        unit = solve_with_controls(extract_two_port(jobs[0], MAPPING), replace(controls, source_rms_v=1))
        row = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(400)).rows[0]
        for key, expected in (
            ("primary_current", 100/unit.primary_current_rms_a),
            ("secondary_current", 100/unit.secondary_current_rms_a),
            ("primary_capacitor", 1200/unit.primary_capacitor_rms_v),
            ("secondary_capacitor", 1200/unit.secondary_capacitor_rms_v),
        ):
            self.assertAlmostEqual(row.source_ceilings_rms_v[key], expected)

    def test_boundary_target_and_tied_limits_are_reported(self):
        campaign, jobs = self.fixture()
        controls = campaign.designs[0].study.controls
        row = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(controls.source_rms_v)).rows[0]
        self.assertEqual(row.status, "target_met")
        unit = solve_with_controls(extract_two_port(jobs[0], MAPPING), replace(controls, source_rms_v=1))
        ceiling = 100/unit.max_coil_current_rms_a
        campaign = replace(campaign, limits=CircuitLimits(100, unit.max_capacitor_voltage_rms_v*ceiling))
        row = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(ceiling)).rows[0]
        self.assertIn("source_voltage", row.limiting_constraints)
        self.assertTrue(any("current" in name for name in row.limiting_constraints))
        self.assertTrue(any("capacitor" in name for name in row.limiting_constraints))

    def test_amplitude_scaling_preserves_efficiency_and_quadratic_power(self):
        campaign, jobs = self.fixture()
        low = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(1)).rows[0]
        high = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(2)).rows[0]
        self.assertAlmostEqual(high.operating_point.load_ac_w, 4*low.operating_point.load_ac_w)
        self.assertAlmostEqual(high.operating_point.primary_current_rms_a, 2*low.operating_point.primary_current_rms_a)
        self.assertAlmostEqual(high.operating_point.ac_efficiency, low.operating_point.ac_efficiency)

    def test_acceptance_is_rechecked_instead_of_using_cached_points(self):
        campaign, jobs = self.fixture()
        jobs[1] = replace(jobs[1], result={"metrics": jobs[1].result["metrics"],
                              "metadata": {"scientific_validation": {"status": "rejected"}}})
        result = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(400))
        self.assertEqual(result.rows[1].status, "unavailable")
        self.assertEqual(result.designs[0].status, "incomplete")
        self.assertIsNone(result.designs[0].worst_case_maximum_load_power_w)

    def test_missing_nominal_is_not_replaced_by_another_scenario(self):
        campaign, jobs = self.fixture()
        result = analyze_operating_envelope(campaign, jobs[1:], EnvelopeLimits(400))
        self.assertTrue(all(row.status == "unavailable" for row in result.rows))
        self.assertIsNone(result.designs[0].controls)

    def test_no_transfer_is_unavailable_not_zero_power_approval(self):
        campaign, jobs = self.fixture()
        values = dict(jobs[1].result["metrics"], M12_H=0, M21_H=0)
        jobs[1] = replace(jobs[1], result={**jobs[1].result, "metrics": values})
        result = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(400))
        self.assertEqual(result.rows[1].status, "unavailable")
        self.assertIsNone(result.rows[1].operating_point)

    def test_stale_signatures_model_and_formula_identity_are_not_reused(self):
        campaign, jobs = self.fixture()
        for changed in (replace(jobs[1], run_signature="stale"),
                        replace(jobs[1], parameters={**jobs[1].parameters, "xoff": "40[mm]"}),
                        replace(jobs[1], run_context={"other": "model"}),
                        replace(jobs[1], output_formulas={"other": "1"})):
            with self.subTest(changed=changed):
                result = analyze_operating_envelope(campaign, [jobs[0], changed], EnvelopeLimits(400))
                self.assertEqual(result.rows[1].status, "unavailable")
                self.assertEqual(result.designs[0].status, "incomplete")

    def test_invalid_metric_and_frequency_mismatch_are_isolated(self):
        campaign, jobs = self.fixture()
        for metrics in (dict(jobs[1].result["metrics"], frequency_Hz=90000),
                        dict(jobs[1].result["metrics"], R1_ohm=math.nan),
                        dict(jobs[1].result["metrics"], R12_ohm=2, R21_ohm=2)):
            changed = replace(jobs[1], result={**jobs[1].result, "metrics": metrics})
            result = analyze_operating_envelope(campaign, [jobs[0], changed], EnvelopeLimits(400))
            self.assertEqual(result.rows[0].status, "target_met")
            self.assertEqual(result.rows[1].status, "unavailable")

    def test_two_designs_keep_independent_controls_and_isolate_bad_nominal(self):
        designs = [fixtures.design(), fixtures.design("B", "110[mm]", 3)]
        initial = fixtures.DesignCampaignTests().plan(designs=designs)
        jobs = [job(index+1, state.parameters, values=fixtures.metrics(100e-6 if index < 2 else 120e-6))
                for index, state in enumerate(initial.campaign.states)]
        plan = fixtures.DesignCampaignTests().plan(designs=designs, jobs=jobs)
        campaign = analyze_design_campaign(plan, jobs, MAPPING)
        report = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(400))
        self.assertNotEqual(report.designs[0].controls.primary_capacitance_f,
                            report.designs[1].controls.primary_capacitance_f)
        unaffected = report.designs[1]
        jobs[0] = replace(jobs[0], result={**jobs[0].result, "metrics": dict(jobs[0].result["metrics"], frequency_Hz=1e308)})
        report = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(400))
        self.assertEqual(report.designs[0].status, "incomplete")
        self.assertEqual(report.designs[1], unaffected)

    def test_energy_balance_failure_is_not_an_electrical_pass(self):
        campaign, jobs = self.fixture(CircuitLimits(max_energy_balance_relative=0))
        report = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(400))
        self.assertTrue(all(row.status == "unavailable" for row in report.rows))
        self.assertIsNone(report.designs[0].worst_case_maximum_load_power_w)

    def test_warning_validation_remains_visible(self):
        campaign, jobs = self.fixture()
        jobs[1] = replace(jobs[1], result={**jobs[1].result, "metadata": {"scientific_validation": {"status": "warning"}}})
        report = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(400))
        self.assertEqual(report.rows[1].status, "target_met")
        self.assertEqual(report.rows[1].validation_status, "warning")

    def test_real_stored_cases_require_two_derating_decisions(self):
        dataset = json.loads((Path(__file__).parents[1] / "examples/wpt_circuit_results.json").read_text(encoding="utf-8"))
        jobs = [job(index+1, {**dataset["geometry"], **case["parameters"]}, values=case["metrics"])
                for index, case in enumerate(dataset["cases"])]
        scenarios = [Scenario("Nominal", {})] + [Scenario(case["name"], case["parameters"]) for case in dataset["cases"][1:]]
        plan = build_design_campaign([DesignCandidate(dataset["design_id"], 1, jobs[0].parameters)], scenarios,
                                     run_context=fixtures.CONTEXT, output_formulas={}, existing_jobs=jobs)
        campaign = analyze_design_campaign(plan, jobs, MAPPING)
        report = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(400))
        rows = {row.scenario: row for row in report.rows}
        self.assertEqual(sum(row.status == "target_met" for row in report.rows), 3)
        self.assertEqual(rows["Offset 60 mm"].status, "derated")
        self.assertEqual(rows["Gap 180 mm"].status, "derated")
        self.assertAlmostEqual(rows["Offset 60 mm"].maximum_load_power_w, 3222.195, delta=.1)
        self.assertAlmostEqual(rows["Gap 180 mm"].maximum_load_power_w, 2294.130, delta=.1)
        self.assertTrue(rows["Offset 60 mm"].minimum_retention_met)
        self.assertFalse(rows["Gap 180 mm"].minimum_retention_met)

    def test_reports_include_limits_evidence_and_unavailable_rows(self):
        campaign, jobs = self.fixture()
        result = analyze_operating_envelope(campaign, jobs[:1], EnvelopeLimits(400))
        with tempfile.TemporaryDirectory() as directory:
            csv_path = write_envelope_csv(Path(directory) / "envelope.csv", result)
            html_path = write_envelope_html(Path(directory) / "envelope.html", result)
            with csv_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            document = html_path.read_text(encoding="utf-8")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["status"], "unavailable")
        self.assertEqual(rows[1]["maximum_load_power_w"], "")
        self.assertEqual(rows[0]["limit_max_source_rms_v"], "400")
        self.assertTrue(rows[0]["run_signature"])
        self.assertIn("fixed_load_ohm", rows[0])
        self.assertIn("twoport_frequency_hz", rows[0])
        self.assertIn("ceiling_primary_current_rms_v", rows[0])
        self.assertIn("check_secondary_capacitor", rows[0])
        self.assertIn("No interpolation", document)
        self.assertNotIn(".mph", document)

    def test_reports_escape_text_and_protect_csv_formulas(self):
        campaign, jobs = self.fixture()
        result = analyze_operating_envelope(campaign, jobs, EnvelopeLimits(400))
        hostile = replace(result.rows[0], design="=1+1", scenario="<script>alert(1)</script>")
        result = replace(result, rows=(hostile, result.rows[1]))
        with tempfile.TemporaryDirectory() as directory:
            path = write_envelope_html(Path(directory) / "report.html", result)
            document = path.read_text(encoding="utf-8")
            path = write_envelope_csv(Path(directory) / "report.csv", result)
            with path.open(encoding="utf-8", newline="") as stream:
                row = next(csv.DictReader(stream))
        self.assertIn("&lt;script&gt;", document)
        self.assertNotIn("<script>", document)
        self.assertEqual(row["design"], "'=1+1")
        with self.assertRaises(ValueError):
            write_envelope_csv("envelope.html", result)
        with self.assertRaises(ValueError):
            write_envelope_html("envelope.csv", result)


if __name__ == "__main__":
    unittest.main()
