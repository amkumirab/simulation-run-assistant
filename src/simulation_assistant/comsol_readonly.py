"""Bounded compiler/batch transport for packaged, read-only model helpers."""
import base64
import gzip
import hashlib
import re
import shutil
import tempfile
from pathlib import Path

from simulation_assistant.process_control import run_cancellable_process

HELPERS = {'SavedFieldSampler': 'FIELD_SAMPLING', 'SavedGeometryInspector': 'GEOMETRY_INSPECTION'}


def model_digest(path):
    path = Path(path)
    if path.suffix.lower() != '.mph' or not path.is_file() or path.stat().st_size > 2_000_000_000:
        raise ValueError('Choose an existing MPH file no larger than 2 GB')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def run_helper(model, executable, helper, mode, request='', points='', *, expected_sha256,
               cancel_requested=lambda: False, runner=run_cancellable_process):
    if helper not in HELPERS:
        raise ValueError('Unsupported read-only helper')
    executable = Path(executable).resolve()
    compiler = executable.with_name('comsolcompile'+executable.suffix)
    if not executable.is_file() or not compiler.is_file():
        raise ValueError('Select comsolbatch with comsolcompile installed beside it')
    with tempfile.TemporaryDirectory(prefix='readonly-comsol-') as directory:
        root = Path(directory)
        copy = root/'source.mph'
        shutil.copyfile(model, copy)
        if model_digest(copy) != expected_sha256:
            raise ValueError('Model changed while making the private snapshot; inspect again')
        source = root/(helper+'.java')
        shutil.copyfile(Path(__file__).with_name(source.name), source)
        compiled = runner([str(compiler), str(source)], cwd=root, timeout=120, cancel_requested=cancel_requested)
        if compiled.returncode or not source.with_suffix('.class').is_file():
            raise RuntimeError('COMSOL read-only helper compilation failed: '+(compiled.stderr or compiled.stdout)[-1200:])
        payloads = [base64.b64encode(gzip.compress(value.encode('utf-8'), mtime=0)).decode('ascii') for value in (request, points)]
        command = [str(executable), '-inputfile', str(source.with_suffix('.class')),
                   '-batchlog', str(root/'engine.log'), '-nosave', '-np', '1', '-prodargs', str(copy), mode,
                   payloads[0], '-', payloads[1]]
        if sum(len(argument)+3 for argument in command) > 26000:
            raise ValueError('Request is too large for the COMSOL command line')
        result = runner(command, cwd=root, timeout=300, cancel_requested=cancel_requested)
        log = (root/'engine.log').read_text(encoding='utf-8', errors='replace') if (root/'engine.log').exists() else ''
        marker = HELPERS[helper]
        for transcript in (result.stdout, log):
            match = re.search(r'^'+marker+r'_BEGIN\r?\n(.*?)^'+marker+r'_OK\r?$', transcript, re.MULTILINE | re.DOTALL)
            if not result.returncode and match:
                raw = match.group(1).replace('\r\n', '\n').encode('utf-8')
                if len(raw) > 5_000_000:
                    raise ValueError('Engine output exceeds 5 MB')
                return raw
        raise RuntimeError('Read-only COMSOL operation failed (no solve started): '+(log+'\n'+result.stderr+'\n'+result.stdout)[-4000:])
