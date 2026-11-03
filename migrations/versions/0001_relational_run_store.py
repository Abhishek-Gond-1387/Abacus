"""Create normalized problem/run tables and upgrade the original SQLite store."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.reflection import Inspector


revision = "0001_relational_run_store"
down_revision = None
branch_labels = None
depends_on = None


def _create_problems() -> sa.Table:
    return op.create_table(
        "problems",
        sa.Column("problem_id", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("problem_id"),
    )


def _create_runs() -> sa.Table:
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    return op.create_table(
        "api_runs",
        sa.Column("run_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("problem_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("idempotency_hash", sa.String(length=64), nullable=False),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_json", json_type, nullable=True),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'finished', 'failed', 'interrupted')",
            name="ck_api_runs_state",
        ),
        sa.CheckConstraint(
            "length(idempotency_hash) = 64",
            name="ck_api_runs_idempotency_hash_length",
        ),
        sa.CheckConstraint(
            "(state IN ('queued', 'running') AND error_category IS NULL "
            "AND finished_at_utc IS NULL AND record_json IS NULL) "
            "OR (state = 'finished' AND error_category IS NULL "
            "AND finished_at_utc IS NOT NULL AND record_json IS NOT NULL) "
            "OR (state IN ('failed', 'interrupted') AND error_category IS NOT NULL "
            "AND finished_at_utc IS NOT NULL AND record_json IS NULL)",
            name="ck_api_runs_lifecycle_shape",
        ),
        sa.CheckConstraint(
            "updated_at_utc >= created_at_utc AND "
            "(finished_at_utc IS NULL OR finished_at_utc >= created_at_utc)",
            name="ck_api_runs_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["problem_id"], ["problems.problem_id"],
            name="fk_api_runs_problem_id_problems", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint("idempotency_hash", name="uq_api_runs_idempotency_hash"),
    )


def _parse_datetime(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _legacy_record_value(row: sa.RowMapping) -> dict[str, object] | None:
    raw_record = row["record_json"]
    if raw_record is None:
        return None
    record = json.loads(raw_record) if isinstance(raw_record, str) else raw_record
    if type(record) is not dict:
        raise ValueError(f"Legacy run {row['run_id']} does not contain a JSON object.")
    json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return record


def _legacy_run_to_new(row: sa.RowMapping) -> dict[str, object]:
    run_id = str(UUID(str(row["run_id"])))
    problem_id = row["problem_id"]
    if type(problem_id) is not str or not 1 <= len(problem_id) <= 64:
        raise ValueError(f"Legacy run {run_id} has an invalid problem ID.")
    key_hash = row["idempotency_hash"]
    if type(key_hash) is not str or len(key_hash) != 64 or any(
        character not in "0123456789abcdef" for character in key_hash
    ):
        raise ValueError(f"Legacy run {run_id} has an invalid idempotency digest.")

    state = row["state"]
    created_at = _parse_datetime(row["created_at_utc"])
    updated_at = _parse_datetime(row["updated_at_utc"])
    finished_at = _parse_datetime(row["finished_at_utc"]) if row["finished_at_utc"] else None
    if updated_at < created_at or (finished_at is not None and finished_at < created_at):
        raise ValueError(f"Legacy run {run_id} has out-of-order timestamps.")

    record = _legacy_record_value(row)
    if state == "finished":
        record_outcome = record.get("outcome") if record is not None else None
        valid_status = {"complete", "partial", "error"}
        valid_outcomes = {"REFUTED", "TESTS_PASSED", "PROVEN", "UNRESOLVED", "ERROR"}
        if (
            record is None
            or record.get("run_id") != run_id
            or record.get("run_status") not in valid_status
            or record.get("run_status") != row["run_status"]
            or type(record_outcome) is not dict
            or record_outcome.get("outcome") not in valid_outcomes
            or record_outcome.get("outcome") != row["outcome"]
            or row["error_category"] is not None
            or finished_at is None
        ):
            raise ValueError(f"Legacy run {run_id} has inconsistent summary and evidence fields.")
    elif state in {"queued", "running"}:
        if (
            record is not None
            or row["run_status"] is not None
            or row["outcome"] is not None
            or row["error_category"] is not None
            or finished_at is not None
        ):
            raise ValueError(f"Legacy run {run_id} has an invalid nonterminal shape.")
    elif state in {"failed", "interrupted"}:
        if (
            record is not None
            or row["run_status"] is not None
            or row["outcome"] is not None
            or not row["error_category"]
            or finished_at is None
        ):
            raise ValueError(f"Legacy run {run_id} has an invalid failed shape.")
    else:
        raise ValueError(f"Legacy run {run_id} has an unknown lifecycle state.")

    return {
        "run_id": UUID(run_id),
        "problem_id": problem_id,
        "state": state,
        "idempotency_hash": key_hash,
        "error_category": row["error_category"],
        "created_at_utc": created_at,
        "updated_at_utc": updated_at,
        "finished_at_utc": finished_at,
        "record_json": record,
    }


def _preflight_legacy_runs(table_name: str) -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text(f"SELECT * FROM {table_name}"))
    for row in rows.mappings():
        _legacy_run_to_new(row)


def _copy_legacy_runs(legacy_name: str, run_table: sa.Table) -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text(f"SELECT * FROM {legacy_name} ORDER BY created_at_utc"))
    prepared: list[dict[str, object]] = []
    for row in rows.mappings():
        prepared.append(_legacy_run_to_new(row))
        if len(prepared) >= 500:
            _insert_legacy_batch(connection, prepared, run_table)
            prepared.clear()
    if prepared:
        _insert_legacy_batch(connection, prepared, run_table)


def _insert_legacy_batch(
    connection: sa.Connection,
    prepared: list[dict[str, object]],
    run_table: sa.Table,
) -> None:
    # The parent problem keys must exist before the new table's FK is checked.
    problem_ids = sorted({str(item["problem_id"]) for item in prepared})
    problem_table = sa.Table("problems", sa.MetaData(), autoload_with=connection)
    now = datetime.now(timezone.utc)
    existing = set(connection.execute(
        sa.select(problem_table.c.problem_id).where(problem_table.c.problem_id.in_(problem_ids))
    ).scalars())
    missing = set(problem_ids) - existing
    if missing:
        connection.execute(problem_table.insert(), [
            {
                "problem_id": problem_id,
                "is_active": True,
                "created_at_utc": now,
                "updated_at_utc": now,
            }
            for problem_id in sorted(missing)
        ])
    connection.execute(run_table.insert(), prepared)


def upgrade() -> None:
    connection = op.get_bind()
    inspector: Inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())

    if "api_runs" in tables:
        if "api_runs_legacy_migration" in tables:
            raise RuntimeError("An unfinished database migration table already exists.")
        _preflight_legacy_runs("api_runs")

    if "problems" not in tables:
        problem_table = _create_problems()
    else:
        problem_table = sa.Table("problems", sa.MetaData(), autoload_with=connection)

    if "api_runs" in tables:
        op.rename_table("api_runs", "api_runs_legacy_migration")
        run_table = _create_runs()
        _copy_legacy_runs("api_runs_legacy_migration", run_table)
        op.drop_table("api_runs_legacy_migration")
    else:
        _create_runs()

    op.create_index("ix_api_runs_created_at_utc", "api_runs", ["created_at_utc"])
    op.create_index(
        "ix_api_runs_state_updated_at_utc", "api_runs", ["state", "updated_at_utc"]
    )


def downgrade() -> None:
    op.drop_index("ix_api_runs_state_updated_at_utc", table_name="api_runs")
    op.drop_index("ix_api_runs_created_at_utc", table_name="api_runs")
    op.drop_table("api_runs")
    op.drop_table("problems")
