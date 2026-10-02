import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from simulation_assistant.design_campaigns import (
    DesignCandidate, Scenario, analyze_design_campaign, build_design_campaign,
    designs_from_jobs, require_campaign_identity,
)
from simulation_assistant.design_campaign_reports import (
    load_design_campaign, save_design_campaign,
    write_design_campaign_csv, write_design_campaign_html,
)
from simulation_assistant.preflight import build_run_signature
from simulation_assistant.storage import JobStore
from simulation_assistant.types import Job, JobStatus
from simulation_assistant.wpt_circuit import CircuitLimits, TwoPortMetricMap


CONTEXT = {"model": {"name": "wpt.mph", "size_bytes": 100}, "target": {"tag": "b1"}}
MAPPING = TwoPortMetricMap(
    "frequency_Hz", "L1_H", "L2_H", "M12_H", "M21_H",
    "R1_ohm", "R2_ohm", "R12_ohm", "R21_ohm",
)


def metrics(inductance=100e-6):
    return dict(frequency_Hz=85000, L1_H=inductance, L2_H=inductance,
                M12_H=20e-6, M21_H=20e-6, R1_ohm=.2, R2_ohm=.2,
                R12_ohm=0, R21_ohm=0)


def design(name="A", radius="100[mm]", source_id=1):
    return DesignCandidate(name, source_id, dict(radius=radius, gap="150[mm]",
                                               xoff="0[mm]", yoff="0[mm]", tilt="0[deg]"))


def job(job_id, parameters, *, state=JobStatus.SUCCEEDED, validation="valid", values=None):
    return Job(job_id, "test", "comsol", state, parameters, {},
               {"metrics": values or metrics(),
                "metadata": {"scientific_validation": {"status": validation}}},
               None, None, 1, "2026-10-01", None, None,
               build_run_signature("comsol", parameters, {}, CONTEXT), CONTEXT)


