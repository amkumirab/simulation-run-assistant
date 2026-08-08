import json
import tempfile
import unittest
from pathlib import Path

from simulation_assistant.profiles import (
    ProfileStore,
    WorkspaceProfile,
    missing_local_paths,
    sanitized_profile_template,
    write_sanitized_profile_template,
)


def make_profile(name: str = "Wireless charger") -> WorkspaceProfile:
    return WorkspaceProfile.create(
        name=name,
        executable_path="C:/Program Files/COMSOL/comsolbatch.exe",
        model_path="C:/private/models/charger.mph",
        target_mode="job",
        job_tag="job1",
        timeout_seconds=7200,
        cores=4,
        batch_name="charger-frequency-sweep",
        parameters={"f0": "70:100:10[kHz]", "gap": "15[cm]"},
        parameter_modes={"f0": "Sweep", "gap": "Fixed"},
        output_formulas={"time_ratio": "duration / total"},
    )


class ProfileTests(unittest.TestCase):
    def test_saves_lists_and_restores_the_last_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProfileStore(Path(temp_dir) / "profiles.json")
            store.save(make_profile("First"))
            store.save(make_profile("Second"))

            self.assertEqual([profile.name for profile in store.list()], ["Second", "First"])
            self.assertEqual(store.last().name, "Second")
            self.assertEqual(store.get("second").job_tag, "job1")
            store.set_last("First")
            self.assertEqual([profile.name for profile in store.list()], ["First", "Second"])

    def test_updates_profiles_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProfileStore(Path(temp_dir) / "profiles.json")
            store.save(make_profile("Charger"))
            updated = WorkspaceProfile.create(
                **{**make_profile("charger").to_dict(), "cores": 8}
            )
            store.save(updated)

            self.assertEqual(len(store.list()), 1)
            self.assertEqual(store.get("CHARGER").cores, 8)

    def test_duplicates_and_deletes_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProfileStore(Path(temp_dir) / "profiles.json")
            store.save(make_profile("Original"))
            duplicate = store.duplicate("Original", "Variant")
            self.assertEqual(duplicate.name, "Variant")
            self.assertEqual(duplicate.parameters, make_profile().parameters)
            store.delete("original")
            self.assertEqual([profile.name for profile in store.list()], ["Variant"])

    def test_rejects_invalid_sweep_values_and_corrupt_storage(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two"):
            WorkspaceProfile.create(
                **{
                    **make_profile().to_dict(),
                    "parameters": {"f0": "85[kHz]"},
                    "parameter_modes": {"f0": "Sweep"},
                }
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "profiles.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Could not read"):
                ProfileStore(path).list()

    def test_sanitized_export_never_contains_local_paths(self) -> None:
        profile = make_profile()
        template = sanitized_profile_template(profile)
        serialized = json.dumps(template)
        self.assertNotIn(profile.executable_path, serialized)
        self.assertNotIn(profile.model_path, serialized)
        self.assertTrue(template["local_paths_excluded"])
        self.assertEqual(template["parameters"]["f0"]["mode"], "Sweep")

        with tempfile.TemporaryDirectory() as temp_dir:
            output = write_sanitized_profile_template(
                Path(temp_dir) / "template.json",
                profile,
            )
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), template)

    def test_reports_missing_local_files(self) -> None:
        missing = missing_local_paths(make_profile())
        self.assertEqual([label for label, _path in missing], ["COMSOL executable", "MPH model"])


if __name__ == "__main__":
    unittest.main()
