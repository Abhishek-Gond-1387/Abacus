"""HTTP API authentication, persistence, and idempotency checks."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient

from abacus.api import create_app
from abacus.api_store import RunStore


API_KEY = "test-key-" + ("x" * 40)
IDEMPOTENCY_KEY = "test-run-request-0001"


class ApiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.app = create_app(data_dir=self.data_dir, api_key_reader=lambda: API_KEY)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()
        self.headers = {"X-API-Key": API_KEY}

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_health_is_public_but_data_routes_require_an_api_key(self) -> None:
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(self.client.get("/health/ready").json(), {"status": "ready"})
        self.assertEqual(self.client.get("/v1/problems").status_code, 401)
        self.assertEqual(
            self.client.get("/v1/problems", headers={"X-API-Key": "wrong-key"}).status_code,
            401,
        )

    def test_problem_list_contains_only_current_validated_problems(self) -> None:
        response = self.client.get("/v1/problems", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["problem_id"] for item in response.json()],
            ["p01_true_sort", "p02_false_sort"],
        )

    def test_run_is_persisted_and_idempotent_key_prevents_duplicate_evaluation(self) -> None:
        headers = {**self.headers, "Idempotency-Key": IDEMPOTENCY_KEY}
        calls: list[str] = []

        def fake_run_problem(spec, *, runs_dir, run_id):
            calls.append(spec.problem_id)
            return {
                "run_id": run_id,
                "run_status": "complete",
                "outcome": {"outcome": "TESTS_PASSED"},
                "log_path": str(Path(runs_dir) / "private-host-path.json"),
            }

        with patch("abacus.api.run_problem", side_effect=fake_run_problem):
            first = self.client.post("/v1/runs", json={"problem_id": "p01_true_sort"}, headers=headers)
            second = self.client.post("/v1/runs", json={"problem_id": "p01_true_sort"}, headers=headers)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["run_id"], second.json()["run_id"])
        self.assertEqual(calls, ["p01_true_sort"])
        self.assertNotIn("record", first.json())
        self.assertNotIn("log_path", second.json())

        fetched = self.client.get(f"/v1/runs/{first.json()['run_id']}", headers=self.headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["record"]["outcome"]["outcome"], "TESTS_PASSED")
        self.assertNotIn("log_path", fetched.json()["record"])

    def test_real_request_runs_local_pipeline_without_a_provider_call(self) -> None:
        headers = {**self.headers, "Idempotency-Key": "real-local-run-request-0001"}
        submitted = self.client.post(
            "/v1/runs", json={"problem_id": "p01_true_sort"}, headers=headers,
        )
        self.assertEqual(submitted.status_code, 201)

        fetched = self.client.get(
            f"/v1/runs/{submitted.json()['run_id']}", headers=self.headers,
        )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["record"]["run_status"], "complete")
        self.assertFalse(fetched.json()["record"]["model"]["provider_api_called"])

    def test_idempotency_key_cannot_be_reused_for_another_problem(self) -> None:
        headers = {**self.headers, "Idempotency-Key": IDEMPOTENCY_KEY}

        def fake_run_problem(spec, *, runs_dir, run_id):
            return {
                "run_id": run_id,
                "run_status": "complete",
                "outcome": {"outcome": "TESTS_PASSED"},
            }

        with patch("abacus.api.run_problem", side_effect=fake_run_problem):
            self.assertEqual(
                self.client.post("/v1/runs", json={"problem_id": "p01_true_sort"}, headers=headers).status_code,
                201,
            )
            conflict = self.client.post(
                "/v1/runs", json={"problem_id": "p02_false_sort"}, headers=headers,
            )
        self.assertEqual(conflict.status_code, 409)

    def test_unknown_problem_and_bad_request_shape_are_rejected(self) -> None:
        headers = {**self.headers, "Idempotency-Key": IDEMPOTENCY_KEY}
        unknown = self.client.post("/v1/runs", json={"problem_id": "unknown_problem"}, headers=headers)
        malformed = self.client.post(
            "/v1/runs", json={"problem_id": "p01_true_sort", "target_code": "ignored"}, headers=headers,
        )
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(malformed.status_code, 422)

    def test_metrics_are_authenticated_and_prometheus_formatted(self) -> None:
        self.assertEqual(self.client.get("/metrics").status_code, 401)
        response = self.client.get("/metrics", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("abacus_http_requests_total", response.text)

    def test_readiness_fails_closed_when_api_key_is_not_configured(self) -> None:
        unconfigured = TestClient(create_app(
            data_dir=self.data_dir / "unconfigured",
            api_key_reader=lambda: "",
        ))
        with unconfigured:
            self.assertEqual(unconfigured.get("/health/live").status_code, 200)
            self.assertEqual(unconfigured.get("/health/ready").status_code, 503)

    def test_startup_marks_previous_process_runs_interrupted(self) -> None:
        data_dir = self.data_dir / "orphaned"
        store = RunStore(data_dir / "abacus.sqlite3")
        store.initialize()
        run_id = str(uuid4())
        store.reserve_run(
            run_id=run_id,
            problem_id="p01_true_sort",
            idempotency_hash=sha256(b"previous-process-run-key").hexdigest(),
            now=datetime.now(timezone.utc).isoformat(),
        )

        app = create_app(data_dir=data_dir, api_key_reader=lambda: API_KEY)
        with TestClient(app):
            recovered = app.state.store.get_run(run_id)
        self.assertEqual(recovered["state"], "interrupted")
        self.assertEqual(recovered["error_category"], "process_interrupted")


if __name__ == "__main__":
    unittest.main()
