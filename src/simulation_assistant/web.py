from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from simulation_assistant.adapters import ComsolAdapter, MockElectromagneticAdapter
from simulation_assistant.adapters.comsol import (
    ComsolConfig,
    check_comsol,
    discover_comsol_executable,
)
from simulation_assistant.notifications import notifier_from_environment
from simulation_assistant.runner import SimulationRunner
from simulation_assistant.storage import JobStore


JOB_PATH = re.compile(r"^/api/jobs/(\d+)$")
RETRY_PATH = re.compile(r"^/api/jobs/(\d+)/retry$")
MAX_REQUEST_BYTES = 64 * 1024
ComsolChecker = Callable[[ComsolConfig], dict[str, Any]]


def create_dashboard_server(
    database_path: str | Path,
    artifact_root: str | Path,
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    comsol_checker: ComsolChecker = check_comsol,
) -> ThreadingHTTPServer:
    """Create the localhost dashboard server without starting its event loop."""
    _require_loopback(host)
    store = JobStore(database_path)
    store.initialize()
    api_token = secrets.token_urlsafe(32)
    dashboard_html = (
        files("simulation_assistant")
        .joinpath("dashboard.html")
        .read_text(encoding="utf-8")
        .replace("__API_TOKEN__", json.dumps(api_token))
    )

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            path = urlparse(self.path).path
            if path == "/":
                self._write(HTTPStatus.OK, dashboard_html, "text/html; charset=utf-8")
                return
            if path == "/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/api/comsol/discovery":
                self._json(HTTPStatus.OK, _discovery_payload())
                return
            if path == "/api/jobs":
                self._json(
                    HTTPStatus.OK,
                    {
                        "counts": store.counts(),
                        "jobs": [job.to_dict() for job in store.list(limit=200)],
                    },
                )
                return
            match = JOB_PATH.match(path)
            if match:
                try:
                    job = store.get(int(match.group(1)))
                except KeyError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Job not found"})
                    return
                self._json(HTTPStatus.OK, job.to_dict())
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if not hmac.compare_digest(
                self.headers.get("X-Sim-Assistant-Token", ""), api_token
            ):
                self._json(HTTPStatus.FORBIDDEN, {"error": "Invalid session token"})
                return

            try:
                payload = self._read_json()
                path = urlparse(self.path).path
                if path == "/api/comsol/check":
                    config = _config_from_payload(payload)
                    self._json(HTTPStatus.OK, comsol_checker(config))
                    return
                if path == "/api/runs":
                    self._create_run(payload, store, artifact_root)
                    return
                if path == "/api/queue/run-next":
                    config = _config_from_payload(payload)
                    summary = _runner(store, artifact_root, config).run_pending(limit=1)
                    self._json(HTTPStatus.OK, _summary_payload(summary))
                    return
                match = RETRY_PATH.match(path)
                if match:
                    job_id = int(match.group(1))
                    store.retry(job_id)
                    self._json(HTTPStatus.OK, store.get(job_id).to_dict())
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except (OSError, RuntimeError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except Exception:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "Unexpected dashboard error"},
                )

        def _create_run(
            self,
            payload: dict[str, Any],
            current_store: JobStore,
            current_artifact_root: str | Path,
        ) -> None:
            config = _config_from_payload(payload)
            batch_name = payload.get("batch_name", "")
            parameters = payload.get("parameters")
            start = payload.get("start", False)
            if not isinstance(batch_name, str) or not batch_name.strip():
                raise ValueError("Batch name must be a non-empty string")
            if len(batch_name.strip()) > 120:
                raise ValueError("Batch name must be 120 characters or fewer")
            if not isinstance(parameters, dict):
                raise ValueError("Parameters must be a JSON object")
            if len(parameters) > 200:
                raise ValueError("A run can contain at most 200 parameters")
            if not isinstance(start, bool):
                raise ValueError("Start must be true or false")

            job_id = current_store.enqueue_batch(
                batch_name.strip(), "comsol", [parameters]
            )[0]
            if start:
                summary = _runner(
                    current_store, current_artifact_root, config
                ).run_job(job_id)
                status = HTTPStatus.OK
            else:
                summary = None
                status = HTTPStatus.CREATED
            response: dict[str, Any] = {"job": current_store.get(job_id).to_dict()}
            if summary is not None:
                response["summary"] = _summary_payload(summary)
            self._json(status, response)

        def _read_json(self) -> dict[str, Any]:
            content_type = self.headers.get("Content-Type", "")
            if "application/json" not in content_type.lower():
                raise ValueError("Content-Type must be application/json")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("Invalid Content-Length") from exc
            if length < 1 or length > MAX_REQUEST_BYTES:
                raise ValueError("Request body must be between 1 byte and 64 KiB")
            try:
                payload = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Request body must contain valid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object")
            return payload

        def log_message(self, format: str, *args: object) -> None:
            return None

        def _json(self, status: HTTPStatus, payload: object) -> None:
            self._write(
                status,
                json.dumps(payload, ensure_ascii=False),
                "application/json; charset=utf-8",
            )

        def _write(self, status: HTTPStatus, body: str, content_type: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.daemon_threads = True
    return server


def serve_dashboard(
    database_path: str | Path,
    artifact_root: str | Path,
    host: str,
    port: int,
) -> None:
    server = create_dashboard_server(database_path, artifact_root, host, port)
    actual_port = server.server_address[1]
    print(f"Dashboard: http://{host}:{actual_port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _runner(
    store: JobStore,
    artifact_root: str | Path,
    config: ComsolConfig,
) -> SimulationRunner:
    return SimulationRunner(
        store=store,
        artifact_root=artifact_root,
        adapters=[MockElectromagneticAdapter(), ComsolAdapter(config)],
        notifier=notifier_from_environment(),
    )


def _config_from_payload(payload: dict[str, Any]) -> ComsolConfig:
    raw = payload.get("connection", payload)
    if not isinstance(raw, dict):
        raise ValueError("Connection must be a JSON object")
    executable = _optional_string(raw.get("executable"), "Executable")
    model_path = _optional_string(raw.get("model_path"), "Model path")
    if not executable:
        executable = os.getenv("COMSOL_EXECUTABLE") or str(discover_comsol_executable())
    if not model_path:
        model_path = os.getenv("COMSOL_MODEL_PATH")
    if not model_path:
        raise ValueError("COMSOL model path is required")
    timeout = _optional_positive_int(raw.get("timeout_seconds"), "Timeout")
    if timeout is None:
        timeout = _environment_positive_int("COMSOL_TIMEOUT_SECONDS", 3600)
    cores = _optional_positive_int(raw.get("cores"), "Core count")
    if cores is None and os.getenv("COMSOL_CORES"):
        cores = _environment_positive_int("COMSOL_CORES")
    config = ComsolConfig(
        executable=Path(executable),
        model_path=Path(model_path),
        study_tag=_optional_string(raw.get("study_tag"), "Study tag"),
        job_tag=_optional_string(raw.get("job_tag"), "Job tag"),
        timeout_seconds=timeout,
        cores=cores,
    )
    config.validate()
    return config


def _optional_string(value: Any, label: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value.strip() or None


def _optional_positive_int(value: Any, label: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if parsed < 1:
        raise ValueError(f"{label} must be a positive integer")
    return parsed


def _discovery_payload() -> dict[str, Any]:
    try:
        executable = str(discover_comsol_executable())
    except ValueError:
        executable = None
    configured_model = os.getenv("COMSOL_MODEL_PATH")
    return {
        "executable": executable,
        "model_configured": bool(configured_model),
        "model_filename": Path(configured_model).name if configured_model else None,
        "defaults": {
            "study_tag": os.getenv("COMSOL_STUDY_TAG"),
            "job_tag": os.getenv("COMSOL_JOB_TAG"),
            "timeout_seconds": _environment_positive_int(
                "COMSOL_TIMEOUT_SECONDS", 3600
            ),
            "cores": (
                _environment_positive_int("COMSOL_CORES")
                if os.getenv("COMSOL_CORES")
                else None
            ),
        },
    }


def _environment_positive_int(name: str, default: int | None = None) -> int:
    value = os.getenv(name)
    if not value:
        if default is None:
            raise ValueError(f"Environment variable {name} is required")
        return default
    return _optional_positive_int(value, name) or default or 1


def _summary_payload(summary: Any) -> dict[str, int]:
    return {
        "processed": summary.processed,
        "succeeded": summary.succeeded,
        "failed": summary.failed,
    }


def _require_loopback(host: str) -> None:
    if host.lower() == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(
            "The interactive dashboard must bind to a loopback host"
        ) from exc
    if not address.is_loopback:
        raise ValueError("The interactive dashboard must bind to a loopback host")
