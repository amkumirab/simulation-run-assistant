import unittest

from simulation_assistant.result_pipeline import inspect_result_pipeline


def complete_model(*, job_steps: list[dict] | None = None) -> dict:
    return {
        "datasets": [
            {
                "tag": "dset1",
                "label": "Solution 1",
                "type": "Solution",
                "study_tag": "std1",
            }
        ],
        "numerical_features": [
            {
                "tag": "gev1",
                "label": "WPT metrics",
                "type": "EvalGlobal",
                "dataset_tag": "dset1",
                "table_tag": "tbl1",
                "expressions": ["P_in", "P_out"],
                "units": ["W", "W"],
            }
        ],
        "tables": [
            {
                "tag": "tbl1",
                "label": "Metrics",
                "status": "built",
                "columns": ["Input power (W)", "Output power (W)"],
                "has_data": True,
            }
        ],
        "jobs": [
            {
                "tag": "job1",
                "label": "Fresh result job",
                "steps": job_steps or [],
            }
        ],
    }


class ResultPipelineTests(unittest.TestCase):
    def test_study_pipeline_is_linked_but_saved_tables_are_stale(self) -> None:
        report = inspect_result_pipeline(
            complete_model(),
            selected_study="std1",
            selected_job=None,
        )

        self.assertEqual(report.status, "stale")
        self.assertEqual(report.chains[0].state, "linked")
        self.assertEqual(report.chains[0].study_tag, "std1")
        self.assertIn(
            "study_does_not_refresh_tables",
            {finding.code for finding in report.findings},
        )

    def test_job_with_solve_and_evaluation_steps_is_fresh(self) -> None:
        model = complete_model(
            job_steps=[
                {"tag": "solve1", "category": "solve", "label": "Study"},
                {
                    "tag": "eval1",
                    "category": "evaluation",
                    "label": "Evaluate Derived Values",
                },
                {"tag": "save1", "category": "save", "label": "Save Model"},
            ]
        )
        report = inspect_result_pipeline(
            model,
            selected_study=None,
            selected_job="job1",
        )

        self.assertEqual(report.status, "fresh")
        self.assertIn(
            "fresh_pipeline_verified",
            {finding.code for finding in report.findings},
        )

    def test_job_without_evaluation_step_is_incomplete(self) -> None:
        model = complete_model(
            job_steps=[{"tag": "solve1", "category": "solve", "label": "Study"}]
        )
        report = inspect_result_pipeline(
            model,
            selected_study=None,
            selected_job="job1",
        )

        self.assertEqual(report.status, "incomplete")
        finding = next(
            item for item in report.findings if item.code == "job_missing_evaluation"
        )
        self.assertIn("Evaluate Derived Values", finding.action)

    def test_job_must_solve_before_evaluating_results(self) -> None:
        model = complete_model(
            job_steps=[
                {"tag": "eval1", "category": "evaluation"},
                {"tag": "solve1", "category": "solve"},
            ]
        )
        report = inspect_result_pipeline(
            model,
            selected_study=None,
            selected_job="job1",
        )

        self.assertEqual(report.status, "incomplete")
        self.assertIn(
            "job_step_order_invalid",
            {finding.code for finding in report.findings},
        )

    def test_missing_links_and_orphan_snapshot_are_reported(self) -> None:
        model = complete_model()
        model["numerical_features"][0].pop("dataset_tag")
        model["numerical_features"][0].pop("table_tag")
        report = inspect_result_pipeline(
            model,
            selected_study="std1",
            selected_job=None,
        )

        self.assertEqual(report.status, "incomplete")
        self.assertEqual(report.orphan_tables, ("tbl1",))
        codes = {finding.code for finding in report.findings}
        self.assertIn("incomplete_result_chain", codes)
        self.assertIn("orphan_saved_tables", codes)

    def test_dataset_from_another_study_is_rejected(self) -> None:
        model = complete_model()
        model["datasets"][0]["study_tag"] = "std2"
        report = inspect_result_pipeline(
            model,
            selected_study="std1",
            selected_job=None,
        )

        self.assertEqual(report.status, "incomplete")
        self.assertIn(
            "study_dataset_mismatch",
            {finding.code for finding in report.findings},
        )


if __name__ == "__main__":
    unittest.main()
