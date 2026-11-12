"""Immutable, consistency-checked saved-field inputs; hashes are not signatures."""
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from simulation_assistant.comsol_field_sampling import FieldSelection, SavedState, _field_csv, validate_selection
from simulation_assistant.field_sample_files import parse_field_csv, parse_field_workspace, _object
from simulation_assistant.field_samples import FieldDataset, FieldMetadata, Sensor, validate_layout, validate_metadata

SINGLE = 'wpt.saved-field-evidence.v1'
CAMPAIGN = 'wpt.saved-field-campaign.v1'
SINGLE_KEYS = {'schema', 'model_sha256', 'states', 'expressions', 'source_csv_sha256', 'metadata',
               'method', 'extrapolation', 'phase_rotation_deg', 'new_solve', 'sensor_response', 'sensors'}
CAMPAIGN_KEYS = {'schema', 'source_csv_sha256', 'metadata', 'sources', 'compatibility', 'new_solve', 'sensor_response'}
SHARED = ('coordinate_frame', 'coordinate_unit', 'field_unit', 'frequency_hz', 'phasor_convention',
          'excitation', 'phase_reference', 'source_kind')


@dataclass(frozen=True)
class FieldSource:
    scenario: str
    model_sha256: str
    state: SavedState
    expressions: tuple[str, ...]
    source_csv_sha256: str


@dataclass(frozen=True)
class SavedFieldBundle:
    data: FieldDataset
    sensors: tuple[Sensor, ...]
    sources: tuple[FieldSource, ...]
    workspace_sha256: str
    evidence_sha256: str


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(folder, name, limit):
    path = folder/name
    if path.is_symlink() or path.resolve().parent != folder or not path.is_file():
        raise ValueError('Bundle files must be regular files directly inside the chosen folder')
    with path.open('rb') as stream:
        raw = stream.read(limit+1)
    if len(raw) > limit:
        raise ValueError('Bundle file exceeds limit: '+name)
    return raw


def _saved_only(document):
    if document['new_solve'] is not False or document['sensor_response'] != 'Not calibrated MTJ voltage':
        raise ValueError('Expected saved fields without a new solve or calibrated sensor response')


def _sensors(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise ValueError('Invalid evidence sensor layout')
    result = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'point_id', 'position_m', 'axis'}
                or not isinstance(row['position_m'], list) or not isinstance(row['axis'], list)):
            raise ValueError('Invalid evidence sensor fields')
        result.append(Sensor(row['point_id'], tuple(row['position_m']), tuple(row['axis'])))
    validate_layout(tuple(result))
    return tuple(result)


def _source(document, data, sensors):
    if not isinstance(document, dict) or set(document) != SINGLE_KEYS or document['schema'] != SINGLE:
        raise ValueError('Unsupported saved-field source evidence')
    _saved_only(document)
    if (document['method'] != 'COMSOL Interp at fixed global XYZ points'
            or type(document['extrapolation']) is not int or document['extrapolation'] != 0
            or type(document['phase_rotation_deg']) not in (int, float) or document['phase_rotation_deg'] != 0):
        raise ValueError('Expected fixed Cartesian points without extrapolation or phase rotation')
    meta = FieldMetadata(**document['metadata'])
    validate_metadata(meta)
    if any(getattr(meta, key) != getattr(data.metadata, key) for key in SHARED) or meta.model_revision != document['model_sha256']:
        raise ValueError('Source metadata is incompatible with the saved dataset')
    if _sensors(document['sensors']) != sensors:
        raise ValueError('Source and workspace layouts differ')
    rows = document['states']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError('Expected 1-32 explicit saved states per source')
    states = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'scenario', *SavedState.__dataclass_fields__}:
            raise ValueError('Invalid saved-state fields')
        states.append((row['scenario'], SavedState(**{k: v for k, v in row.items() if k != 'scenario'})))
    expressions = document['expressions']
    if not isinstance(expressions, list):
        raise ValueError('Expected Cartesian expression names')
    selection = FieldSelection(document['model_sha256'], tuple(states), tuple(expressions),
                               meta.phasor_convention, meta.excitation, meta.phase_reference)
    validate_selection(selection, sensors)
    if any(state.frequency_hz != meta.frequency_hz for _, state in states):
        raise ValueError('State frequency differs from declared frequency')
    names = {name for name, _ in states}
    samples = tuple(s for s in data.samples if s.scenario in names)
    if {s.scenario for s in samples} != names or _sha(_field_csv(samples)) != document['source_csv_sha256']:
        raise ValueError('Source CSV hash or scenario coverage differs')
    positions = {s.point_id: s.position_m for s in sensors}
    if any(s.point_id not in positions or s.position_m != positions[s.point_id] for s in samples):
        raise ValueError('Sample coordinates differ from the fixed source layout')
    return tuple(FieldSource(name, selection.model_sha256, state, selection.expressions,
                              document['source_csv_sha256']) for name, state in states)


def load_saved_field_bundle(folder) -> SavedFieldBundle:
    """Read four known bounded files once, then validate their complete association."""
    folder = Path(folder).resolve()
    marker = _read(folder, 'COMPLETE', 128)
    csv = _read(folder, 'fields.csv', 5_000_000)
    workspace = _read(folder, 'workspace.json', 8_000_000)
    raw_evidence = _read(folder, 'evidence.json', 500_000)
    if marker.strip() != b'All files written. Verify hashes in evidence.json.':
        raise ValueError('Incomplete or unsupported bundle completion marker')
    try:
        document = json.loads(raw_evidence.decode('utf-8'), object_pairs_hook=_object)
        if not isinstance(document, dict):
            raise ValueError('Expected saved-field evidence object')
        schema = document.get('schema')
        keys = SINGLE_KEYS if schema == SINGLE else CAMPAIGN_KEYS if schema == CAMPAIGN else set()
        if not keys or set(document) != keys | {'workspace_sha256'}:
            raise ValueError('Unsupported saved-field bundle evidence')
        _saved_only(document)
        if document['workspace_sha256'] != _sha(workspace) or document['source_csv_sha256'] != _sha(csv):
            raise ValueError('Saved-field bundle failed file integrity checks')
        data, sensors = parse_field_workspace(workspace)
        if (data.metadata.source_kind != 'comsol-export' or data.metadata.coordinate_unit != 'm'
                or data.metadata.field_unit != 'T' or asdict(data.metadata) != document['metadata']
                or data != parse_field_csv(csv, data.metadata)):
            raise ValueError('CSV, workspace or metadata do not describe the same saved Cartesian fields')
        if schema == SINGLE:
            sources = _source({k: v for k, v in document.items() if k != 'workspace_sha256'}, data, sensors)
        else:
            rows = document['sources']
            if (not isinstance(rows, list) or not 1 <= len(rows) <= 32
                    or not isinstance(document['compatibility'], str) or len(document['compatibility']) > 400
                    or any(not 32 <= ord(c) < 127 for c in document['compatibility'])):
                raise ValueError('Invalid saved-field campaign sources or compatibility declaration')
            sources = tuple(source for row in rows for source in _source(row, data, sensors))
        if (len(sources) != len(data.scenarios) or {s.scenario for s in sources} != set(data.scenarios)
                or len({s.expressions for s in sources}) != 1):
            raise ValueError('Duplicate/missing scenario provenance or incompatible Cartesian expressions')
        return SavedFieldBundle(data, sensors, sources, _sha(workspace), _sha(raw_evidence))
    except (TypeError, KeyError, UnicodeError, OverflowError, RecursionError, AttributeError) as exc:
        raise ValueError('Invalid saved-field bundle') from exc
