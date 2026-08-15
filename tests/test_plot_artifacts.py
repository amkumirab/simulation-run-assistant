import tempfile
import unittest
from pathlib import Path

from simulation_assistant.plot_artifacts import (
    format_file_size,
    preview_subsample_factor,
    resolve_plot_artifact,
)


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


if __name__ == "__main__":
    unittest.main()
