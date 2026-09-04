from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from simulation_assistant.formulas import validate_output_formulas
from simulation_assistant.sweeps import parse_sweep_values


PROFILE_SCHEMA_VERSION = 1
FEATURE_TAG = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class WorkspaceProfile:
    name: str
    executable_path: str
    model_path: str
    contract_path: str
    target_mode: str
    study_tag: str
    job_tag: str
    timeout_seconds: int
    cores: int | None
    batch_name: str
    parameters: dict[str, str]
    parameter_modes: dict[str, str]
    output_formulas: dict[str, str]
    plot_tags: tuple[str, ...]
    updated_at: str

    @classmethod
    def create(
        cls,
        *,
        name: str,
        executable_path: str,
        model_path: str,
        contract_path: str = "",
        target_mode: str = "study",
        study_tag: str = "",
        job_tag: str = "",
        timeout_seconds: int = 3600,
        cores: int | None = None,
        batch_name: str = "desktop-comsol-run",
        parameters: Mapping[str, str] | None = None,
        parameter_modes: Mapping[str, str] | None = None,
        output_formulas: Mapping[str, str] | None = None,
        plot_tags: tuple[str, ...] | list[str] | None = None,
        updated_at: str | None = None,
    ) -> WorkspaceProfile:
        profile = cls(
            name=name.strip(),
            executable_path=executable_path.strip(),
            model_path=model_path.strip(),
            contract_path=contract_path.strip(),
            target_mode=target_mode.strip().lower(),
            study_tag=study_tag.strip(),
            job_tag=job_tag.strip(),
            timeout_seconds=timeout_seconds,
            cores=cores,
            batch_name=batch_name.strip(),
            parameters={str(key): str(value) for key, value in (parameters or {}).items()},
            parameter_modes={
                str(key): str(value) for key, value in (parameter_modes or {}).items()
            },
            output_formulas={
                str(key): str(value) for key, value in (output_formulas or {}).items()
            },
            plot_tags=tuple(str(tag) for tag in (plot_tags or ())),
            updated_at=updated_at or _utc_now(),
        )
        validate_profile(profile)
        return profile

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkspaceProfile:
        try:
            return cls.create(
                name=str(data["name"]),
                executable_path=str(data["executable_path"]),
                model_path=str(data["model_path"]),
                contract_path=str(data.get("contract_path", "")),
                target_mode=str(data.get("target_mode", "study")),
                study_tag=str(data.get("study_tag", "")),
                job_tag=str(data.get("job_tag", "")),
                timeout_seconds=int(data.get("timeout_seconds", 3600)),
                cores=(int(data["cores"]) if data.get("cores") is not None else None),
                batch_name=str(data.get("batch_name", "desktop-comsol-run")),
                parameters=_string_mapping(data.get("parameters", {}), "parameters"),
                parameter_modes=_string_mapping(
                    data.get("parameter_modes", {}), "parameter_modes"
                ),
                output_formulas=_string_mapping(
                    data.get("output_formulas", {}), "output_formulas"
                ),
                plot_tags=_string_list(data.get("plot_tags", []), "plot_tags"),
                updated_at=str(data.get("updated_at") or _utc_now()),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid workspace profile: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _string_mapping(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"Profile field '{label}' must be an object")
    return {str(key): str(item) for key, item in value.items()}


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"Profile field '{label}' must be a list")
    return [str(item) for item in value]


def validate_profile(profile: WorkspaceProfile) -> None:
    if not profile.name:
        raise ValueError("Profile name cannot be empty")
    if len(profile.name) > 80 or any(ord(character) < 32 for character in profile.name):
        raise ValueError("Profile name must be at most 80 printable characters")
    if not profile.executable_path:
        raise ValueError("COMSOL executable path cannot be empty")
    if not profile.model_path:
        raise ValueError("MPH model path cannot be empty")
    if profile.contract_path and Path(profile.contract_path).suffix.lower() != ".json":
        raise ValueError("Model contract path must use the .json extension")
    if profile.target_mode not in {"study", "job"}:
        raise ValueError("Profile target mode must be 'study' or 'job'")
    if profile.timeout_seconds < 1:
        raise ValueError("Profile timeout must be a positive integer")
    if profile.cores is not None and profile.cores < 1:
        raise ValueError("Profile core count must be a positive integer")
    if not profile.batch_name:
        raise ValueError("Profile run label cannot be empty")

    parameter_names = set(profile.parameters)
    unknown_modes = set(profile.parameter_modes).difference(parameter_names)
    if unknown_modes:
        names = ", ".join(sorted(unknown_modes))
        raise ValueError(f"Profile modes reference unknown parameters: {names}")
    for name, value in profile.parameters.items():
        if not name or not value.strip():
            raise ValueError("Profile parameters need non-empty names and values")
        mode = profile.parameter_modes.get(name, "Fixed")
        if mode not in {"Fixed", "Sweep"}:
            raise ValueError(f"Parameter '{name}' has an invalid profile mode")
        if mode == "Sweep":
            parse_sweep_values(value)
    validate_output_formulas(profile.output_formulas)
    if len(profile.plot_tags) != len(set(profile.plot_tags)):
        raise ValueError("Profile plot tags cannot be duplicated")
    if len(profile.plot_tags) > 12:
        raise ValueError("Profile cannot select more than 12 plot groups")
    if any(not FEATURE_TAG.fullmatch(tag) for tag in profile.plot_tags):
        raise ValueError("Profile plot tags contain an invalid COMSOL feature tag")


def missing_local_paths(profile: WorkspaceProfile) -> list[tuple[str, Path]]:
    missing: list[tuple[str, Path]] = []
    for label, raw_path in (
        ("COMSOL executable", profile.executable_path),
        ("MPH model", profile.model_path),
        ("Model contract", profile.contract_path),
    ):
        if not raw_path:
            continue
        path = Path(raw_path).expanduser()
        if not path.is_file():
            missing.append((label, path))
    return missing


