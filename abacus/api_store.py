"""Small SQLite store for HTTP-submitted Abacus runs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


class RunStore:
    """Persist run lifecycle and result JSON without storing API keys or request bodies."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        if str(self.path) == ":memory:":
            raise ValueError("A persistent file path is required for the API database.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        record_json = item.pop("record_json")
        item["record"] = json.loads(record_json) if record_json else None
        return item

    def initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_runs (
                    run_id TEXT PRIMARY KEY,
                    problem_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'finished', 'failed', 'interrupted')),
                    idempotency_hash TEXT NOT NULL UNIQUE,
                    outcome TEXT,
                    run_status TEXT,
                    error_category TEXT,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    finished_at_utc TEXT,
                    record_json TEXT
                );
                CREATE INDEX IF NOT EXISTS api_runs_created_at_idx
                    ON api_runs(created_at_utc DESC);
                """
            )

    def ping(self) -> bool:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT 1").fetchone()
            return row is not None and row[0] == 1

    def reserve_run(
        self,
        *,
        run_id: str,
        problem_id: str,
        idempotency_hash: str,
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        """Create one queued run, or return the existing request's row atomically."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM api_runs WHERE idempotency_hash = ?",
                (idempotency_hash,),
            ).fetchone()
            if existing is not None:
                connection.commit()
                row = self._row_dict(existing)
                assert row is not None
                return row, False
            connection.execute(
                """
                INSERT INTO api_runs (
                    run_id, problem_id, state, idempotency_hash,
                    created_at_utc, updated_at_utc
                ) VALUES (?, ?, 'queued', ?, ?, ?)
                """,
                (run_id, problem_id, idempotency_hash, now, now),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM api_runs WHERE run_id = ?", (run_id,)).fetchone()
            result = self._row_dict(row)
            assert result is not None
            return result, True

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            return self._row_dict(
                connection.execute("SELECT * FROM api_runs WHERE run_id = ?", (run_id,)).fetchone()
            )

    def mark_running(self, run_id: str, *, now: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE api_runs SET state = 'running', updated_at_utc = ? WHERE run_id = ? AND state = 'queued'",
                (now, run_id),
            )

    def finish_run(self, run_id: str, record: dict[str, Any], *, now: str) -> None:
        output = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE api_runs
                SET state = 'finished', run_status = ?, outcome = ?, record_json = ?,
                    updated_at_utc = ?, finished_at_utc = ?
                WHERE run_id = ? AND state = 'running'
                """,
                (record["run_status"], record["outcome"]["outcome"], output, now, now, run_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Run row was not in the running state.")

    def fail_run(self, run_id: str, *, error_category: str, now: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE api_runs
                SET state = 'failed', error_category = ?, updated_at_utc = ?, finished_at_utc = ?
                WHERE run_id = ? AND state IN ('queued', 'running')
                """,
                (error_category, now, now, run_id),
            )

    def recover_orphaned_runs(self, *, now: str) -> int:
        """Mark all nonterminal runs from the previous process as interrupted at startup."""
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE api_runs
                SET state = 'interrupted', error_category = 'process_interrupted',
                    updated_at_utc = ?, finished_at_utc = ?
                WHERE state IN ('queued', 'running')
                """,
                (now, now),
            )
            return cursor.rowcount
