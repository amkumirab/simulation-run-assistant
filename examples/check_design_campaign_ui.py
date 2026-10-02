"""Exercise the native campaign workflow in an isolated database, without COMSOL."""
from __future__ import annotations

import json
import tempfile
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from simulation_assistant.design_campaign_ui import DesignCampaignDialog
from simulation_assistant.desktop import DesktopApp
from simulation_assistant.preflight import build_comsol_run_context
from simulation_assistant.types import JobStatus


def main():
    with tempfile.TemporaryDirectory(prefix="design-ui-check-") as directory:
        folder = Path(directory)
        model = folder / "fixture.mph"
        model.write_bytes(b"Test fixture, not a COMSOL model")
        contract = folder / "contract.json"
        contract.write_text(json.dumps({
            "schema_version": 1, "name": "fixture", "version": "1.0.0",
            "target": {"kind": "job", "tag": "batch1"},
            "inputs": [{"name": name, "unit": unit} for name, unit in
                       (("radius", "mm"), ("gap", "mm"), ("xoff", "mm"), ("yoff", "mm"), ("tilt", "deg"))],
            "outputs": [{"name": "L1_H", "table_tag": "t1", "column": "L1", "unit": "H"}],
        }))
        config = SimpleNamespace(model_path=model, contract_path=contract, study_tag=None,
                                 job_tag="batch1", plot_tags=[])
        context = build_comsol_run_context(model, study_tag=None, job_tag="batch1", contract_path=contract)
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *error: errors.append(error)
        app = DesktopApp(root, folder / "jobs.db", folder / "artifacts", folder / "profiles.json")
        empty = DesignCampaignDialog(app)
        assert empty.preview() is None and "Select at least" in empty.summary.get()
        empty.window.destroy()
        parameters = dict(radius="100[mm]", gap="150[mm]", xoff="0[mm]", yoff="0[mm]", tilt="0[deg]")
        nominal_id = app.store.enqueue_batch("Test design", "comsol", [parameters], run_context=context)[0]
        app.store.claim(nominal_id)
        app.store.mark_succeeded(nominal_id, {"metrics": {
            "frequency_Hz": 85000, "L1_H": .0001, "L2_H": .0001, "M12_H": .00002,
            "M21_H": .00002, "R1_ohm": .2, "R2_ohm": .2, "R12_ohm": 0, "R21_ohm": 0,
        }, "metadata": {"scientific_validation": {"status": "valid"}}}, "")
        dialog = DesignCampaignDialog(app)
        dialog.design_tree.selection_set(str(nominal_id))
        root.update()
        assert len(dialog.preview().campaign.pending) == 4
        assert dialog.report.designs[0].status == "incomplete"
        dialog.scenario_vars["name"].set("Extra y offset")
        dialog.scenario_vars["yoff"].set("20[mm]")
        dialog.edit_scenario("add")
        assert len(dialog.preview().campaign.states) == 6
        dialog.scenario_tree.selection_set("5")
        dialog.edit_scenario("remove")
        assert len(dialog.preview().campaign.states) == 5
        campaign_path = folder / "campaign.json"
        with patch("simulation_assistant.design_campaign_ui.filedialog.asksaveasfilename", return_value=str(campaign_path)):
            dialog.save()
        assert campaign_path.exists()
        dialog.window.destroy()
        dialog = DesignCampaignDialog(app)
        with patch("simulation_assistant.design_campaign_ui.filedialog.askopenfilename", return_value=str(campaign_path)):
            dialog.load()
        assert dialog.plan.campaign.completed_count == 1
        assert len(dialog.plan.campaign.pending) == 4
        # Only the external connection and confirmation boundaries are substituted.
        # The plan, contract validation, database queue and sequential iteration are real.
        app._require_connected_config = lambda: config
        app._collect_formulas = lambda: {}
        app.connection_report = {"contract": {"status": "ready"}, "result_pipeline": {"status": "stale"}}
        dialog.submit(start=False)
        assert "Fresh" in dialog.identity_note.get()
        assert len(app.store.list()) == 1
        app.connection_report = {"contract": {"status": "ready"}, "result_pipeline": {"status": "fresh"}}
        app._collect_formulas = lambda: {"different": "1"}
        dialog.submit(start=False)
        assert "identity" in dialog.identity_note.get()
        assert len(app.store.list()) == 1
        app._collect_formulas = lambda: {}
        with patch("simulation_assistant.design_campaign_ui.messagebox.askyesno", return_value=True):
            dialog.submit(start=False)
            dialog.submit(start=False)
        assert len(app.store.list()) == 5
        assert dialog.plan.campaign.active_count == 4
        app.store.set_queue_paused(True)
        dialog.submit(start=True)
        assert "Resume the run queue" in dialog.identity_note.get()
        app.store.set_queue_paused(False)
        processed = []
        class LocalRunner:
            store = app.store
            def run_job(self, job_id):
                processed.append(job_id)
                self.store.claim(job_id)
                self.store.mark_failed(job_id, "Deliberate local-runner failure")
                if len(processed) == 2:
                    self.store.set_queue_paused(True)
                return SimpleNamespace(succeeded=0, failed=1, cancelled=0)
        app._runner = lambda _config: LocalRunner()
        app._run_background = lambda _label, work, finished: finished(work())
        with patch("simulation_assistant.design_campaign_ui.messagebox.askyesno", return_value=True):
            dialog.submit(start=True)
        assert len(processed) == 2
        assert len(app.store.list(status=JobStatus.QUEUED)) == 2
        assert len(dialog.plan.campaign.pending) == 2
        assert not errors, errors
        # Verify widgets are laid out at the minimum supported desktop size.
        root.deiconify()
        dialog.window.geometry("920x680")
        for index in range(3):
            dialog.tabs.select(index)
            root.update()
            assert dialog.tabs.winfo_height() > 300
        dialog.window.destroy()
        root.destroy()
    print("Native UI checks passed: empty state, scenario editing, save/load, identity/Fresh gates,")
    print("queue deduplication, paused execution, sequential interruption, and minimum-size layout.")


if __name__ == "__main__":
    main()
