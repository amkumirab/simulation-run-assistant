import tempfile
import unittest
from pathlib import Path

from simulation_assistant.field_sample_files import (
    load_field_csv, load_field_workspace, parse_field_csv, parse_field_workspace,
    save_field_workspace,
)

ROOT = Path(__file__).resolve().parents[1]


class FieldByteParserTests(unittest.TestCase):
    def test_existing_real_bytes_and_path_loaders_agree_exactly(self):
        folder = ROOT/'examples/saved_field_wpt'
        data, sensors = load_field_workspace(folder/'workspace.json')
        self.assertEqual(parse_field_workspace((folder/'workspace.json').read_bytes()), (data, sensors))
        self.assertEqual(parse_field_csv((folder/'fields.csv').read_bytes(), data.metadata), data)
        self.assertEqual(load_field_csv(folder/'fields.csv', data.metadata), data)
        with tempfile.TemporaryDirectory() as directory:
            path = save_field_workspace(Path(directory)/'workspace.json', data, sensors)
            self.assertEqual(parse_field_workspace(path.read_bytes()), (data, sensors))

    def test_byte_parsers_reject_wrong_types_and_oversize_before_decoding(self):
        data, _ = load_field_workspace(ROOT/'examples/saved_field_wpt/workspace.json')
        for raw in (None, '{}', b' '*8_000_001, b'\xff', b'{}'):
            with self.subTest(raw_type=type(raw)), self.assertRaises(ValueError):
                parse_field_workspace(raw)
        for raw in (None, 'csv', b' '*5_000_001, b'\xff', b'not,the,schema'):
            with self.subTest(raw_type=type(raw)), self.assertRaises(ValueError):
                parse_field_csv(raw, data.metadata)


if __name__ == '__main__':
    unittest.main()
