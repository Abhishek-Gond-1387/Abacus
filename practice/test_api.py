"""HTTP API authentication, persistence, and idempotency checks."""

from __future__ import annotations

import tempfile
import unittest
import json
import os
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

    def test_clients_can_reuse_idempotency_keys_without_reading_each_others_runs(self) -> None:
        keys = {
            "client-alpha": "alpha-secret-" + ("a" * 40),
            "client-beta": "beta-secret-" + ("b" * 40),
        }
        with patch.dict(os.environ, {
            "ABACUS_CLIENT_API_KEYS": json.dumps(keys),
            "ABACUS_RUN_MODE": "inline",
        }):
            app = create_app(data_dir=self.data_dir / "multi-client")
            with TestClient(app) as client:
                def fake_run_problem(spec, *, runs_dir, run_id):
                    return {
                        "run_id": run_id,
                        "run_status": "complete",
                        "outcome": {"outcome": "TESTS_PASSED"},
                    }

                with patch("abacus.api.run_problem", side_effect=fake_run_problem):
                    first = client.post(
                        "/v1/runs",
                        json={"problem_id": "p01_true_sort"},
                        headers={
                            "X-API-Key": keys["client-alpha"],
                            "Idempotency-Key": "same-idempotency-key-for-all",
                        },
                    )
                    second = client.post(
                        "/v1/runs",
                        json={"problem_id": "p01_true_sort"},
                        headers={
                            "X-API-Key": keys["client-beta"],
                            "Idempotency-Key": "same-idempotency-key-for-all",
                        },
                    )
                self.assertEqual(first.status_code, 201)
                self.assertEqual(second.status_code, 201)
                self.assertNotEqual(first.json()["run_id"], second.json()["run_id"])
                hidden = client.get(
                    f"/v1/runs/{second.json()['run_id']}",
                    headers={"X-API-Key": keys["client-alpha"]},
                )
                visible = client.get(
                    f"/v1/runs/{second.json()['run_id']}",
                    headers={"X-API-Key": keys["client-beta"]},
                )
                self.assertEqual(hidden.status_code, 404)
                self.assertEqual(visible.status_code, 200)

    def test_roles_quotas_and_admin_client_listing(self) -> None:
        keys = {
            "operator": {
                "api_key": "operator-secret-" + ("o" * 40),
                "role": "admin", "daily_run_limit": 10, "max_active_runs": 3,
            },
            "member": {
                "api_key": "member-secret-" + ("m" * 40),
                "role": "member", "daily_run_limit": 5, "max_active_runs": 1,
            },
        }
        with patch.dict(os.environ, {
            "ABACUS_CLIENT_API_KEYS": json.dumps(keys),
            "ABACUS_RUN_MODE": "queue",
        }):
            app = create_app(data_dir=self.data_dir / "roles")
            with TestClient(app) as client:
                admin_headers = {"X-API-Key": keys["operator"]["api_key"]}
                member_headers = {"X-API-Key": keys["member"]["api_key"]}
                denied = client.get("/v1/admin/clients", headers=member_headers)
                self.assertEqual(denied.status_code, 403)

                submitted = client.post(
                    "/v1/runs", json={"problem_id": "p01_true_sort"},
                    headers={**member_headers, "Idempotency-Key": "member-request-key-0001"},
                )
                self.assertEqual(submitted.status_code, 202)
                repeated = client.post(
                    "/v1/runs", json={"problem_id": "p01_true_sort"},
                    headers={**member_headers, "Idempotency-Key": "member-request-key-0001"},
                )
                self.assertEqual(repeated.status_code, 202)
                self.assertEqual(repeated.json()["run_id"], submitted.json()["run_id"])
                limited = client.post(
                    "/v1/runs", json={"problem_id": "p01_true_sort"},
                    headers={**member_headers, "Idempotency-Key": "member-request-key-0002"},
                )
                self.assertEqual(limited.status_code, 429)
                self.assertEqual(limited.json()["detail"]["code"], "max_active_runs")
                self.assertIn("Retry-After", limited.headers)

                listed = client.get("/v1/admin/clients", headers=admin_headers)
                self.assertEqual(listed.status_code, 200, listed.text)
                member = next(item for item in listed.json() if item["client_id"] == "member")
                self.assertEqual(member["role"], "member")
                self.assertEqual(member["daily_run_limit"], 5)
                self.assertEqual(member["max_active_runs"], 1)
                self.assertEqual(member["runs_today"], 1)
                self.assertEqual(member["active_runs"], 1)
                self.assertNotIn(keys["member"]["api_key"], listed.text)

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

    def test_readiness_fails_when_database_ping_fails(self) -> None:
        with patch.object(self.app.state.store, "ping", return_value=False):
            response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "not_ready"})

    def test_startup_marks_previous_process_runs_interrupted(self) -> None:
        data_dir = self.data_dir / "orphaned"
        store = RunStore(data_dir / "abacus.sqlite3")
        store.initialize()
        store.sync_problems(["p01_true_sort"], now=datetime.now(timezone.utc))
        run_id = str(uuid4())
        store.reserve_run(
            run_id=run_id,
            problem_id="p01_true_sort",
            idempotency_hash=sha256(b"previous-process-run-key").hexdigest(),
            now=datetime.now(timezone.utc).isoformat(),
        )
        store.close()

        app = create_app(data_dir=data_dir, api_key_reader=lambda: API_KEY)
        with TestClient(app):
            recovered = app.state.store.get_run(run_id)
        self.assertEqual(recovered["state"], "interrupted")
        self.assertEqual(recovered["error_category"], "process_interrupted")


if __name__ == "__main__":
    unittest.main()
