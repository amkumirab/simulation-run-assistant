import ast
import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from simulation_assistant import __version__
from simulation_assistant.comsol_field_sampling import SavedState

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT/'docs/COMSOL_FIELD_SAMPLING.md'


class SavedFieldDocumentationTests(unittest.TestCase):
    def test_saved_state_example_matches_the_current_constructor(self):
        text = GUIDE.read_text(encoding='utf-8')
        expression = re.search(r'`(SavedState\([^`]+\))`', text).group(1)
        call = ast.parse(expression, mode='eval').body
        state = SavedState(*(ast.literal_eval(argument) for argument in call.args))
        self.assertEqual(state.frequency_hz, 85000.)
        self.assertEqual(state.inner, 2)
        self.assertIn('freq=85000', state.parameters)

    def test_readme_exposes_the_license_free_replay_and_sampling_guide(self):
        text = (ROOT/'README.md').read_text(encoding='utf-8')
        self.assertIn('examples/replay_saved_comsol_fields.py --desktop', text)
        self.assertIn('examples/saved_field_wpt/README.md', text)
        self.assertIn('docs/COMSOL_FIELD_SAMPLING.md', text)
        guide = GUIDE.read_text(encoding='utf-8')
        self.assertIn('examples/replay_saved_comsol_fields.py --headless', guide)

    def test_local_guide_links_and_images_exist(self):
        documents = (ROOT/'README.md', GUIDE, ROOT/'docs/FIELD_SAMPLES.md',
                     ROOT/'examples/saved_field_wpt/README.md')
        for document in documents:
            text = document.read_text(encoding='utf-8')
            for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', text):
                link = urlsplit(target)
                if link.scheme or not link.path:
                    continue
                with self.subTest(document=document.name, target=target):
                    self.assertTrue((document.parent/unquote(link.path)).is_file())

    def test_project_package_and_changelog_versions_agree(self):
        project = (ROOT/'pyproject.toml').read_text(encoding='utf-8').split('[project]', 1)[1].split('\n[', 1)[0]
        version = re.search(r'^version\s*=\s*"([^"]+)"', project, re.MULTILINE).group(1)
        changelog = (ROOT/'CHANGELOG.md').read_text(encoding='utf-8')
        latest = re.search(r'^## \[([^\]]+)\] - (.+)$', changelog, re.MULTILINE)
        self.assertEqual(version, __version__)
        self.assertEqual(latest.group(1), version)
        self.assertRegex(latest.group(2), r'^(Unreleased|\d{4}-\d{2}-\d{2})$')


if __name__ == '__main__':
    unittest.main()
