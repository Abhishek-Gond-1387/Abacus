"""Transactional run persistence backed by SQLite or PostgreSQL."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from abacus.database import (
    ApiRun,
    ApiClient,
    Problem,
    create_database_engine,
    database_session_factory,
    upgrade_database,
)


class RunStore:
    """Persist normalized run lifecycle data and a validated JSON evidence snapshot."""

    def __init__(self, database_url: str | Path) -> None:
        value = str(database_url)
        if "://" not in value:
            from abacus.database import sqlite_url

            value = sqlite_url(value)
        self.database_url = value
        self.engine: Engine = create_database_engine(value)
        self._session_factory = database_session_factory(self.engine)

    @staticmethod
    def _datetime(value: str | datetime) -> datetime:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Database timestamps must include a UTC offset.")
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def _row_dict(cls, row: ApiRun | None) -> dict[str, Any] | None:
        if row is None:
            return None
        record = row.record_json
        record_outcome = record.get("outcome") if type(record) is dict else None
        return {
            "run_id": str(row.run_id),
            "client_id": row.client_id,
            "problem_id": row.problem_id,
            "state": row.state,
            "idempotency_hash": row.idempotency_hash,
            "outcome": record_outcome.get("outcome")
            if type(record_outcome) is dict else None,
            "run_status": record.get("run_status") if type(record) is dict else None,
            "error_category": row.error_category,
            "created_at_utc": cls._timestamp(row.created_at_utc),
            "updated_at_utc": cls._timestamp(row.updated_at_utc),
            "finished_at_utc": cls._timestamp(row.finished_at_utc)
            if row.finished_at_utc is not None else None,
            "attempt_count": row.attempt_count,
            "lease_owner": row.lease_owner,
            "lease_expires_at": cls._timestamp(row.lease_expires_at)
            if row.lease_expires_at is not None else None,
            "record": record,
        }

    def initialize(self) -> None:
        """Upgrade the database to the reviewed schema before serving requests."""
        upgrade_database(self.database_url)

    def close(self) -> None:
        self.engine.dispose()

    def sync_clients(self, client_ids: list[str], *, now: str | datetime) -> None:
        """Activate configured client identities while retaining historical foreign keys."""
        identifiers = sorted(set(client_ids))
        if not identifiers or any(not value or len(value) > 64 for value in identifiers):
            raise ValueError("At least one valid API client ID is required.")
        timestamp = self._datetime(now)
        with self._session_factory.begin() as session:
            current = {
                item.client_id: item for item in session.scalars(select(ApiClient)).all()
            }
            for client_id in identifiers:
                item = current.get(client_id)
                if item is None:
                    session.add(ApiClient(
                        client_id=client_id,
                        is_active=True,
                        created_at_utc=timestamp,
                        updated_at_utc=timestamp,
                    ))
                else:
                    item.is_active = True
                    item.updated_at_utc = timestamp
            inactive_ids = set(current) - set(identifiers)
            if inactive_ids:
                session.execute(
                    update(ApiClient)
                    .where(ApiClient.client_id.in_(inactive_ids))
                    .values(is_active=False, updated_at_utc=timestamp)
                )

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            return connection.exec_driver_sql("SELECT 1").scalar_one() == 1

    def is_client_active(self, client_id: str) -> bool:
        with self._session_factory() as session:
            active = session.scalar(
                select(ApiClient.is_active).where(ApiClient.client_id == client_id)
            )
            return active is True

    def sync_problems(self, problem_ids: list[str], *, now: str | datetime) -> None:
        """Atomically publish the active problem allowlist and retain historical FK rows."""
        identifiers = sorted(set(problem_ids))
        timestamp = self._datetime(now)
        with self._session_factory.begin() as session:
            current = {
                item.problem_id: item
                for item in session.scalars(select(Problem)).all()
            }
            for problem_id in identifiers:
                item = current.get(problem_id)
                if item is None:
                    session.add(Problem(
                        problem_id=problem_id,
                        is_active=True,
                        created_at_utc=timestamp,
                        updated_at_utc=timestamp,
                    ))
                else:
                    item.is_active = True
                    item.updated_at_utc = timestamp
            inactive_ids = set(current) - set(identifiers)
            if inactive_ids:
                session.execute(
                    update(Problem)
                    .where(Problem.problem_id.in_(inactive_ids))
                    .values(is_active=False, updated_at_utc=timestamp)
                )

    def reserve_run(
        self,
        *,
        run_id: str,
        client_id: str = "default",
        problem_id: str,
        idempotency_hash: str,
        now: str | datetime,
    ) -> tuple[dict[str, Any], bool]:
        """Insert once under concurrent retries, returning the row that owns the key."""
        identifier = UUID(run_id)
        timestamp = self._datetime(now)
        values = {
            "run_id": identifier,
            "client_id": client_id,
            "problem_id": problem_id,
            "state": "queued",
            "idempotency_hash": idempotency_hash,
            "created_at_utc": timestamp,
            "updated_at_utc": timestamp,
        }
        if self.engine.dialect.name == "sqlite":
            insert_statement = sqlite_insert(ApiRun).values(**values)
        elif self.engine.dialect.name == "postgresql":
            insert_statement = postgresql_insert(ApiRun).values(**values)
        else:
            raise RuntimeError(f"Unsupported database dialect: {self.engine.dialect.name}")
        insert_statement = insert_statement.on_conflict_do_nothing(
            index_elements=[ApiRun.client_id, ApiRun.idempotency_hash]
        )

        with self._session_factory.begin() as session:
            inserted_run_id = session.execute(
                insert_statement.returning(ApiRun.run_id)
            ).scalar_one_or_none()
            row = session.scalar(
                select(ApiRun).where(
                    ApiRun.client_id == client_id,
                    ApiRun.idempotency_hash == idempotency_hash,
                )
            )
            if row is None:
                raise RuntimeError("Run insert did not produce or find an idempotency row.")
            item = self._row_dict(row)
            assert item is not None
            return item, inserted_run_id is not None

    def get_run(self, run_id: str, *, client_id: str = "default") -> dict[str, Any] | None:
        with self._session_factory() as session:
            row = session.scalar(select(ApiRun).where(
                ApiRun.run_id == UUID(run_id), ApiRun.client_id == client_id,
            ))
            return self._row_dict(row)

    def mark_running(
        self,
        run_id: str,
        *,
        now: str | datetime,
        lease_owner: str = "inline-api",
        lease_seconds: int = 86_400,
    ) -> str:
        timestamp = self._datetime(now)
        token = uuid4()
        with self._session_factory.begin() as session:
            result = session.execute(
                update(ApiRun)
                .where(ApiRun.run_id == UUID(run_id), ApiRun.state == "queued")
                .values(
                    state="running",
                    lease_owner=lease_owner[:128],
                    lease_token=token,
                    lease_expires_at=timestamp + timedelta(seconds=lease_seconds),
                    attempt_count=ApiRun.attempt_count + 1,
                    updated_at_utc=timestamp,
                )
            )
            if result.rowcount != 1:
                raise RuntimeError("Run is not queued and cannot transition to running.")
        return str(token)

    def claim_next_run(
        self,
        *,
        worker_id: str,
        now: str | datetime,
        lease_seconds: int = 90,
    ) -> tuple[dict[str, Any], str] | None:
        """Atomically lease the oldest queued run; PostgreSQL workers skip locked rows."""
        if not worker_id or lease_seconds < 1:
            raise ValueError("worker_id and positive lease_seconds are required.")
        timestamp = self._datetime(now)
        token = uuid4()
        with self._session_factory.begin() as session:
            candidate_query = (
                select(ApiRun.run_id)
                .where(ApiRun.state == "queued")
                .order_by(ApiRun.created_at_utc, ApiRun.run_id)
                .limit(1)
            )
            if self.engine.dialect.name == "postgresql":
                candidate_query = candidate_query.with_for_update(skip_locked=True)
            candidate_id = session.scalar(candidate_query)
            if candidate_id is None:
                return None
            result = session.execute(
                update(ApiRun)
                .where(ApiRun.run_id == candidate_id, ApiRun.state == "queued")
                .values(
                    state="running",
                    lease_owner=worker_id[:128],
                    lease_token=token,
                    lease_expires_at=timestamp + timedelta(seconds=lease_seconds),
                    attempt_count=ApiRun.attempt_count + 1,
                    updated_at_utc=timestamp,
                )
            )
            if result.rowcount != 1:
                return None
            row = session.get(ApiRun, candidate_id)
            item = self._row_dict(row)
            assert item is not None
            return item, str(token)

    def renew_lease(
        self,
        run_id: str,
        *,
        lease_token: str,
        now: str | datetime,
        lease_seconds: int = 90,
    ) -> bool:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive.")
        timestamp = self._datetime(now)
        with self._session_factory.begin() as session:
            result = session.execute(
                update(ApiRun)
                .where(
                    ApiRun.run_id == UUID(run_id),
                    ApiRun.state == "running",
                    ApiRun.lease_token == UUID(lease_token),
                    ApiRun.lease_expires_at > timestamp,
                )
                .values(
                    lease_expires_at=timestamp + timedelta(seconds=lease_seconds),
                    updated_at_utc=timestamp,
                )
            )
            return result.rowcount == 1

    def recover_expired_leases(
        self,
        *,
        now: str | datetime,
        max_attempts: int = 3,
    ) -> tuple[int, int]:
        """Requeue expired work or terminate rows after their final lease expires."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive.")
        timestamp = self._datetime(now)
        with self._session_factory.begin() as session:
            expired = (
                (ApiRun.state == "running")
                & (ApiRun.lease_expires_at <= timestamp)
            )
            exhausted = session.execute(
                update(ApiRun)
                .where(expired, ApiRun.attempt_count >= max_attempts)
                .values(
                    state="interrupted",
                    error_category="worker_lease_expired",
                    finished_at_utc=timestamp,
                    updated_at_utc=timestamp,
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                )
            ).rowcount
            retried = session.execute(
                update(ApiRun)
                .where(expired, ApiRun.attempt_count < max_attempts)
                .values(
                    state="queued",
                    updated_at_utc=timestamp,
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                )
            ).rowcount
            return retried, exhausted

    def finish_run(
        self,
        run_id: str,
        record: dict[str, Any],
        *,
        now: str | datetime,
        lease_token: str | None = None,
    ) -> None:
        if type(record) is not dict or record.get("run_id") != str(UUID(run_id)):
            raise ValueError("Run record ID does not match the reserved run ID.")
        run_status = record.get("run_status")
        outcome = record.get("outcome")
        if run_status not in {"complete", "partial", "error"}:
            raise ValueError("Run record has an unsupported run_status.")
        if type(outcome) is not dict or outcome.get("outcome") not in {
            "REFUTED", "TESTS_PASSED", "PROVEN", "UNRESOLVED", "ERROR",
        }:
            raise ValueError("Run record has an unsupported outcome.")
        json_safe_record = json.loads(json.dumps(
            record, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ))
        timestamp = self._datetime(now)
        with self._session_factory.begin() as session:
            statement = update(ApiRun).where(
                ApiRun.run_id == UUID(run_id), ApiRun.state == "running"
            )
            if lease_token is not None:
                statement = statement.where(
                    ApiRun.lease_token == UUID(lease_token),
                    ApiRun.lease_expires_at > timestamp,
                )
            result = session.execute(statement.values(
                    state="finished",
                    record_json=json_safe_record,
                    updated_at_utc=timestamp,
                    finished_at_utc=timestamp,
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                ))
            if result.rowcount != 1:
                raise RuntimeError("Run row is not running and cannot be finalized.")

    def fail_run(
        self,
        run_id: str,
        *,
        error_category: str,
        now: str | datetime,
        lease_token: str | None = None,
    ) -> None:
        if not error_category or len(error_category) > 64:
            raise ValueError("error_category must contain 1-64 characters.")
        timestamp = self._datetime(now)
        with self._session_factory.begin() as session:
            statement = update(ApiRun).where(
                    ApiRun.run_id == UUID(run_id),
                    ApiRun.state.in_(("queued", "running")),
                )
            if lease_token is not None:
                statement = statement.where(
                    ApiRun.lease_token == UUID(lease_token),
                    ApiRun.lease_expires_at > timestamp,
                )
            result = session.execute(statement.values(
                    state="failed",
                    error_category=error_category,
                    updated_at_utc=timestamp,
                    finished_at_utc=timestamp,
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                ))
            if result.rowcount != 1:
                raise RuntimeError("Run is not nonterminal and cannot be failed.")

    def recover_orphaned_runs(self, *, now: str | datetime) -> int:
        """Mark nonterminal rows interrupted when this single API process starts."""
        timestamp = self._datetime(now)
        with self._session_factory.begin() as session:
            result = session.execute(
                update(ApiRun)
                .where(ApiRun.state.in_(("queued", "running")))
                .values(
                    state="interrupted",
                    error_category="process_interrupted",
                    updated_at_utc=timestamp,
                    finished_at_utc=timestamp,
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                )
            )
            return result.rowcount
