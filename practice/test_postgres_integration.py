"""Live PostgreSQL migration, integrity, concurrency, and API checks.

Set ABACUS_TEST_POSTGRES_URL to a disposable PostgreSQL database before running
this module. The GitHub Actions postgres-integration job supplies that database.
"""

from __future__ import annotations

import os
import secrets
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url

from abacus.api import create_app
from abacus.api_store import RunQuotaExceeded, RunStore


DATABASE_URL = os.getenv("ABACUS_TEST_POSTGRES_URL", "")
TEST_API_KEY = "postgres-integration-test-key-" + ("x" * 32)


@unittest.skipUnless(DATABASE_URL, "Set ABACUS_TEST_POSTGRES_URL to run PostgreSQL integration tests.")
class PostgreSQLIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = RunStore(DATABASE_URL)
        cls.store.initialize()
        cls.store.sync_problems(["p01_true_sort", "p02_false_sort"], now=datetime.now(timezone.utc))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.store.close()

    def test_migration_creates_native_postgresql_types_and_constraints(self) -> None:
        with self.store.engine.connect() as connection:
            columns = connection.execute(text(
                """
                SELECT column_name, udt_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'api_runs'
                  AND column_name IN ('run_id', 'record_json')
                """
            )).all()
            column_types = dict(columns)
            constraints = set(connection.execute(text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'api_runs'::regclass
                """
            )).scalars())

        self.assertEqual(column_types, {"run_id": "uuid", "record_json": "jsonb"})
        self.assertIn("uq_api_runs_client_idempotency_hash", constraints)
        self.assertIn("ck_api_runs_lifecycle_shape", constraints)
        self.assertIn("fk_api_runs_problem_id_problems", constraints)
        with self.store.engine.connect() as connection:
            client_constraints = set(connection.execute(text(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'api_clients'::regclass"
            )).scalars())
            metric_table = connection.execute(text(
                "SELECT to_regclass('api_daily_metrics')"
            )).scalar_one()
        self.assertIn("ck_api_clients_role", client_constraints)
        self.assertIn("ck_api_clients_daily_run_limit", client_constraints)
        self.assertIn("ck_api_clients_max_active_runs", client_constraints)
        self.assertEqual(metric_table, "api_daily_metrics")

    def test_postgresql_client_quotas_and_durable_metrics(self) -> None:
        now = datetime.now(timezone.utc)
        client_id = f"quota-{uuid4().hex[:16]}"
        self.store.sync_clients({
            "default": {
                "role": "admin", "daily_run_limit": 100, "max_active_runs": 3,
            },
            client_id: {
                "role": "member", "daily_run_limit": 2, "max_active_runs": 1,
            },
        }, now=now)
        first_hash = sha256(f"first-{uuid4()}".encode()).hexdigest()
        first, created = self.store.reserve_run(
            run_id=str(uuid4()), client_id=client_id, problem_id="p01_true_sort",
            idempotency_hash=first_hash, now=now,
        )
        self.assertTrue(created)
        with self.assertRaisesRegex(RunQuotaExceeded, "max_active_runs"):
            self.store.reserve_run(
                run_id=str(uuid4()), client_id=client_id, problem_id="p01_true_sort",
                idempotency_hash=sha256(f"second-{uuid4()}".encode()).hexdigest(), now=now,
            )

        before = self.store.get_http_metrics()
        self.store.record_http_request(status_code=200, duration_seconds=0.25, now=now)
        after = self.store.get_http_metrics()
        self.assertEqual(after["requests_total"], before["requests_total"] + 1)
        self.assertAlmostEqual(
            after["request_duration_seconds_sum"],
            before["request_duration_seconds_sum"] + 0.25,
        )
        self.assertEqual(self.store.get_run(first["run_id"], client_id=client_id)["state"], "queued")

    def test_non_superuser_schema_owner_can_migrate_and_write(self) -> None:
        schema = f"runtime_{uuid4().hex[:16]}"
        role = f"runtime_{uuid4().hex[:16]}"
        password = secrets.token_urlsafe(32)
        with self.store.engine.connect() as connection:
            is_superuser = connection.execute(text(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            )).scalar_one()
        if not is_superuser:
            self.skipTest("The disposable integration database user cannot create temporary roles.")

        with self.store.engine.begin() as connection:
            create_role = connection.execute(
                text(
                    "SELECT format("
                    "'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', "
                    "CAST(:role AS text), CAST(:password AS text))"
                ),
                {"role": role, "password": password},
            ).scalar_one()
            connection.exec_driver_sql(create_role)
            create_schema = connection.execute(
                text(
                    "SELECT format('CREATE SCHEMA %I AUTHORIZATION %I', "
                    "CAST(:schema AS text), CAST(:role AS text))"
                ),
                {"schema": schema, "role": role},
            ).scalar_one()
            connection.exec_driver_sql(create_schema)

        base_url = make_url(DATABASE_URL).set(username=role, password=password)
        query = dict(base_url.query)
        query["options"] = f"-c search_path={schema}"
        runtime_database_url = base_url.set(query=query).render_as_string(
            hide_password=False
        )
        runtime_store = RunStore(runtime_database_url)
        try:
            runtime_store.initialize()
            runtime_store.sync_clients({"runtime-client": {
                "role": "admin", "daily_run_limit": 2, "max_active_runs": 1,
            }}, now=datetime.now(timezone.utc))
            runtime_store.sync_problems(["p01_true_sort"], now=datetime.now(timezone.utc))
            row, created = runtime_store.reserve_run(
                run_id=str(uuid4()), client_id="runtime-client", problem_id="p01_true_sort",
                idempotency_hash=sha256(f"runtime-{uuid4()}".encode()).hexdigest(),
                now=datetime.now(timezone.utc),
            )
            self.assertTrue(created)
            self.assertEqual(row["state"], "queued")
        finally:
            runtime_store.close()
            with self.store.engine.begin() as connection:
                drop_schema = connection.execute(
                    text(
                        "SELECT format('DROP SCHEMA IF EXISTS %I CASCADE', "
                        "CAST(:schema AS text))"
                    ),
                    {"schema": schema},
                ).scalar_one()
                connection.exec_driver_sql(drop_schema)
                drop_role = connection.execute(
                    text(
                        "SELECT format('DROP ROLE IF EXISTS %I', CAST(:role AS text))"
                    ),
                    {"role": role},
                ).scalar_one()
                connection.exec_driver_sql(drop_role)

    def test_simultaneous_idempotent_reservations_create_one_row(self) -> None:
        key_hash = sha256(f"postgres-parallel-{uuid4()}".encode()).hexdigest()

        def reserve(_index: int):
            return self.store.reserve_run(
                run_id=str(uuid4()),
                problem_id="p01_true_sort",
                idempotency_hash=key_hash,
                now=datetime.now(timezone.utc),
            )

        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(reserve, range(8)))

        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len({row["run_id"] for row, _ in results}), 1)

    def test_database_rejects_run_with_missing_problem(self) -> None:
        with self.assertRaises(IntegrityError):
            self.store.reserve_run(
                run_id=str(uuid4()),
                problem_id="p-missing-from-registry",
                idempotency_hash=sha256(f"missing-problem-{uuid4()}".encode()).hexdigest(),
                now=datetime.now(timezone.utc),
            )

    def test_http_api_runs_and_retrieves_real_evidence_using_postgresql(self) -> None:
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(
                data_dir=data_dir,
                database_url=DATABASE_URL,
                api_key_reader=lambda: TEST_API_KEY,
            )
            headers = {
                "X-API-Key": TEST_API_KEY,
                "Idempotency-Key": f"postgres-api-run-{uuid4()}",
            }
            with TestClient(app) as client:
                submitted = client.post(
                    "/v1/runs",
                    json={"problem_id": "p01_true_sort"},
                    headers=headers,
                )
                self.assertEqual(submitted.status_code, 201, submitted.text)

                repeated = client.post(
                    "/v1/runs",
                    json={"problem_id": "p01_true_sort"},
                    headers=headers,
                )
                self.assertEqual(repeated.status_code, 200, repeated.text)
                self.assertEqual(repeated.json()["run_id"], submitted.json()["run_id"])

                fetched = client.get(
                    f"/v1/runs/{submitted.json()['run_id']}",
                    headers={"X-API-Key": TEST_API_KEY},
                )
                self.assertEqual(fetched.status_code, 200, fetched.text)
                self.assertEqual(fetched.json()["state"], "finished")
                self.assertEqual(fetched.json()["record"]["run_status"], "complete")
                self.assertFalse(fetched.json()["record"]["model"]["provider_api_called"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
