import http.client
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from simulation_assistant.storage import JobStore
from simulation_assistant.web import create_dashboard_server


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.executable = self.root / "comsolbatch.exe"
        self.executable.write_bytes(b"fake")
        self.model = self.root / "model.mph"
        self.model.write_bytes(b"fake")
        self.checked_model_path: Path | None = None

        def fake_checker(config):
            self.checked_model_path = config.model_path
            return {
                "status": "ok",
                "installed_version": "COMSOL 6.3",
                "model": {
                    "filename": config.model_path.name,
                    "comsol_version": "6.3",
                    "physics": ["Magnetic Fields"],
                    "parameters": {"frequency": "85[kHz]"},
                    "studies": [{"tag": "std1", "label": "Study 1"}],
                },
                "selected_study": "std1",
                "selected_job": None,
                "license_requirements": ["COMSOL", "ACDC"],
            }

        self.server = create_dashboard_server(
            self.root / "jobs.db",
            self.root / "artifacts",
            port=0,
            comsol_checker=fake_checker,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])
        token_match = re.search(r'const API_TOKEN = "([^"]+)"', body)
        self.assertIsNotNone(token_match)
        self.token = token_match.group(1)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None, *, token=None, retry_reset=False):
        attempts = 2 if retry_reset else 1
        for attempt in range(attempts):
            connection = http.client.HTTPConnection(
                "127.0.0.1", self.port, timeout=5
            )
            body = json.dumps(payload) if payload is not None else None
            headers = {}
            if payload is not None:
                headers["Content-Type"] = "application/json"
            if token is not None:
                headers["X-Sim-Assistant-Token"] = token
            try:
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                response_body = response.read().decode("utf-8")
                response_headers = {
                    name.lower(): value for name, value in response.getheaders()
                }
                return response.status, response_headers, response_body
            except ConnectionResetError:
                if attempt + 1 == attempts:
                    raise
            finally:
                connection.close()
        raise AssertionError("Local request retry was exhausted")

    def connection(self):
        return {
            "executable": str(self.executable),
            "model_path": str(self.model),
            "study_tag": "std1",
            "timeout_seconds": 30,
            "cores": 2,
        }

    def test_serves_assistant_workspace(self) -> None:
        status, _, body = self.request("GET", "/")

        self.assertEqual(status, 200)
        self.assertIn("Connect COMSOL", body)
        self.assertIn("Configure a run", body)
        self.assertIn("Run queue", body)
        self.assertNotIn("__API_TOKEN__", body)

    def test_write_actions_require_the_session_token(self) -> None:
        status, _, body = self.request(
            "POST",
            "/api/comsol/check",
            {"connection": self.connection()},
            retry_reset=True,
        )

        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "Invalid session token")

    def test_checks_connection_and_queues_a_run(self) -> None:
        status, _, body = self.request(
            "POST",
            "/api/comsol/check",
            {"connection": self.connection()},
            token=self.token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["model"]["filename"], "model.mph")
        self.assertEqual(self.checked_model_path, self.model)

        status, _, body = self.request(
            "POST",
            "/api/runs",
            {
                "connection": self.connection(),
                "batch_name": "dashboard-test",
                "parameters": {"frequency": "90[kHz]"},
                "output_formulas": {
                    "duration_ratio": (
                        "comsol_duration_seconds / comsol_reported_total_seconds"
                    )
                },
                "start": False,
            },
            token=self.token,
        )
        job = json.loads(body)["job"]
        self.assertEqual(status, 201)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["adapter"], "comsol")
        self.assertEqual(len(job["run_signature"]), 64)
        self.assertEqual(job["run_context"]["model"]["name"], "model.mph")
        self.assertNotIn(str(self.root), json.dumps(job["run_context"]))
        self.assertEqual(
            job["output_formulas"],
            {
                "duration_ratio": (
                    "comsol_duration_seconds / comsol_reported_total_seconds"
                )
            },
        )

    def test_discovery_never_returns_the_full_model_path(self) -> None:
        private_path = str(self.root / "private" / "sensitive-model.mph")
        with patch.dict("os.environ", {"COMSOL_MODEL_PATH": private_path}):
            status, _, body = self.request("GET", "/api/comsol/discovery")

        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["model_configured"])
        self.assertEqual(payload["model_filename"], "sensitive-model.mph")
        self.assertNotIn(private_path, body)

    def test_run_next_reports_a_paused_queue(self) -> None:
        status, _, _ = self.request(
            "POST",
            "/api/runs",
            {
                "connection": self.connection(),
                "batch_name": "paused-dashboard",
                "parameters": {"frequency": "90[kHz]"},
                "start": False,
            },
            token=self.token,
        )
        self.assertEqual(status, 201)
        store = JobStore(self.root / "jobs.db")
        store.set_queue_paused(True)

        status, _, body = self.request(
            "POST",
            "/api/queue/run-next",
            {"connection": self.connection()},
            token=self.token,
        )

        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["processed"], 0)
        self.assertTrue(payload["queue_paused"])

    def test_requests_a_stop_for_a_running_job(self) -> None:
        store = JobStore(self.root / "jobs.db")
        job_id = store.enqueue_batch("active-web", "comsol", [{"x": 1}])[0]
        store.claim(job_id)

        status, _, body = self.request(
            "POST",
            f"/api/jobs/{job_id}/stop",
            {},
            token=self.token,
        )

        payload = json.loads(body)
        self.assertEqual(status, 202)
        self.assertEqual(payload["status"], "running")
        self.assertIsNotNone(payload["stop_requested_at"])

    def test_reports_live_comsol_progress_and_log_tail(self) -> None:
        store = JobStore(self.root / "jobs.db")
        job_id = store.enqueue_batch("active-monitor", "comsol", [{"x": 1}])[0]
        store.claim(job_id)
        artifact_dir = self.root / "artifacts" / f"job-{job_id:06d}"
        artifact_dir.mkdir(parents=True)
        store.record_artifact_dir(job_id, artifact_dir)
        (artifact_dir / "comsol.log").write_text(
            "<---- Stationary Solver 1 ----------------\n"
            "Current Progress:  42 % - Solving linear system\n",
            encoding="utf-8",
        )

        status, _, body = self.request("GET", f"/api/jobs/{job_id}")

        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["progress"]["percent"], 42)
        self.assertEqual(payload["progress"]["stage"], "Solving linear system")
        self.assertIn("Current Progress", payload["progress"]["log_tail"][-1])

        status, _, body = self.request("GET", "/api/jobs")
        listed = json.loads(body)["jobs"][0]
        self.assertEqual(status, 200)
        self.assertEqual(listed["progress"]["summary"], "42% · Solving linear system")
        self.assertEqual(listed["progress"]["log_tail"], [])

    def test_refuses_non_local_bindings(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            create_dashboard_server(
                self.root / "other.db", self.root / "other-artifacts", "0.0.0.0", 0
            )


if __name__ == "__main__":
    unittest.main()
