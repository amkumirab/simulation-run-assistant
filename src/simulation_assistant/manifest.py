from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BatchManifest:
    name: str
    adapter: str
    jobs: list[dict[str, Any]]


def load_manifest(path: str | Path) -> BatchManifest:
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {manifest_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("Manifest root must be a JSON object")
    name = data.get("name")
    adapter = data.get("adapter", "mock-em")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Manifest field 'name' must be a non-empty string")
    if not isinstance(adapter, str) or not adapter.strip():
        raise ValueError("Manifest field 'adapter' must be a non-empty string")

    has_jobs = "jobs" in data
    has_sweep = "sweep" in data
    if has_jobs == has_sweep:
        raise ValueError("Manifest must define exactly one of 'jobs' or 'sweep'")

    if has_jobs:
        raw_jobs = data["jobs"]
        if not isinstance(raw_jobs, list) or not raw_jobs:
            raise ValueError("Manifest field 'jobs' must be a non-empty list")
        if not all(isinstance(item, dict) for item in raw_jobs):
            raise ValueError("Every job must be a JSON object")
        jobs = raw_jobs
    else:
        jobs = _expand_sweep(data["sweep"], data.get("fixed", {}))

    if len(jobs) > 10_000:
        raise ValueError("Manifest expands to more than 10,000 jobs")
    return BatchManifest(name=name.strip(), adapter=adapter.strip(), jobs=jobs)


def _expand_sweep(sweep: Any, fixed: Any) -> list[dict[str, Any]]:
    if not isinstance(sweep, dict) or not sweep:
        raise ValueError("Manifest field 'sweep' must be a non-empty object")
    if not isinstance(fixed, dict):
        raise ValueError("Manifest field 'fixed' must be an object")

    keys = list(sweep)
    values: list[list[Any]] = []
    for key in keys:
        candidates = sweep[key]
        if not isinstance(candidates, list) or not candidates:
            raise ValueError(f"Sweep field '{key}' must be a non-empty list")
        values.append(candidates)

    jobs = []
    for combination in itertools.product(*values):
        parameters = dict(fixed)
        parameters.update(dict(zip(keys, combination)))
        jobs.append(parameters)
    return jobs
