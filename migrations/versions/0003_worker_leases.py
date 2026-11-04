"""Add recoverable worker leases to queued runs."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision = "0003_worker_leases"
down_revision = "0002_scoped_api_clients"
branch_labels = None
depends_on = None


LIFECYCLE_CHECK = (
    "((state = 'queued' AND error_category IS NULL AND finished_at_utc IS NULL "
    "AND record_json IS NULL AND lease_owner IS NULL AND lease_token IS NULL "
    "AND lease_expires_at IS NULL) "
    "OR (state = 'running' AND error_category IS NULL AND finished_at_utc IS NULL "
    "AND record_json IS NULL AND attempt_count >= 1 AND lease_owner IS NOT NULL "
    "AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) "
    "OR (state = 'finished' AND error_category IS NULL "
    "AND finished_at_utc IS NOT NULL AND record_json IS NOT NULL) "
    "OR (state IN ('failed', 'interrupted') AND error_category IS NOT NULL "
    "AND finished_at_utc IS NOT NULL AND record_json IS NULL)) "
    "AND (state IN ('queued', 'running') OR (lease_owner IS NULL AND "
    "lease_token IS NULL AND lease_expires_at IS NULL))"
)


def upgrade() -> None:
    # A running evaluation from the pre-lease API cannot safely be resumed.
    runs = sa.table(
        "api_runs",
        sa.column("state", sa.String()),
        sa.column("error_category", sa.String()),
        sa.column("created_at_utc", sa.DateTime(timezone=True)),
        sa.column("updated_at_utc", sa.DateTime(timezone=True)),
        sa.column("finished_at_utc", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    transition_time = sa.case(
        (runs.c.created_at_utc > now, runs.c.created_at_utc),
        else_=now,
    )
    op.execute(
        sa.update(runs)
        .where(runs.c.state == "running")
        .values(
            state="interrupted",
            error_category="pre_lease_run_interrupted",
            updated_at_utc=transition_time,
            finished_at_utc=transition_time,
        )
    )

    with op.batch_alter_table("api_runs") as batch:
        batch.add_column(sa.Column(
            "attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ))
        batch.add_column(sa.Column("lease_owner", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("lease_token", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column(
            "lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ))

    with op.batch_alter_table("api_runs") as batch:
        batch.drop_constraint("ck_api_runs_lifecycle_shape", type_="check")
        batch.create_check_constraint("ck_api_runs_lifecycle_shape", LIFECYCLE_CHECK)

    op.create_index(
        "ix_api_runs_state_lease_expiry",
        "api_runs",
        ["state", "lease_expires_at"],
    )


def downgrade() -> None:
    with op.batch_alter_table("api_runs") as batch:
        batch.drop_constraint("ck_api_runs_lifecycle_shape", type_="check")
        batch.create_check_constraint(
            "ck_api_runs_lifecycle_shape",
            "(state IN ('queued', 'running') AND error_category IS NULL "
            "AND finished_at_utc IS NULL AND record_json IS NULL) "
            "OR (state = 'finished' AND error_category IS NULL "
            "AND finished_at_utc IS NOT NULL AND record_json IS NOT NULL) "
            "OR (state IN ('failed', 'interrupted') AND error_category IS NOT NULL "
            "AND finished_at_utc IS NOT NULL AND record_json IS NULL)",
        )
    op.drop_index("ix_api_runs_state_lease_expiry", table_name="api_runs")
    with op.batch_alter_table("api_runs") as batch:
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_token")
        batch.drop_column("lease_owner")
        batch.drop_column("attempt_count")