class DesignCampaignTests(unittest.TestCase):
    def plan(self, designs=None, scenarios=None, jobs=()):
        return build_design_campaign(
            designs or [design()], scenarios or [Scenario("Nominal", {}),
                                                  Scenario("Offset", {"xoff": "30[mm]"})],
            run_context=CONTEXT, output_formulas={}, existing_jobs=jobs,
        )

    def test_two_designs_expand_without_overwriting_geometry(self):
        plan = self.plan([design(), design("B", "110[mm]", 2)])
        self.assertEqual(len(plan.campaign.states), 4)
        self.assertEqual([p.parameters["radius"] for p in plan.campaign.states],
                         ["100[mm]", "100[mm]", "110[mm]", "110[mm]"])
        self.assertEqual(len(plan.campaign.pending), 4)

    def test_reuses_accepted_not_failed_and_does_not_duplicate_active_jobs(self):
        initial = self.plan()
        nominal, offset = [state.parameters for state in initial.campaign.states]
        plan = self.plan(jobs=[job(1, nominal), job(2, nominal, state=JobStatus.FAILED),
                               job(3, offset, state=JobStatus.QUEUED)])
        self.assertEqual(plan.campaign.completed_count, 1)
        self.assertEqual(plan.campaign.active_count, 1)
        self.assertEqual(len(plan.campaign.pending), 0)
        self.assertEqual(plan.campaign.states[0].job_id, 1)

    def test_rejected_and_unvalidated_are_retryable(self):
        states = self.plan().campaign.states
        plan = self.plan(jobs=[job(1, states[0].parameters, validation="rejected"),
                               job(2, states[1].parameters, validation="")])
        self.assertEqual(len(plan.campaign.pending), 2)

    def test_different_model_is_not_reused_or_allowed_to_execute(self):
        wrong = replace(job(1, design().parameters), run_signature="different")
        plan = self.plan(jobs=[wrong])
        self.assertEqual(plan.campaign.completed_count, 0)
        require_campaign_identity(plan, CONTEXT, {})
        with self.assertRaisesRegex(ValueError, "identity"):
            require_campaign_identity(plan, {"model": {"name": "other.mph"}}, {})
        with self.assertRaisesRegex(ValueError, "identity"):
            require_campaign_identity(plan, CONTEXT, {"power": "2"})

    def test_rejects_ambiguous_duplicate_scenarios_and_designs(self):
        for scenarios in (
            [Scenario("Nominal", {}), Scenario("Same", {"gap": "15[cm]"})],
            [Scenario("Nominal", {}), Scenario("nominal", {"xoff": "30[mm]"})],
            [Scenario("Nominal", {}), Scenario("Geometry", {"radius": "12[cm]"})],
        ):
            with self.assertRaises(ValueError):
                self.plan(scenarios=scenarios)
        with self.assertRaisesRegex(ValueError, "same geometry"):
            self.plan([design(), design("B", "10[cm]", 2)])

    def test_rejects_bad_units_and_more_than_500_pairs(self):
        for value in ("nan[mm]", "30[deg]", "4", "1e309[mm]", "gap+1[mm]"):
            with self.assertRaises(ValueError):
                self.plan(scenarios=[Scenario("Nominal", {}), Scenario("Bad", {"xoff": value})])
        with self.assertRaisesRegex(ValueError, "500"):
            self.plan([design(str(i), f"{i+1}[mm]", i+1) for i in range(501)])

    def test_negative_zero_offset_is_not_a_distinct_scenario(self):
        with self.assertRaisesRegex(ValueError, "Equivalent"):
            self.plan(scenarios=[Scenario("Nominal", {}), Scenario("Duplicate zero", {"xoff": "-0[mm]"})])

    def test_source_selection_requires_accepted_consistent_nominal_jobs(self):
        with self.assertRaisesRegex(ValueError, "accepted"):
            designs_from_jobs([job(1, design().parameters, validation="rejected")])
        with self.assertRaisesRegex(ValueError, "identity"):
            designs_from_jobs([job(1, design().parameters),
                               replace(job(2, design("B", "110[mm]").parameters), run_context={})])

    def test_each_design_uses_its_own_nominal_controls(self):
        initial = self.plan([design(), design("B", "110[mm]", 3)])
        jobs = [job(i+1, state.parameters, values=metrics(100e-6 if i < 2 else 200e-6))
                for i, state in enumerate(initial.campaign.states)]
        report = analyze_design_campaign(self.plan(list(initial.designs), jobs=jobs), jobs, MAPPING,
                                         limits=CircuitLimits(max_capacitor_voltage_rms_v=5000))
        self.assertEqual([r.status for r in report.designs], ["passed", "passed"])
        self.assertNotEqual(report.designs[0].study.controls.primary_capacitance_f,
                            report.designs[1].study.controls.primary_capacitance_f)
        self.assertEqual([r.study.nominal_job_id for r in report.designs], [1, 3])

    def test_missing_scenario_never_counts_as_passed(self):
        nominal = job(1, design().parameters)
        report = analyze_design_campaign(self.plan(jobs=[nominal]), [nominal], MAPPING)
        self.assertEqual(report.designs[0].status, "incomplete")
        self.assertEqual(report.designs[0].accepted_count, 1)
        self.assertEqual(report.designs[0].required_count, 2)

    def test_invalid_two_port_marks_only_its_design_ineligible(self):
        initial = self.plan([design(), design("B", "110[mm]", 3)])
        jobs = [job(i+1, state.parameters, values=metrics(-1 if i >= 2 else 100e-6))
                for i, state in enumerate(initial.campaign.states)]
        report = analyze_design_campaign(self.plan(list(initial.designs), jobs=jobs), jobs, MAPPING)
        self.assertEqual([r.status for r in report.designs], ["passed", "ineligible"])

    def test_saved_configuration_round_trip_and_escaped_reports(self):
        plan = self.plan([design("<Design>")])
        report = analyze_design_campaign(plan, [], MAPPING)
        with tempfile.TemporaryDirectory() as directory:
            path = save_design_campaign(Path(directory)/"campaign.json", plan, MAPPING)
            loaded, mapping, settings, limits = load_design_campaign(path, [])
            self.assertEqual(loaded.designs, plan.designs)
            self.assertEqual(mapping, MAPPING)
            html = write_design_campaign_html(Path(directory)/"report.html", report).read_text()
            csv_path = write_design_campaign_csv(Path(directory)/"report.csv", report)
            with csv_path.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertIn("&lt;Design&gt;", html)
            self.assertNotIn("wpt.mph", html)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["design_status"], "incomplete")
            path.write_text('{"schema": "unknown"}')
            with self.assertRaises(ValueError):
                load_design_campaign(path, [])

    def test_real_stored_wpt_cases_keep_three_passes_and_two_failures(self):
        dataset = json.loads((Path(__file__).parents[1]/"examples/wpt_circuit_results.json").read_text())
        nominal = next(case for case in dataset["cases"] if case["name"] == dataset["nominal_case"])
        base = DesignCandidate(dataset["design_id"], 1, nominal["parameters"])
        cases = [nominal] + [case for case in dataset["cases"] if case != nominal]
        scenarios = [Scenario("Nominal", {})] + [Scenario(c["name"], c["parameters"]) for c in cases[1:]]
        jobs = [job(i+1, case["parameters"], values=case["metrics"]) for i, case in enumerate(cases)]
        plan = build_design_campaign([base], scenarios, output_formulas={}, run_context=CONTEXT, existing_jobs=jobs)
        result = analyze_design_campaign(plan, jobs, MAPPING).designs[0]
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.study.passed_count, 3)
        self.assertEqual(result.study.failed_count, 2)

    def test_restart_reads_existing_queue_and_resubmits_only_failed_states(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"jobs.db"
            store = JobStore(path)
            store.initialize()
            initial = self.plan()
            ids = store.enqueue_batch("campaign", "comsol",
                                       [s.parameters for s in initial.campaign.states], run_context=CONTEXT)
            store.claim(ids[0])
            store.mark_succeeded(ids[0], job(1, design().parameters).result, "")
            store.claim(ids[1])
            store.mark_failed(ids[1], "Interrupted solver")
            restarted = JobStore(path)
            restarted.initialize()
            plan = self.plan(jobs=restarted.list())
            self.assertEqual(plan.campaign.completed_count, 1)
            self.assertEqual(len(plan.campaign.pending), 1)
            retry_id = restarted.enqueue_batch("resume", "comsol",
                      [c.parameters for c in plan.campaign.candidates_to_enqueue()], run_context=CONTEXT)[0]
            resumed = self.plan(jobs=restarted.list())
            self.assertEqual(resumed.campaign.active_count, 1)
            self.assertFalse(resumed.campaign.pending)
            self.assertEqual(resumed.campaign.states[1].job_id, retry_id)

    def test_report_contains_independent_controls_checks_and_safe_csv_labels(self):
        initial = self.plan([design("=untrusted()")])
        jobs = [job(i+1, state.parameters) for i, state in enumerate(initial.campaign.states)]
        report = analyze_design_campaign(self.plan(list(initial.designs), jobs=jobs), jobs, MAPPING)
        with tempfile.TemporaryDirectory() as directory:
            path = write_design_campaign_csv(Path(directory)/"report.csv", report)
            with path.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            html = write_design_campaign_html(Path(directory)/"report.html", report).read_text()
        self.assertEqual(rows[0]["design"], "'=untrusted()")
        self.assertEqual(rows[0]["check_coil_current"], "True")
        self.assertEqual(float(rows[0]["twoport_frequency"]), 85000)
        self.assertGreater(float(rows[0]["fixed_primary_capacitance_f"]), 0)
        self.assertIn("run_signature", html)
        self.assertIn("check_coil_current", html)
        self.assertIn("input_radius", html)

    def test_malformed_configuration_cannot_crash_or_supply_nested_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = save_design_campaign(Path(directory)/"campaign.json", self.plan(), MAPPING)
            original = json.loads(path.read_text())
            for bad in (None, [], {"schema": "wpt.design-campaign.v1"}):
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    load_design_campaign(path, [])
            original["designs"][0]["parameters"]["radius"] = {"invalid": "value"}
            path.write_text(json.dumps(original))
            with self.assertRaises(ValueError):
                load_design_campaign(path, [])

    def test_missing_nominal_does_not_use_a_scenario_as_nominal(self):
        offset = job(2, self.plan().campaign.states[1].parameters)
        report = analyze_design_campaign(self.plan(jobs=[offset]), [offset], MAPPING)
        self.assertEqual(report.designs[0].status, "incomplete")
        self.assertIsNone(report.designs[0].study)
        self.assertIn("nominal", report.designs[0].message)

    def test_changed_frequency_and_nonpositive_gap_are_ineligible(self):
        states = self.plan().campaign.states
        values = metrics()
        values["frequency_Hz"] = 90000
        jobs = [job(1, states[0].parameters), job(2, states[1].parameters, values=values)]
        report = analyze_design_campaign(self.plan(jobs=jobs), jobs, MAPPING)
        self.assertEqual(report.designs[0].status, "ineligible")
        with self.assertRaises(ValueError):
            self.plan(scenarios=[Scenario("Nominal", {}), Scenario("Bad", {"gap": "0[mm]"})])


if __name__ == "__main__":
    unittest.main()
