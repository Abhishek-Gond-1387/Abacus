"""Add stable API client identities and scope idempotency per client."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


revision = "0002_scoped_api_clients"
down_revision = "0001_relational_run_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    clients = op.create_table(
        "api_clients",
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("client_id"),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(clients, [{
        "client_id": "default",
        "is_active": True,
        "created_at_utc": now,
        "updated_at_utc": now,
    }])

    with op.batch_alter_table("api_runs") as batch:
        batch.add_column(sa.Column("client_id", sa.String(length=64), nullable=True))
    op.execute(sa.text("UPDATE api_runs SET client_id = 'default' WHERE client_id IS NULL"))

    with op.batch_alter_table("api_runs") as batch:
        batch.drop_constraint("uq_api_runs_idempotency_hash", type_="unique")
        batch.alter_column(
            "client_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch.create_foreign_key(
            "fk_api_runs_client_id_clients",
            "api_clients",
            ["client_id"],
            ["client_id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_api_runs_client_idempotency_hash",
            ["client_id", "idempotency_hash"],
        )


def downgrade() -> None:
    with op.batch_alter_table("api_runs") as batch:
        batch.drop_constraint("uq_api_runs_client_idempotency_hash", type_="unique")
        batch.drop_constraint("fk_api_runs_client_id_clients", type_="foreignkey")
        batch.drop_column("client_id")
        batch.create_unique_constraint(
            "uq_api_runs_idempotency_hash", ["idempotency_hash"]
        )
    op.drop_table("api_clients")