class ProfileStore:
    """Atomic local JSON storage for native workspace profiles."""

    def __init__(self, path: str | Path = ".sim-assistant/profiles.json") -> None:
        self.path = Path(path)

    def list(self) -> list[WorkspaceProfile]:
        profiles, _last_profile = self._read()
        indexed_profiles = enumerate(profiles)
        return [
            profile
            for _index, profile in sorted(
                indexed_profiles,
                key=lambda item: (item[1].updated_at, item[0]),
                reverse=True,
            )
        ]

    def get(self, name: str) -> WorkspaceProfile:
        profiles, _last_profile = self._read()
        match = _find_profile(profiles, name)
        if match is None:
            raise KeyError(f"Workspace profile '{name}' was not found")
        return match

    def save(self, profile: WorkspaceProfile, *, set_last: bool = True) -> None:
        validate_profile(profile)
        profiles, last_profile = self._read()
        profiles = [
            existing
            for existing in profiles
            if existing.name.casefold() != profile.name.casefold()
        ]
        refreshed = replace(profile, updated_at=_next_updated_at(profiles))
        profiles.append(refreshed)
        self._write(profiles, refreshed.name if set_last else last_profile)

    def duplicate(self, source_name: str, new_name: str) -> WorkspaceProfile:
        source = self.get(source_name)
        profiles, _last_profile = self._read()
        if _find_profile(profiles, new_name) is not None:
            raise ValueError(f"Workspace profile '{new_name}' already exists")
        duplicate = WorkspaceProfile.create(
            **{
                **source.to_dict(),
                "name": new_name,
                "updated_at": _utc_now(),
            }
        )
        self.save(duplicate)
        return self.get(duplicate.name)

    def delete(self, name: str) -> None:
        profiles, last_profile = self._read()
        match = _find_profile(profiles, name)
        if match is None:
            raise KeyError(f"Workspace profile '{name}' was not found")
        remaining = [
            profile for profile in profiles if profile.name.casefold() != name.casefold()
        ]
        next_last = (
            None
            if last_profile and last_profile.casefold() == name.casefold()
            else last_profile
        )
        self._write(remaining, next_last)

    def set_last(self, name: str | None) -> None:
        profiles, _last_profile = self._read()
        if name is not None:
            match = _find_profile(profiles, name)
            if match is None:
                raise KeyError(f"Workspace profile '{name}' was not found")
            name = match.name
            next_updated_at = _next_updated_at(profiles)
            profiles = [
                replace(profile, updated_at=next_updated_at)
                if profile.name.casefold() == name.casefold()
                else profile
                for profile in profiles
            ]
        self._write(profiles, name)

    def last(self) -> WorkspaceProfile | None:
        profiles, last_profile = self._read()
        return _find_profile(profiles, last_profile) if last_profile else None

    def _read(self) -> tuple[list[WorkspaceProfile], str | None]:
        if not self.path.exists():
            return [], None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read workspace profiles: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Workspace profile file must contain a JSON object")
        if data.get("schema_version") != PROFILE_SCHEMA_VERSION:
            raise ValueError("Unsupported workspace profile schema version")
        raw_profiles = data.get("profiles", [])
        if not isinstance(raw_profiles, list):
            raise ValueError("Workspace profile list is invalid")
        profiles = [WorkspaceProfile.from_dict(item) for item in raw_profiles]
        names = [profile.name.casefold() for profile in profiles]
        if len(names) != len(set(names)):
            raise ValueError("Workspace profile names must be unique")
        last_profile = data.get("last_profile")
        if last_profile is not None and not isinstance(last_profile, str):
            raise ValueError("Last workspace profile name is invalid")
        return profiles, last_profile

    def _write(
        self,
        profiles: list[WorkspaceProfile],
        last_profile: str | None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "last_profile": last_profile,
            "profiles": [profile.to_dict() for profile in profiles],
        }
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def _find_profile(
    profiles: list[WorkspaceProfile],
    name: str | None,
) -> WorkspaceProfile | None:
    if not name:
        return None
    normalized = name.strip().casefold()
    return next(
        (profile for profile in profiles if profile.name.casefold() == normalized),
        None,
    )


def _next_updated_at(profiles: list[WorkspaceProfile]) -> str:
    now = datetime.now(timezone.utc)
    existing = []
    for profile in profiles:
        try:
            parsed = datetime.fromisoformat(profile.updated_at)
        except ValueError:
            continue
        existing.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc))
    if existing and now <= max(existing):
        now = max(existing) + timedelta(microseconds=1)
    return now.isoformat(timespec="microseconds")


def sanitized_profile_template(profile: WorkspaceProfile) -> dict[str, Any]:
    validate_profile(profile)
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "name": profile.name,
        "local_paths_excluded": True,
        "contract_path_excluded": bool(profile.contract_path),
        "target": {
            "mode": profile.target_mode,
            "study_tag": profile.study_tag,
            "job_tag": profile.job_tag,
        },
        "run": {
            "timeout_seconds": profile.timeout_seconds,
            "cores": profile.cores,
            "batch_name": profile.batch_name,
        },
        "parameters": {
            name: {
                "mode": profile.parameter_modes.get(name, "Fixed"),
                "value": value,
            }
            for name, value in profile.parameters.items()
        },
        "output_formulas": dict(profile.output_formulas),
        "plot_tags": list(profile.plot_tags),
    }


def write_sanitized_profile_template(
    path: str | Path,
    profile: WorkspaceProfile,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(sanitized_profile_template(profile), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
