"""provider health, immutable snapshots and observation revisions

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08

Connector operations need four things the Phase 1 schema did not record:

* ``provider_health_checks`` is an append-only health log, distinct from an
  ingestion run (a config check makes no provider call).
* ``provider_snapshots`` archives the normalised payload of each run so a
  provider correction cannot silently rewrite history.
* ``trend_observations.revision`` / ``updated_at`` record when a provider
  revised a value for the same natural key.
* ``ingestion_runs.records_updated`` separates updates from inserts.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("data_sources", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "health_status",
                sa.String(length=20),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.add_column(
            sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("last_health_latency_ms", sa.Integer(), nullable=True))

    with op.batch_alter_table("ingestion_runs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "records_updated", sa.Integer(), nullable=False, server_default="0"
            )
        )

    with op.batch_alter_table("trend_observations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "provider_health_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("live", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="unknown"),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_health_source_checked",
        "provider_health_checks",
        ["source_id", "checked_at"],
    )

    op.create_table(
        "provider_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("listing_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attribution", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"], ["ingestion_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_snapshots_source_fetched",
        "provider_snapshots",
        ["source_id", "fetched_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_snapshots_source_fetched", table_name="provider_snapshots")
    op.drop_table("provider_snapshots")
    op.drop_index("ix_health_source_checked", table_name="provider_health_checks")
    op.drop_table("provider_health_checks")

    with op.batch_alter_table("trend_observations", schema=None) as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("revision")

    with op.batch_alter_table("ingestion_runs", schema=None) as batch_op:
        batch_op.drop_column("records_updated")

    with op.batch_alter_table("data_sources", schema=None) as batch_op:
        batch_op.drop_column("last_health_latency_ms")
        batch_op.drop_column("last_health_check_at")
        batch_op.drop_column("health_status")
