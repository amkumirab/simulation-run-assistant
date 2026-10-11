import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, "Native checks require Tk")
class ExperimentDesktopTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("Native checks require a desktop display")
        self.addCleanup(self.root.destroy)
        self.root.withdraw()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        from simulation_assistant.desktop import DesktopApp
        self.app = DesktopApp(self.root, self.base / "jobs.db", self.base / "artifacts", self.base / "profiles.json")
        self.app._populate_parameters({"gap": "100[mm]", "N1": "10"})
        self.model = self.base / "example.mph"
        self.model.write_bytes(b"isolated identity fixture, not a COMSOL model")
        self.contract = self.base / "contract.json"
        self.contract.write_text('{"schema_version":1,"name":"test","version":"1","inputs":[{"name":"gap","unit":"mm","min":"50[mm]","max":"300[mm]"},{"name":"N1","min":"1","max":"30"}],"internal_parameters":[],"outputs":[]}', encoding="utf-8")
        self.config = SimpleNamespace(model_path=self.model, contract_path=self.contract,
                                      study_tag=None, job_tag="j1", plot_tags=())
        self.patch = patch.object(self.app, "_require_connected_config", return_value=self.config)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.app.connection_report = {"contract": {"status": "ready"}, "result_pipeline": {"status": "fresh"}}
        from simulation_assistant.experiment_ui import ExperimentDialog
        self.dialog = ExperimentDialog(self.app)
        self.dialog.inputs["gap"][0].set("Continuous")
        self.dialog.inputs["gap"][2].set("200[mm]")
        self.dialog.budget.set("6")
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)

    def test_generate_edit_invalidation_and_no_implicit_queue(self):
        self.assertIsNotNone(self.dialog.generate())
        self.assertEqual(len(self.dialog.plan.states), 6)
        self.assertEqual(self.app.store.page_jobs().total, 0)
        self.dialog.inputs["gap"][2].set("300[mm]")
        self.assertIsNone(self.dialog.saved)
        self.assertFalse(self.dialog.tree.get_children())
        self.assertFalse(self.errors)

    def test_save_load_restart_queue_and_duplicate_reuse(self):
        self.dialog.generate()
        path = self.base / "plan.json"
        with patch("simulation_assistant.experiment_ui.filedialog.asksaveasfilename", return_value=str(path)):
            self.dialog.save()
        self.dialog.window.destroy()
        from simulation_assistant.experiment_ui import ExperimentDialog
        self.dialog = ExperimentDialog(self.app)
        with patch("simulation_assistant.experiment_ui.filedialog.askopenfilename", return_value=str(path)):
            self.dialog.load()
        with patch("simulation_assistant.experiment_ui.messagebox.askyesno", return_value=True):
            self.dialog.submit(start=False)
            self.dialog.submit(start=False)
        self.assertEqual(self.app.store.page_jobs().total, 6)
        self.assertEqual(self.dialog.plan.active_count, 6)
        self.assertFalse(self.errors)

    def test_identity_freshness_and_pause_block_submission(self):
        self.dialog.generate()
        self.model.write_bytes(b"different model")
        self.dialog.submit(start=False)
        self.assertIn("changed", self.dialog.summary.get())
        self.assertEqual(self.app.store.page_jobs().total, 0)
        self.dialog.generate()
        self.app.connection_report["result_pipeline"]["status"] = "stale"
        self.dialog.submit(start=False)
        self.assertIn("Fresh", self.dialog.summary.get())
        self.app.connection_report["result_pipeline"]["status"] = "fresh"
        self.app.store.set_queue_paused(True)
        self.dialog.submit(start=True)
        self.assertIn("Resume", self.dialog.summary.get())
        self.assertEqual(self.app.store.page_jobs().total, 0)

    def test_confirmation_changes_identity_and_does_not_enqueue(self):
        self.dialog.generate()
        def confirm(*args, **kwargs):
            self.model.write_bytes(b"modified during confirmation")
            return True
        with patch("simulation_assistant.experiment_ui.messagebox.askyesno", side_effect=confirm):
            self.dialog.submit(start=False)
        self.assertEqual(self.app.store.page_jobs().total, 0)

    def test_resume_runs_only_matching_queued_ids(self):
        self.dialog.generate()
        with patch("simulation_assistant.experiment_ui.messagebox.askyesno", return_value=True):
            self.dialog.submit(start=False)
        planned_ids = [state.job_id for state in self.dialog.plan.states]
        unrelated = self.app.store.enqueue_batch("unrelated", "comsol", [{"gap": "100[mm]"}])[0]
        def finish_one(job_id):
            self.app.store.claim(job_id)
            self.app.store.mark_succeeded(job_id, {"metrics": {"fixture": 1},
                "metadata": {"scientific_validation": {"status": "valid"}}}, "")
            return SimpleNamespace(succeeded=1, failed=0, cancelled=0)
        runner = SimpleNamespace(store=self.app.store, run_job=finish_one)
        def background(_kind, operation, finished):
            finished(operation())
        with patch.object(self.app, "_runner", return_value=runner), \
                patch.object(self.app, "_run_background", side_effect=background), \
                patch("simulation_assistant.experiment_ui.messagebox.askyesno", return_value=True):
            self.dialog.submit(start=True)
        self.assertEqual(self.dialog.plan.completed_count, 6)
        self.assertEqual(self.app.store.get(unrelated).status.value, "queued")
        self.assertTrue(all(self.app.store.get(job_id).status.value == "succeeded" for job_id in planned_ids))
        self.assertFalse(self.errors)


if __name__ == "__main__":
    unittest.main()
