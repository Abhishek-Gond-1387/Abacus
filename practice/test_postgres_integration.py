"""Live PostgreSQL migration, integrity, concurrency, and API checks.

Set ABACUS_TEST_POSTGRES_URL to a disposable PostgreSQL database before running
this module. The GitHub Actions postgres-integration job supplies that database.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from abacus.api import create_app
from abacus.api_store import RunStore


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
        self.assertIn("uq_api_runs_idempotency_hash", constraints)
        self.assertIn("ck_api_runs_lifecycle_shape", constraints)
        self.assertIn("fk_api_runs_problem_id_problems", constraints)

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
