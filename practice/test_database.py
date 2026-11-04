"""Database integrity, transaction, and legacy-migration regression checks."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from abacus.api_store import RunStore
from abacus.database import ApiRun, Problem


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _idempotency_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _write_legacy_database(
    path: Path,
    *,
    run_id: str,
    record: dict[str, object],
    stored_outcome: str = "TESTS_PASSED",
) -> None:
    timestamp = _now()
    with closing(sqlite3.connect(path)) as connection:
        with connection:
            connection.executescript(
                """
                CREATE TABLE api_runs (
                    run_id TEXT PRIMARY KEY,
                    problem_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    idempotency_hash TEXT NOT NULL UNIQUE,
                    outcome TEXT,
                    run_status TEXT,
                    error_category TEXT,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    finished_at_utc TEXT,
                    record_json TEXT
                );
                CREATE INDEX api_runs_created_at_idx ON api_runs(created_at_utc DESC);
                """
            )
            connection.execute(
                """
                INSERT INTO api_runs (
                    run_id, problem_id, state, idempotency_hash, outcome, run_status,
                    error_category, created_at_utc, updated_at_utc, finished_at_utc, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, "p01_true_sort", "finished", _idempotency_hash("legacy-key"),
                    stored_outcome, "complete", None, timestamp, timestamp, timestamp,
                    json.dumps(record),
                ),
            )


class DatabaseIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary.name) / "abacus.sqlite3"
        self.store = RunStore(self.database_path)
        self.store.initialize()
        self.store.sync_problems(["p01_true_sort"], now=_now())

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_idempotency_conflict_returns_original_run_atomically(self) -> None:
        key_hash = _idempotency_hash("same-request-key")
        first_id = str(uuid4())
        second_id = str(uuid4())
        first, created = self.store.reserve_run(
            run_id=first_id,
            problem_id="p01_true_sort",
            idempotency_hash=key_hash,
            now=_now(),
        )
        duplicate, duplicate_created = self.store.reserve_run(
            run_id=second_id,
            problem_id="p01_true_sort",
            idempotency_hash=key_hash,
            now=_now(),
        )

        self.assertTrue(created)
        self.assertFalse(duplicate_created)
        self.assertEqual(duplicate["run_id"], first["run_id"])
        self.assertEqual(duplicate["state"], "queued")

    def test_concurrent_retries_create_only_one_run_row(self) -> None:
        key_hash = _idempotency_hash("parallel-idempotency-key")

        def reserve(index: int):
            return self.store.reserve_run(
                run_id=str(uuid4()),
                problem_id="p01_true_sort",
                idempotency_hash=key_hash,
                now=_now(),
            )

        with ThreadPoolExecutor(max_workers=8) as workers:
            results = list(workers.map(reserve, range(8)))

        self.assertEqual(sum(created for _, created in results), 1)
        self.assertEqual(len({row["run_id"] for row, _ in results}), 1)

    def test_lifecycle_transitions_and_json_record_round_trip(self) -> None:
        run_id = str(uuid4())
        self.store.reserve_run(
            run_id=run_id,
            problem_id="p01_true_sort",
            idempotency_hash=_idempotency_hash("finish-run-key"),
            now=_now(),
        )
        self.store.mark_running(run_id, now=_now())
        record = {
            "run_id": run_id,
            "run_status": "complete",
            "outcome": {"outcome": "TESTS_PASSED", "test_count": 10},
        }
        self.store.finish_run(run_id, record, now=_now())

        saved = self.store.get_run(run_id)
        self.assertEqual(saved["state"], "finished")
        self.assertEqual(saved["record"], record)
        self.assertIsNotNone(saved["finished_at_utc"])
        with self.assertRaisesRegex(RuntimeError, "not queued"):
            self.store.mark_running(run_id, now=_now())

    def test_worker_leases_recover_expired_work_and_reject_stale_workers(self) -> None:
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        run_id = str(uuid4())
        self.store.reserve_run(
            run_id=run_id,
            problem_id="p01_true_sort",
            idempotency_hash=_idempotency_hash("worker-lease-key"),
            now=started,
        )
        first_claim = self.store.claim_next_run(
            worker_id="worker-a", now=started, lease_seconds=10,
        )
        self.assertIsNotNone(first_claim)
        first_row, first_token = first_claim
        self.assertEqual(first_row["attempt_count"], 1)

        requeued, interrupted = self.store.recover_expired_leases(
            now=started + timedelta(seconds=11),
        )
        self.assertEqual((requeued, interrupted), (1, 0))
        second_claim = self.store.claim_next_run(
            worker_id="worker-b", now=started + timedelta(seconds=12), lease_seconds=30,
        )
        self.assertIsNotNone(second_claim)
        second_row, second_token = second_claim
        self.assertEqual(second_row["attempt_count"], 2)

        record = {
            "run_id": run_id,
            "run_status": "complete",
            "outcome": {"outcome": "TESTS_PASSED"},
        }
        with self.assertRaisesRegex(RuntimeError, "not running"):
            self.store.finish_run(
                run_id,
                record,
                now=started + timedelta(seconds=13),
                lease_token=first_token,
            )
        self.store.finish_run(
            run_id,
            record,
            now=started + timedelta(seconds=13),
            lease_token=second_token,
        )
        self.assertEqual(self.store.get_run(run_id)["state"], "finished")

    def test_foreign_key_and_lifecycle_checks_reject_anomalous_rows(self) -> None:
        with self.assertRaises(IntegrityError):
            self.store.reserve_run(
                run_id=str(uuid4()),
                problem_id="unknown-problem",
                idempotency_hash=_idempotency_hash("missing-problem-key"),
                now=_now(),
            )

        run_id = str(uuid4())
        self.store.reserve_run(
            run_id=run_id,
            problem_id="p01_true_sort",
            idempotency_hash=_idempotency_hash("invalid-state-key"),
            now=_now(),
        )
        with self.assertRaises(IntegrityError):
            with self.store.engine.begin() as connection:
                connection.execute(
                    ApiRun.__table__.update()
                    .where(ApiRun.run_id == UUID(run_id))
                    .values(state="finished")
                )

        self.assertEqual(self.store.get_run(run_id)["state"], "queued")
        with self.assertRaises(IntegrityError):
            with self.store.engine.begin() as connection:
                connection.execute(delete(Problem).where(Problem.problem_id == "p01_true_sort"))

    def test_database_rejects_updated_timestamp_before_creation(self) -> None:
        run_id = str(uuid4())
        self.store.reserve_run(
            run_id=run_id,
            problem_id="p01_true_sort",
            idempotency_hash=_idempotency_hash("bad-timestamp-order"),
            now="2026-01-01T00:00:00+00:00",
        )
        with self.assertRaises(IntegrityError):
            with self.store.engine.begin() as connection:
                connection.execute(
                    ApiRun.__table__.update()
                    .where(ApiRun.run_id == UUID(run_id))
                    .values(updated_at_utc=datetime(2025, 12, 31, tzinfo=timezone.utc))
                )

    def test_postgresql_schema_uses_native_uuid_jsonb_and_constraints(self) -> None:
        ddl = str(CreateTable(ApiRun.__table__).compile(dialect=postgresql.dialect()))
        self.assertIn("UUID", ddl)
        self.assertIn("JSONB", ddl)
        self.assertIn("FOREIGN KEY(problem_id) REFERENCES problems", ddl)
        self.assertIn("uq_api_runs_client_idempotency_hash", ddl)
        self.assertIn("ck_api_runs_lifecycle_shape", ddl)

    def test_legacy_sqlite_migration_preserves_runs_and_adds_foreign_keys(self) -> None:
        legacy_path = Path(self.temporary.name) / "legacy.sqlite3"
        run_id = str(uuid4())
        record = {
            "run_id": run_id,
            "run_status": "complete",
            "outcome": {"outcome": "TESTS_PASSED"},
        }
        _write_legacy_database(legacy_path, run_id=run_id, record=record)

        migrated = RunStore(legacy_path)
        try:
            migrated.initialize()
            saved = migrated.get_run(run_id)
            self.assertEqual(saved["state"], "finished")
            self.assertEqual(saved["record"], record)
            with migrated._session_factory() as session:
                problem = session.get(Problem, "p01_true_sort")
                self.assertIsNotNone(problem)
                self.assertTrue(problem.is_active)
            with migrated.engine.connect() as connection:
                self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_key_check").all(), [])
        finally:
            migrated.close()

    def test_inconsistent_legacy_row_is_rejected_before_table_rename(self) -> None:
        legacy_path = Path(self.temporary.name) / "inconsistent.sqlite3"
        run_id = str(uuid4())
        record = {
            "run_id": run_id,
            "run_status": "complete",
            "outcome": {"outcome": "TESTS_PASSED"},
        }
        _write_legacy_database(
            legacy_path,
            run_id=run_id,
            record=record,
            stored_outcome="REFUTED",
        )
        migrated = RunStore(legacy_path)
        try:
            with self.assertRaisesRegex(ValueError, "inconsistent summary"):
                migrated.initialize()
        finally:
            migrated.close()
        with closing(sqlite3.connect(legacy_path)) as connection:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("api_runs", tables)
        self.assertNotIn("api_runs_legacy_migration", tables)


if __name__ == "__main__":
    unittest.main()
