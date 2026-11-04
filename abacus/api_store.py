"""Transactional run persistence backed by SQLite or PostgreSQL."""

from __future__ import annotations

import json
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from abacus.database import (
    ApiRun,
    ApiClient,
    ApiDailyMetric,
    Problem,
    create_database_engine,
    database_session_factory,
    upgrade_database,
)


class RunQuotaExceeded(Exception):
    """Raised when one client exceeds its persisted submission policy."""

    def __init__(self, reason: str, retry_after: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = max(1, retry_after)


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

    def sync_clients(
        self,
        client_policies: dict[str, dict[str, Any]],
        *,
        now: str | datetime,
    ) -> None:
        """Sync nonsecret client roles and limits while retaining historical foreign keys."""
        identifiers = sorted(client_policies)
        if not identifiers or any(not value or len(value) > 64 for value in identifiers):
            raise ValueError("At least one valid API client ID is required.")
        timestamp = self._datetime(now)
        with self._session_factory.begin() as session:
            current = {
                item.client_id: item for item in session.scalars(select(ApiClient)).all()
            }
            for client_id in identifiers:
                policy = client_policies[client_id]
                item = current.get(client_id)
                if item is None:
                    session.add(ApiClient(
                        client_id=client_id,
                        is_active=True,
                        role=policy["role"],
                        daily_run_limit=policy["daily_run_limit"],
                        max_active_runs=policy["max_active_runs"],
                        created_at_utc=timestamp,
                        updated_at_utc=timestamp,
                    ))
                else:
                    item.is_active = True
                    item.role = policy["role"]
                    item.daily_run_limit = policy["daily_run_limit"]
                    item.max_active_runs = policy["max_active_runs"]
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

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            item = session.get(ApiClient, client_id)
            if item is None:
                return None
            return {
                "client_id": item.client_id,
                "is_active": item.is_active,
                "role": item.role,
                "daily_run_limit": item.daily_run_limit,
                "max_active_runs": item.max_active_runs,
            }

    def list_clients(self, *, now: str | datetime) -> list[dict[str, Any]]:
        timestamp = self._datetime(now)
        day_start = datetime.combine(timestamp.date(), datetime_time.min, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        with self._session_factory() as session:
            clients = session.scalars(select(ApiClient).order_by(ApiClient.client_id)).all()
            summaries = session.execute(
                select(
                    ApiRun.client_id,
                    func.sum(case((
                        (ApiRun.created_at_utc >= day_start)
                        & (ApiRun.created_at_utc < day_end), 1,
                    ), else_=0)).label("runs_today"),
                    func.sum(case((ApiRun.state.in_(("queued", "running")), 1), else_=0)).label("active_runs"),
                )
                .group_by(ApiRun.client_id)
            ).all()
            usage = {row.client_id: (row.runs_today or 0, row.active_runs or 0) for row in summaries}
            return [
                {
                    "client_id": item.client_id,
                    "is_active": item.is_active,
                    "role": item.role,
                    "daily_run_limit": item.daily_run_limit,
                    "max_active_runs": item.max_active_runs,
                    "runs_today": usage.get(item.client_id, (0, 0))[0],
                    "active_runs": usage.get(item.client_id, (0, 0))[1],
                }
                for item in clients
            ]

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
        """Atomically enforce client quotas and reserve one idempotent run."""
        identifier = UUID(run_id)
        timestamp = self._datetime(now)
        day_start = datetime.combine(timestamp.date(), datetime_time.min, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
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
        with self._session_factory.begin() as session:
            if self.engine.dialect.name == "postgresql":
                client = session.scalar(
                    select(ApiClient)
                    .where(ApiClient.client_id == client_id, ApiClient.is_active.is_(True))
                    .with_for_update()
                )
            else:
                # SQLite serializes writers; this no-op UPDATE acquires its write lock before
                # reading quotas, preventing simultaneous requests from overshooting limits.
                session.execute(
                    update(ApiClient)
                    .where(ApiClient.client_id == client_id, ApiClient.is_active.is_(True))
                    .values(updated_at_utc=ApiClient.updated_at_utc)
                )
                client = session.scalar(
                    select(ApiClient).where(
                        ApiClient.client_id == client_id,
                        ApiClient.is_active.is_(True),
                    )
                )
            if client is None:
                raise RuntimeError("Configured API client is not active in the database.")

            existing = session.scalar(select(ApiRun).where(
                ApiRun.client_id == client_id,
                ApiRun.idempotency_hash == idempotency_hash,
            ))
            if existing is not None:
                item = self._row_dict(existing)
                assert item is not None
                return item, False

            daily_count = session.scalar(
                select(func.count())
                .select_from(ApiRun)
                .where(
                    ApiRun.client_id == client_id,
                    ApiRun.created_at_utc >= day_start,
                    ApiRun.created_at_utc < day_end,
                )
            ) or 0
            if daily_count >= client.daily_run_limit:
                seconds_to_reset = int((day_end - timestamp).total_seconds())
                raise RunQuotaExceeded("daily_run_limit", seconds_to_reset)

            active_count = session.scalar(
                select(func.count())
                .select_from(ApiRun)
                .where(
                    ApiRun.client_id == client_id,
                    ApiRun.state.in_(("queued", "running")),
                )
            ) or 0
            if active_count >= client.max_active_runs:
                raise RunQuotaExceeded("max_active_runs", 5)

            insert_statement = insert_statement.on_conflict_do_nothing(
                index_elements=[ApiRun.client_id, ApiRun.idempotency_hash]
            )
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

    def record_http_request(self, *, status_code: int, duration_seconds: float, now: datetime) -> None:
        """Atomically add a request to the durable UTC-day aggregate."""
        timestamp = self._datetime(now)
        duration_microseconds = max(0, round(duration_seconds * 1_000_000))
        is_client_error = 1 if 400 <= status_code < 500 else 0
        is_server_error = 1 if status_code >= 500 else 0
        values = {
            "metric_date": timestamp.date(),
            "requests_total": 1,
            "requests_4xx_total": is_client_error,
            "requests_5xx_total": is_server_error,
            "request_duration_microseconds": duration_microseconds,
        }
        if self.engine.dialect.name == "sqlite":
            insert_statement = sqlite_insert(ApiDailyMetric).values(**values)
        elif self.engine.dialect.name == "postgresql":
            insert_statement = postgresql_insert(ApiDailyMetric).values(**values)
        else:
            raise RuntimeError(f"Unsupported database dialect: {self.engine.dialect.name}")
        insert_statement = insert_statement.on_conflict_do_update(
            index_elements=[ApiDailyMetric.metric_date],
            set_={
                "requests_total": ApiDailyMetric.requests_total + insert_statement.excluded.requests_total,
                "requests_4xx_total": ApiDailyMetric.requests_4xx_total + insert_statement.excluded.requests_4xx_total,
                "requests_5xx_total": ApiDailyMetric.requests_5xx_total + insert_statement.excluded.requests_5xx_total,
                "request_duration_microseconds": (
                    ApiDailyMetric.request_duration_microseconds
                    + insert_statement.excluded.request_duration_microseconds
                ),
            },
        )
        with self._session_factory.begin() as session:
            session.execute(insert_statement)

    def get_http_metrics(self) -> dict[str, int | float]:
        with self._session_factory() as session:
            values = session.execute(select(
                func.coalesce(func.sum(ApiDailyMetric.requests_total), 0),
                func.coalesce(func.sum(ApiDailyMetric.requests_4xx_total), 0),
                func.coalesce(func.sum(ApiDailyMetric.requests_5xx_total), 0),
                func.coalesce(func.sum(ApiDailyMetric.request_duration_microseconds), 0),
            )).one()
            return {
                "requests_total": int(values[0]),
                "requests_4xx_total": int(values[1]),
                "requests_5xx_total": int(values[2]),
                "request_duration_seconds_sum": int(values[3]) / 1_000_000,
            }

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
