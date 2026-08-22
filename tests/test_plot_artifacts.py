import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from simulation_assistant.plot_artifacts import (
    format_file_size,
    matching_plot_artifacts,
    parameter_summary,
    preview_subsample_factor,
    resolve_plot_artifact,
    write_plot_comparison_report,
)
from simulation_assistant.types import Job, JobStatus


class PlotArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.plot_dir = self.root / "plots"
        self.plot_dir.mkdir()
        self.image = self.plot_dir / "pg1-field.png"
        self.image.write_bytes(b"\x89PNG\r\n\x1a\nimage")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_resolves_relocated_artifact_by_stable_filename(self) -> None:
        resolved = resolve_plot_artifact(
            self.root,
            {
                "filename": self.image.name,
                "path": "C:/old-location/plots/pg1-field.png",
            },
        )

        self.assertEqual(resolved, self.image.resolve())

    def test_resolves_relative_recorded_path_inside_job(self) -> None:
        resolved = resolve_plot_artifact(
            self.root,
            {"path": "plots/pg1-field.png"},
        )

        self.assertEqual(resolved, self.image.resolve())

    def test_rejects_paths_outside_the_job_directory(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside.png"
        outside.write_bytes(b"image")
        self.addCleanup(outside.unlink)

        with self.assertRaisesRegex(ValueError, "outside"):
            resolve_plot_artifact(self.root, {"path": str(outside)})
        with self.assertRaisesRegex(ValueError, "directory components"):
            resolve_plot_artifact(self.root, {"filename": "../outside.png"})

    def test_rejects_missing_and_non_png_artifacts(self) -> None:
        text_file = self.plot_dir / "plot.txt"
        text_file.write_text("not an image", encoding="utf-8")
        invalid_png = self.plot_dir / "invalid.png"
        invalid_png.write_text("not an image", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "missing or outside"):
            resolve_plot_artifact(self.root, {"filename": "missing.png"})
        with self.assertRaisesRegex(ValueError, "missing or outside"):
            resolve_plot_artifact(self.root, {"path": str(text_file)})
        with self.assertRaisesRegex(ValueError, "missing or outside"):
            resolve_plot_artifact(self.root, {"filename": invalid_png.name})

    def test_calculates_integer_preview_scaling(self) -> None:
        self.assertEqual(preview_subsample_factor(620, 410), 1)
        self.assertEqual(preview_subsample_factor(800, 600), 2)
        self.assertEqual(preview_subsample_factor(1900, 500), 4)
        with self.assertRaisesRegex(ValueError, "positive"):
            preview_subsample_factor(0, 100)

    def test_formats_artifact_sizes(self) -> None:
        self.assertEqual(format_file_size(900), "900 B")
        self.assertEqual(format_file_size(2048), "2.0 KB")
        self.assertEqual(format_file_size(2 * 1024 * 1024), "2.0 MB")
        self.assertEqual(format_file_size(None), "size unavailable")

    def test_finds_matching_plots_from_successful_jobs_in_the_same_batch(self) -> None:
        jobs = [
            self._job(3, batch="sweep-a", status=JobStatus.FAILED),
            self._job(1, batch="sweep-a"),
            self._job(4, batch="sweep-a"),
            self._job(2, batch="sweep-b"),
            self._job(5, batch="sweep-a", plot_tag="pg2"),
        ]

        matches = matching_plot_artifacts(
            jobs,
            batch_name="sweep-a",
            plot_tag="pg1",
        )

        self.assertEqual([item.job.id for item in matches], [1, 4])
        self.assertTrue(all(item.path.is_file() for item in matches))

    def test_comparison_keeps_the_most_recent_jobs_within_its_limit(self) -> None:
        jobs = [self._job(job_id, batch="sweep-a") for job_id in range(1, 5)]

        matches = matching_plot_artifacts(
            jobs,
            batch_name="sweep-a",
            plot_tag="pg1",
            limit=2,
        )

        self.assertEqual([item.job.id for item in matches], [3, 4])

        with_original = matching_plot_artifacts(
            jobs,
            batch_name="sweep-a",
            plot_tag="pg1",
            limit=2,
            include_job_id=1,
        )
        self.assertEqual([item.job.id for item in with_original], [1, 4])

    def test_ignores_missing_plot_artifacts_during_comparison(self) -> None:
        valid = self._job(1, batch="sweep-a")
        missing = self._job(2, batch="sweep-a", create_image=False)

        matches = matching_plot_artifacts(
            [missing, valid],
            batch_name="sweep-a",
            plot_tag="pg1",
        )

        self.assertEqual([item.job.id for item in matches], [1])

    def test_formats_a_bounded_parameter_summary(self) -> None:
        summary = parameter_summary(
            {"frequency": "85[kHz]", "gap": "15[cm]", "turns": 10},
            limit=2,
        )

        self.assertEqual(summary, "frequency=85[kHz]  ·  gap=15[cm]  ·  +1 more")
        self.assertEqual(parameter_summary({}), "No recorded parameters")

    def test_writes_a_self_contained_comparison_report(self) -> None:
        first = replace(
            self._job(1, batch="sweep-a"),
            parameters={"frequency": "81[kHz]", "note": "<check & compare>"},
        )
        second = self._job(2, batch="sweep-a")
        comparisons = matching_plot_artifacts(
            [first, second],
            batch_name="sweep-a",
            plot_tag="pg1",
        )
        destination = self.root / "comparison.html"

        written = write_plot_comparison_report(
            destination,
            comparisons,
            title="Flux <density>",
            batch_name="sweep & a",
            current_job_id=first.id,
        )
        report = written.read_text(encoding="utf-8")

        self.assertEqual(written, destination.resolve())
        self.assertIn("data:image/png;base64,", report)
        self.assertEqual(report.count("data:image/png;base64,"), 2)
        self.assertIn("Flux &lt;density&gt;", report)
        self.assertIn("&lt;check &amp; compare&gt;", report)
        self.assertIn("Current selection", report)
        self.assertNotIn(str(self.root), report)
        self.assertNotIn("<check & compare>", report)

    def test_rejects_invalid_comparison_report_targets(self) -> None:
        comparisons = matching_plot_artifacts(
            [self._job(1, batch="sweep-a"), self._job(2, batch="sweep-a")],
            batch_name="sweep-a",
            plot_tag="pg1",
        )

        with self.assertRaisesRegex(ValueError, "html extension"):
            write_plot_comparison_report(
                self.root / "comparison.txt",
                comparisons,
                title="Field",
                batch_name="sweep-a",
            )
        with self.assertRaisesRegex(ValueError, "at least two"):
            write_plot_comparison_report(
                self.root / "comparison.html",
                comparisons[:1],
                title="Field",
                batch_name="sweep-a",
            )

    def _job(
        self,
        job_id: int,
        *,
        batch: str,
        status: JobStatus = JobStatus.SUCCEEDED,
        plot_tag: str = "pg1",
        create_image: bool = True,
    ) -> Job:
        artifact_dir = self.root / f"job-{job_id}-{batch}-{plot_tag}"
        plot_dir = artifact_dir / "plots"
        plot_dir.mkdir(parents=True)
        filename = f"{plot_tag}-field.png"
        if create_image:
            (plot_dir / filename).write_bytes(b"\x89PNG\r\n\x1a\nimage")
        return Job(
            id=job_id,
            batch_name=batch,
            adapter="comsol",
            status=status,
            parameters={"frequency": f"{80 + job_id}[kHz]"},
            output_formulas={},
            result={
                "metrics": {},
                "metadata": {
                    "plot_exports": [
                        {
                            "tag": plot_tag,
                            "label": "Magnetic Flux Density",
                            "dimension": "2D",
                            "filename": filename,
                        }
                    ]
                },
            },
            error=None,
            artifact_dir=str(artifact_dir),
            attempts=1,
            created_at=f"2026-08-{job_id:02d}T00:00:00+00:00",
            started_at=None,
            finished_at=None,
        )


if __name__ == "__main__":
    unittest.main()
