"""SQLAlchemy schema and database URL helpers for Abacus persistence."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
    create_engine,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_STATES = ("queued", "running", "finished", "failed", "interrupted")
RUN_STATUSES = ("complete", "partial", "error")
OUTCOMES = ("REFUTED", "TESTS_PASSED", "PROVEN", "UNRESOLVED", "ERROR")
RUN_RECORD_TYPE = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Problem(Base):
    """Stable problem identity used as a foreign-key target for runs."""

    __tablename__ = "problems"

    problem_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at_utc: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_utc: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiRun(Base):
    """Mutable lifecycle row plus one immutable, versioned evidence snapshot."""

    __tablename__ = "api_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_hash", name="uq_api_runs_idempotency_hash"),
        CheckConstraint(
            "state IN ('queued', 'running', 'finished', 'failed', 'interrupted')",
            name="ck_api_runs_state",
        ),
        CheckConstraint(
            "length(idempotency_hash) = 64",
            name="ck_api_runs_idempotency_hash_length",
        ),
        CheckConstraint(
            "(state IN ('queued', 'running') AND error_category IS NULL "
            "AND finished_at_utc IS NULL AND record_json IS NULL) "
            "OR (state = 'finished' AND error_category IS NULL "
            "AND finished_at_utc IS NOT NULL AND record_json IS NOT NULL) "
            "OR (state IN ('failed', 'interrupted') AND error_category IS NOT NULL "
            "AND finished_at_utc IS NOT NULL AND record_json IS NULL)",
            name="ck_api_runs_lifecycle_shape",
        ),
        CheckConstraint(
            "updated_at_utc >= created_at_utc AND "
            "(finished_at_utc IS NULL OR finished_at_utc >= created_at_utc)",
            name="ck_api_runs_timestamp_order",
        ),
        Index("ix_api_runs_created_at_utc", "created_at_utc"),
        Index("ix_api_runs_state_updated_at_utc", "state", "updated_at_utc"),
    )

    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    problem_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "problems.problem_id",
            ondelete="RESTRICT",
            name="fk_api_runs_problem_id_problems",
        ),
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    error_category: Mapped[str | None] = mapped_column(String(64))
    created_at_utc: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at_utc: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at_utc: Mapped[Any | None] = mapped_column(DateTime(timezone=True))
    record_json: Mapped[dict[str, Any] | None] = mapped_column(RUN_RECORD_TYPE)


def sqlite_url(path: str | Path) -> str:
    """Build a SQLAlchemy SQLite URL that also handles Windows absolute paths."""
    resolved = Path(path).expanduser().resolve()
    return f"sqlite:///{resolved.as_posix()}"


def default_database_url() -> str:
    configured_url = os.getenv("ABACUS_DATABASE_URL")
    if configured_url:
        return configured_url
    configured_path = os.getenv("ABACUS_DATABASE_PATH")
    if configured_path:
        database_path = Path(configured_path).expanduser()
        if not database_path.is_absolute():
            database_path = PROJECT_ROOT / database_path
        return sqlite_url(database_path)
    data_dir = Path(os.getenv("ABACUS_DATA_DIR", PROJECT_ROOT / ".abacus-data"))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    return sqlite_url(data_dir / "abacus.sqlite3")


def create_database_engine(database_url: str) -> Engine:
    sqlite = database_url.startswith("sqlite:")
    if sqlite:
        database_file = make_url(database_url).database
        if database_file and database_file != ":memory:" and not database_file.startswith("file:"):
            Path(database_file).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 10}
        if sqlite else {},
    )
    if sqlite:
        @event.listens_for(engine, "connect")
        def _enable_sqlite_integrity(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 10000")
            cursor.close()
    return engine


def upgrade_database(database_url: str) -> None:
    """Apply reviewed Alembic migrations for the selected database."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def database_session_factory(engine: Engine) -> sessionmaker[Any]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def ping_database(engine: Engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1
