"""Read saved Cartesian field solutions without solving or saving source models."""
from __future__ import annotations

import csv
import base64
import gzip
import hashlib
import io
import json
import math
import re
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from simulation_assistant.field_samples import (
    FieldDataset, FieldMetadata, FieldSample, Sensor, validate_dataset, validate_layout,
    validate_label, validate_metadata,
)
from simulation_assistant.field_sample_files import FIELD_COLUMNS, save_field_workspace
from simulation_assistant.process_control import run_cancellable_process

TAG = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,39}\Z')
COMPONENT = re.compile(r'(?:[A-Za-z][A-Za-z0-9_]{0,39}\.){1,3}B[xyz]\Z')
CATALOG_COLUMNS = ('dataset', 'solver', 'outer', 'inner', 'frequency_hz', 'parameters')
VALUE_COLUMNS = ('scenario', 'point_id', 'bx_real', 'bx_imag', 'by_real', 'by_imag', 'bz_real', 'bz_imag')


@dataclass(frozen=True)
class SavedState:
    dataset: str
    solver: str
    outer: int
    inner: int
    frequency_hz: float
    parameters: str


@dataclass(frozen=True)
class FieldSelection:
    model_sha256: str
    states: tuple[tuple[str, SavedState], ...]
    expressions: tuple[str, str, str]
    phasor_convention: str
    excitation: str
    phase_reference: str


@dataclass(frozen=True)
class FieldExtraction:
    data: FieldDataset
    sensors: tuple[Sensor, ...]
    csv_bytes: bytes
    evidence: dict


@dataclass(frozen=True)
class SavedScenario:
    name: str
    model_path: Path
    model_sha256: str
    state: SavedState


def model_digest(path: str | Path) -> str:
    path = Path(path)
    if path.suffix.lower() != '.mph' or not path.is_file() or path.stat().st_size > 2_000_000_000:
        raise ValueError('Choose an existing MPH file no larger than 2 GB')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _state(state):
    if not isinstance(state, SavedState) or any(not isinstance(v, str) or not TAG.fullmatch(v) for v in (state.dataset, state.solver)):
        raise ValueError('Invalid saved dataset or solver tag')
    if any(type(v) is not int or not 1 <= v <= 100000 for v in (state.outer, state.inner)):
        raise ValueError('Explicit positive outer/inner solution indices are required')
    if (type(state.frequency_hz) not in (int, float) or not 0 < state.frequency_hz <= 1e12
            or not math.isfinite(state.frequency_hz)):
        raise ValueError('Only saved frequency-domain states with a finite frequency are supported')
    if not isinstance(state.parameters, str) or len(state.parameters) > 4096 or any(ord(c) < 32 for c in state.parameters):
        raise ValueError('Invalid saved parameter description')


def _rows(raw, columns, limit):
    if not isinstance(raw, bytes) or len(raw) > 5_000_000:
        raise ValueError('Engine output exceeds 5 MB')
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter='\t', strict=True)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError('Unexpected engine output schema')
        rows = []
        for row in reader:
            if len(rows) >= limit or set(row) != set(columns) or any(v is None for v in row.values()):
                raise ValueError('Invalid or excessive engine rows')
            rows.append(row)
        return rows
    except (csv.Error, UnicodeError) as exc:
        raise ValueError('Invalid engine output') from exc


def read_catalog(raw: bytes) -> tuple[SavedState, ...]:
    result, seen = [], set()
    for row in _rows(raw, CATALOG_COLUMNS, 10000):
        state = SavedState(row['dataset'], row['solver'], int(row['outer']), int(row['inner']),
                           float(row['frequency_hz']), row['parameters'])
        _state(state)
        key = state.dataset, state.solver, state.outer, state.inner
        if key in seen:
            raise ValueError('Duplicate saved state')
        result.append(state)
        seen.add(key)
    if not result:
        raise ValueError('No supported saved frequency-domain states found; no solve was started')
    return tuple(result)


