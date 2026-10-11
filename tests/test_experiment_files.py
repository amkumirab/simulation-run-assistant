import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from simulation_assistant.experiments import ExperimentSpec, InputRange, generate_experiments, build_experiment_campaign
from simulation_assistant.experiment_files import save_experiment, load_experiment, write_experiment_csv, require_experiment_identity
from simulation_assistant.storage import JobStore


class ExperimentFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.design = generate_experiments(ExperimentSpec((InputRange("N1", "2", "4", "integer"),), {"gap": "15[cm]"}, 3))
        self.context = {"model": {"name": "example.mph", "path_sha256": "abc"}, "target": {"kind": "job", "tag": "j1"}}
        self.store = JobStore(self.base / "jobs.db")
        self.store.initialize()

    def test_round_trip_retains_points_and_identity(self):
        path = save_experiment(self.base / "plan.json", self.design, self.context, {"score": "N1"})
        loaded = load_experiment(path)
        self.assertEqual(loaded.design, self.design)
        self.assertEqual(loaded.run_context, self.context)
        self.assertEqual(loaded.output_formulas, {"score": "N1"})
        require_experiment_identity(loaded, self.context, {"score": "N1"})
        with self.assertRaises(ValueError):
            require_experiment_identity(loaded, {"model": {}}, {"score": "N1"})
        with self.assertRaises(ValueError):
            require_experiment_identity(loaded, self.context, {})

    def test_malformed_tampered_and_oversized_documents(self):
        path = save_experiment(self.base / "plan.json", self.design, self.context, {})
        original = json.loads(path.read_text())
        for changed in [None, [], {**original, "schema": "other"}, {**original, "points": []},
                        {**original, "seed": True}, {**original, "output_formulas": {"x": "os.system('x')"}},
                        {**original, "points": [{"N1": "999", "gap": "15[cm]"}]}]:
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.subTest(document=changed), self.assertRaises(ValueError):
                load_experiment(path)
        path.write_text(" " * 1_000_001)
        with self.assertRaises(ValueError):
            load_experiment(path)

    def test_campaign_reuses_accepted_and_active_then_retries(self):
        ids = self.store.enqueue_batch("earlier", "comsol", self.design.points, run_context=self.context)
        self.store.claim(ids[0])
        self.store.mark_succeeded(ids[0], {"metrics": {"k": .5}, "metadata": {"scientific_validation": {"status": "valid"}}}, "")
        self.store.claim(ids[1])
        self.store.mark_failed(ids[1], "solver failed")
        plan = build_experiment_campaign(self.design, run_context=self.context, output_formulas={},
                                         existing_jobs=self.store.iter_jobs())
        self.assertEqual([p.status for p in plan.states], ["valid", "failed", "queued"])
        self.assertEqual(len(plan.pending), 1)
        changed = build_experiment_campaign(self.design, run_context={"different": True}, output_formulas={},
                                            existing_jobs=self.store.iter_jobs())
        self.assertEqual(len(changed.pending), 3)
        output = write_experiment_csv(self.base / "results.csv", plan)
        with output.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["run_signature"], plan.states[0].signature)
        self.assertEqual(rows[0]["output_k"], "0.5")

    def test_current_payload_must_match_the_recorded_signature(self):
        job_id = self.store.enqueue_batch("prior", "comsol", [self.design.points[0]], run_context=self.context)[0]
        damaged = replace(self.store.get(job_id), parameters={"gap": "wrong"})
        plan = build_experiment_campaign(self.design, run_context=self.context, output_formulas={}, existing_jobs=[damaged])
        self.assertEqual(plan.states[0].status, "missing")

    def test_missing_identity_cannot_be_saved(self):
        with self.assertRaises(ValueError):
            save_experiment(self.base / "missing.json", self.design, {}, {})

    def test_stored_origin_survives_round_trip_and_export(self):
        context = {"origin": "Stored COMSOL replay; no new solve"}
        path = save_experiment(self.base / "stored.json", self.design, context, {}, method="stored-points-v1")
        saved = load_experiment(path)
        self.assertEqual(saved.method, "stored-points-v1")
        plan = build_experiment_campaign(saved.design, run_context=context, output_formulas={}, existing_jobs=[])
        output = write_experiment_csv(self.base / "stored.csv", plan)
        with output.open(newline="") as handle:
            self.assertEqual(next(csv.DictReader(handle))["plan_origin"], context["origin"])


if __name__ == "__main__":
    unittest.main()
