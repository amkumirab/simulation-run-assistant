import json
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from simulation_assistant.model_briefs import (
    BriefEntry, ModelBrief, load_model_brief, save_model_brief, validate_brief,
)


def example_brief():
    return ModelBrief('Illustrative square layout', 'draft-1', '', (
        BriefEntry('Geometry', 'RX count', '3', '1', 'proposed', 'Illustrative team proposal', ''),
        BriefEntry('Layer stack', 'TX stack, ground to air', '', '', 'unknown', '', ''),
    ))


class ModelBriefTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'brief.json'

    def test_unknown_and_empty_drafts_do_not_invent_values(self):
        validate_brief(ModelBrief('New model', 'draft', '', ()))
        self.assertEqual(example_brief().entries[1].value, '')
        validate_brief(example_brief())

    def test_round_trip_preserves_exact_values_sources_and_order(self):
        brief = replace(example_brief(), model_sha256='a'*64)
        save_model_brief(self.path, brief)
        self.assertEqual(load_model_brief(self.path), brief)
        document = json.loads(self.path.read_text())
        self.assertEqual(document['schema'], 'wpt.model-brief.v1')
        self.assertEqual(document['entries'][1]['status'], 'unknown')

    def test_non_unknown_values_require_explicit_source(self):
        entry = example_brief().entries[0]
        for bad in (replace(entry, source=''), replace(entry, value=''),
                    replace(entry, status='unknown'), replace(entry, status='approved')):
            with self.subTest(entry=bad), self.assertRaises(ValueError):
                validate_brief(replace(example_brief(), entries=(bad,)))

    def test_confirmation_requires_real_iso_date_and_source(self):
        entry = replace(example_brief().entries[0], status='confirmed', reviewed_on='2026-11-02')
        validate_brief(replace(example_brief(), entries=(entry,)))
        for date in ('', '2026-02-30', '20261102', '2026-1-2'):
            with self.subTest(date=date), self.assertRaises(ValueError):
                validate_brief(replace(example_brief(), entries=(replace(entry, reviewed_on=date),)))

    def test_units_require_finite_literal_quantities(self):
        entry = replace(example_brief().entries[0], name='Frequency', value='85', unit='kHz')
        validate_brief(replace(example_brief(), entries=(entry,)))
        for value, unit in (('NaN', 'Hz'), ('inf', 'Hz'), ('1e999', 'W'), ('f0*2', 'Hz'),
                            ('85[kHz]', 'Hz'), ('2', 'unsupported')):
            with self.subTest(value=value, unit=unit), self.assertRaises(ValueError):
                validate_brief(replace(example_brief(), entries=(replace(entry, value=value, unit=unit),)))

    def test_text_specs_do_not_need_physical_units(self):
        entry = replace(example_brief().entries[0], name='Coil shape', value='Square', unit='')
        validate_brief(replace(example_brief(), entries=(entry,)))

    def test_rejects_duplicate_names_controls_unicode_and_bad_hash(self):
        brief = example_brief()
        for bad in (replace(brief, name=''), replace(brief, revision=''),
                    replace(brief, name='a\nb'), replace(brief, name='\u0645'),
                    replace(brief, model_sha256='model.mph'),
                    replace(brief, entries=(brief.entries[0], replace(brief.entries[0], name='rx COUNT'))),
                    replace(brief, entries=tuple(replace(brief.entries[0], name=str(i)) for i in range(129)))):
            with self.subTest(brief=bad), self.assertRaises(ValueError):
                validate_brief(bad)

    def test_bad_document_shapes_types_and_versions_are_rejected(self):
        document = {'schema': 'wpt.model-brief.v1', **asdict(example_brief())}
        bad_documents = [[], {**document, 'schema': 'wpt.model-brief.v2'},
                         {**document, 'extra': True}, {**document, 'entries': {}},
                         {**document, 'entries': [{'section': 'Geometry'}]},
                         {**document, 'name': True}, {**document, 'entries': [None]}]
        for bad in bad_documents:
            with self.subTest(document=bad), self.assertRaises(ValueError):
                self.path.write_text(json.dumps(bad))
                load_model_brief(self.path)

    def test_duplicate_keys_nonstandard_numbers_and_deep_json_are_rejected(self):
        for raw in ('{"schema":"a","schema":"b"}', '{"name":NaN}', '['*1100+']'*1100,
                    '{broken', '\ufeff{}'):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                self.path.write_text(raw, encoding='utf-8')
                load_model_brief(self.path)

    def test_size_extension_and_encoding_limits(self):
        self.path.write_bytes(b' '*262145)
        with self.assertRaises(ValueError):
            load_model_brief(self.path)
        self.path.write_bytes(b'\xff')
        with self.assertRaises(ValueError):
            load_model_brief(self.path)
        with self.assertRaises(ValueError):
            save_model_brief(self.path.with_suffix('.mph'), example_brief())
        with self.assertRaises(ValueError):
            load_model_brief(self.path.with_suffix('.mph'))

    def test_failed_validation_or_replace_preserves_previous_file(self):
        save_model_brief(self.path, example_brief())
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            save_model_brief(self.path, replace(example_brief(), name=''))
        with patch('simulation_assistant.model_briefs.os.replace', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                save_model_brief(self.path, replace(example_brief(), revision='draft-2'))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ['brief.json'])


if __name__ == '__main__':
    unittest.main()