def validate_selection(selection: FieldSelection, sensors: tuple[Sensor, ...]):
    validate_layout(sensors)
    if not isinstance(selection, FieldSelection) or not isinstance(selection.model_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', selection.model_sha256):
        raise ValueError('Inspect this model before extracting fields')
    if not isinstance(selection.states, tuple) or not 1 <= len(selection.states) <= 32 or len(selection.states)*len(sensors) > 10000:
        raise ValueError('Choose 1-32 named states, at most 10000 total samples')
    seen = set()
    for name, state in selection.states:
        validate_label(name)
        _state(state)
        if name in seen or state.frequency_hz != selection.states[0][1].frequency_hz:
            raise ValueError('Scenario names must be unique and frequencies must match exactly')
        seen.add(name)
    if (not isinstance(selection.expressions, tuple) or len(selection.expressions) != 3
            or any(not isinstance(expr, str) or not COMPONENT.fullmatch(expr) or not expr.endswith('B'+axis)
                   for expr, axis in zip(selection.expressions, 'xyz'))
            or len({expr.rsplit('.', 1)[0] for expr in selection.expressions}) != 1):
        raise ValueError('Declare qualified Cartesian Bx, By, Bz symbols from one physics interface; formulas are not accepted')
    validate_metadata(_metadata(selection))


def _metadata(selection):
    return FieldMetadata('Saved COMSOL fields', 'comsol-export', selection.model_sha256, 'Explicit saved states',
                         'Global Cartesian XYZ', 'm', 'T', selection.states[0][1].frequency_hz,
                         selection.phasor_convention, selection.excitation, selection.phase_reference)


def _tsv(columns, rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter='\t', lineterminator='\n')
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue()


def _field_csv(samples):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(FIELD_COLUMNS)
    for sample in samples:
        writer.writerow((sample.scenario, sample.point_id, *sample.position_m,
                         *(part for value in sample.field for part in (value.real, value.imag))))
    return stream.getvalue().encode('utf-8')


def _engine(model, executable, mode, request='', points='', *, expected_sha256, cancel_requested=lambda: False):
    executable = Path(executable).resolve()
    compiler = executable.with_name('comsolcompile'+executable.suffix)
    if not executable.is_file() or not compiler.is_file():
        raise ValueError('Select comsolbatch with comsolcompile installed beside it')
    with tempfile.TemporaryDirectory(prefix='saved-field-') as directory:
        root = Path(directory)
        copy = root / 'source.mph'
        shutil.copyfile(model, copy)
        if model_digest(copy) != expected_sha256:
            raise ValueError('Model changed while making the private snapshot; inspect again')
        source = root / 'SavedFieldSampler.java'
        shutil.copyfile(Path(__file__).with_name(source.name), source)
        compiled = run_cancellable_process([str(compiler), str(source)], cwd=root, timeout=120, cancel_requested=cancel_requested)
        if compiled.returncode or not source.with_suffix('.class').is_file():
            raise RuntimeError('COMSOL field helper compilation failed: '+(compiled.stderr or compiled.stdout)[-1200:])
        payloads = [base64.b64encode(gzip.compress(value.encode('utf-8'), mtime=0)).decode('ascii') for value in (request, points)]
        command = [str(executable), '-inputfile', str(source.with_suffix('.class')),
                 '-batchlog', str(root/'engine.log'), '-nosave', '-np', '1', '-prodargs', str(copy), mode,
                 payloads[0], '-', payloads[1]]
        if sum(len(argument)+3 for argument in command) > 26000:
            raise ValueError('Sampling request is too large for the COMSOL command line; use fewer sensors/states')
        result = run_cancellable_process(command,
                 cwd=root, timeout=300, cancel_requested=cancel_requested)
        log = (root/'engine.log').read_text(encoding='utf-8', errors='replace') if (root/'engine.log').exists() else ''
        for transcript in (result.stdout, log):
            match = re.search(r'^FIELD_SAMPLING_BEGIN\r?\n(.*?)^FIELD_SAMPLING_OK\r?$', transcript, re.MULTILINE | re.DOTALL)
            if not result.returncode and match:
                raw = match.group(1).replace('\r\n', '\n').encode('utf-8')
                if len(raw) > 5_000_000:
                    raise ValueError('Engine output exceeds 5 MB')
                return raw
        raise RuntimeError('Saved-field operation failed (no solve started): '+(log+'\n'+result.stderr+'\n'+result.stdout)[-4000:])


def inspect_saved_fields(model, executable, *, cancel_requested=lambda: False):
    """Return (source SHA-256, states) from a private model copy, without solving."""
    digest = model_digest(model)
    raw = _engine(model, executable, 'catalog', expected_sha256=digest, cancel_requested=cancel_requested)
    if model_digest(model) != digest:
        raise ValueError('Source model changed during inspection; inspect again')
    return digest, read_catalog(raw)


def extract_saved_fields(model, executable, selection, sensors, *, cancel_requested=lambda: False) -> FieldExtraction:
    """All-or-nothing field extraction, bound to source identity and explicit states."""
    validate_selection(selection, sensors)
    if model_digest(model) != selection.model_sha256:
        raise ValueError('Source model changed; inspect it again')
    request = '\t'.join(selection.expressions)+'\n'+_tsv(('scenario', *CATALOG_COLUMNS), [
        (name, state.dataset, state.solver, state.outer, state.inner, state.frequency_hz, state.parameters) for name, state in selection.states])
    points = _tsv(('point_id', 'x_m', 'y_m', 'z_m'), [(sensor.point_id, *sensor.position_m) for sensor in sensors])
    raw = _engine(model, executable, 'extract', request, points, expected_sha256=selection.model_sha256, cancel_requested=cancel_requested)
    if model_digest(model) != selection.model_sha256:
        raise ValueError('Source model changed during extraction; results rejected')
    index = {(name, sensor.point_id): sensor for name, _ in selection.states for sensor in sensors}
    samples, seen = [], set()
    for row in _rows(raw, VALUE_COLUMNS, 10000):
        key = row['scenario'], row['point_id']
        if key not in index or key in seen:
            raise ValueError('Unexpected or duplicate sampled point')
        field = tuple(complex(float(row[f'b{axis}_real']), float(row[f'b{axis}_imag'])) for axis in 'xyz')
        samples.append(FieldSample(*key, index[key].position_m, field))
        seen.add(key)
    if seen != set(index):
        raise ValueError('Incomplete field extraction; no partial dataset accepted')
    csv_bytes = _field_csv(samples)
    data = FieldDataset(_metadata(selection), tuple(samples), hashlib.sha256(csv_bytes).hexdigest())
    validate_dataset(data)
    evidence = {'schema': 'wpt.saved-field-evidence.v1', 'model_sha256': selection.model_sha256,
                'states': [{'scenario': name, **asdict(state)} for name, state in selection.states],
                'expressions': selection.expressions, 'source_csv_sha256': data.source_sha256,
                'metadata': asdict(data.metadata), 'method': 'COMSOL Interp at fixed global XYZ points',
                'extrapolation': 0, 'phase_rotation_deg': 0, 'new_solve': False,
                'sensor_response': 'Not calibrated MTJ voltage', 'sensors': [asdict(s) for s in sensors]}
    return FieldExtraction(data, sensors, csv_bytes, evidence)


def extract_scenarios(scenarios, executable, expressions, sensors, phasor_convention,
                      excitation, phase_reference, *, cancel_requested=lambda: False) -> FieldExtraction:
    """Compare fixed locations across explicitly declared compatible source files."""
    if not isinstance(scenarios, tuple) or not 1 <= len(scenarios) <= 32 or any(not isinstance(s, SavedScenario) for s in scenarios):
        raise ValueError('Add 1-32 explicit saved scenarios')
    selection = FieldSelection(scenarios[0].model_sha256, tuple((s.name, s.state) for s in scenarios),
                               expressions, phasor_convention, excitation, phase_reference)
    validate_selection(selection, sensors)
    # Validate all source identities before launching any expensive engine work.
    for scenario in scenarios:
        if model_digest(scenario.model_path) != scenario.model_sha256:
            raise ValueError('A source model changed; inspect and add its state again')
    results = []
    for scenario in scenarios:
        current = FieldSelection(scenario.model_sha256, ((scenario.name, scenario.state),), expressions,
                                 phasor_convention, excitation, phase_reference)
        results.append(extract_saved_fields(scenario.model_path, executable, current, sensors,
                                           cancel_requested=cancel_requested))
    for scenario in scenarios:
        if model_digest(scenario.model_path) != scenario.model_sha256:
            raise ValueError('A source model changed during sampling; all results rejected')
    # Each validated CSV shares its exact header and SI metadata.
    csv_bytes = results[0].csv_bytes + b''.join(r.csv_bytes.split(b'\n', 1)[1] for r in results[1:])
    from dataclasses import replace
    meta = replace(results[0].data.metadata, model_revision='See source evidence bundle', solution_id='Explicit saved scenarios')
    data = FieldDataset(meta, tuple(sample for r in results for sample in r.data.samples), hashlib.sha256(csv_bytes).hexdigest())
    validate_dataset(data)
    evidence = {'schema': 'wpt.saved-field-campaign.v1', 'source_csv_sha256': data.source_sha256,
                'metadata': asdict(meta), 'sources': [r.evidence for r in results],
                'compatibility': 'Shared frame, excitation and phase reference declared by user; not scientifically certified',
                'new_solve': False, 'sensor_response': 'Not calibrated MTJ voltage'}
    return FieldExtraction(data, sensors, csv_bytes, evidence)


def save_source_bundle(parent, result: FieldExtraction) -> Path:
    """Create a new portable directory; never overwrite a model or existing bundle."""
    validate_dataset(result.data)
    validate_layout(result.sensors)
    if (result.csv_bytes != _field_csv(result.data.samples)
            or hashlib.sha256(result.csv_bytes).hexdigest() != result.data.source_sha256
            or result.evidence.get('source_csv_sha256') != result.data.source_sha256):
        raise ValueError('Source bundle CSV and evidence do not match the validated dataset')
    target = Path(parent) / ('saved-field-'+uuid.uuid4().hex[:12])
    target.mkdir(parents=False, exist_ok=False)
    (target/'fields.csv').write_bytes(result.csv_bytes)
    workspace = save_field_workspace(target/'workspace.json', result.data, result.sensors)
    evidence = {**result.evidence, 'workspace_sha256': hashlib.sha256(workspace.read_bytes()).hexdigest()}
    (target/'evidence.json').write_text(json.dumps(evidence, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    (target/'COMPLETE').write_text('All files written. Verify hashes in evidence.json.\n', encoding='ascii')
    return target.resolve()
