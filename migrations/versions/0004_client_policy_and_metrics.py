"""Add client roles/quotas and durable HTTP metrics."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_client_policy_metrics"
down_revision = "0003_worker_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_clients", sa.Column(
        "role", sa.String(length=16),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_api_clients_role"),
        nullable=False, server_default="admin",
    ))
    op.add_column("api_clients", sa.Column(
        "daily_run_limit", sa.Integer(),
        sa.CheckConstraint(
            "daily_run_limit BETWEEN 1 AND 1000000",
            name="ck_api_clients_daily_run_limit",
        ),
        nullable=False, server_default="100",
    ))
    op.add_column("api_clients", sa.Column(
        "max_active_runs", sa.Integer(),
        sa.CheckConstraint(
            "max_active_runs BETWEEN 1 AND 10000",
            name="ck_api_clients_max_active_runs",
        ),
        nullable=False, server_default="3",
    ))

    op.create_table(
        "api_daily_metrics",
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("requests_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests_4xx_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests_5xx_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "request_duration_microseconds", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.CheckConstraint("requests_total >= 0", name="ck_api_daily_metrics_requests_nonnegative"),
        sa.CheckConstraint("requests_4xx_total >= 0", name="ck_api_daily_metrics_4xx_nonnegative"),
        sa.CheckConstraint("requests_5xx_total >= 0", name="ck_api_daily_metrics_5xx_nonnegative"),
        sa.CheckConstraint(
            "request_duration_microseconds >= 0",
            name="ck_api_daily_metrics_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "requests_4xx_total + requests_5xx_total <= requests_total",
            name="ck_api_daily_metrics_status_counts_valid",
        ),
        sa.PrimaryKeyConstraint("metric_date"),
    )


def downgrade() -> None:
    op.drop_table("api_daily_metrics")
    op.drop_column("api_clients", "max_active_runs")
    op.drop_column("api_clients", "daily_run_limit")
    op.drop_column("api_clients", "role")
