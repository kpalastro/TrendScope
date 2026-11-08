"""free-first source metadata and observation provenance

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08

Adds the fields the free-first data-source specification requires: cost and
usage visibility on ``data_sources``, and full provenance (metric type, period,
source URL, verification and quality) on every ``trend_observations`` row.
Existing rows are backfilled so no observation loses its origin.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("data_sources", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("cost_model", sa.String(length=20), nullable=False, server_default="free")
        )
        batch_op.add_column(
            sa.Column(
                "monthly_cost", sa.Numeric(12, 2), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(
            sa.Column("cost_currency", sa.String(length=3), nullable=False, server_default="AUD")
        )
        batch_op.add_column(sa.Column("request_limit_month", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "requests_used_month", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch_op.add_column(sa.Column("usage_period", sa.String(length=7), nullable=True))
        batch_op.add_column(
            sa.Column(
                "availability", sa.String(length=30), nullable=False, server_default="available"
            )
        )
        batch_op.add_column(sa.Column("availability_reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "usage_rights",
                sa.String(length=40),
                nullable=False,
                server_default="unspecified",
            )
        )
        batch_op.add_column(sa.Column("docs_url", sa.String(length=600), nullable=True))
        batch_op.add_column(sa.Column("terms_url", sa.String(length=600), nullable=True))
        batch_op.add_column(
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True)
        )

    with op.batch_alter_table("trend_observations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "metric_type",
                sa.String(length=30),
                nullable=False,
                server_default="search_interest",
            )
        )
        batch_op.add_column(sa.Column("provider_name", sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column("period_start", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("period_end", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("source_url", sa.String(length=600), nullable=True))
        batch_op.add_column(
            sa.Column(
                "verification_status",
                sa.String(length=20),
                nullable=False,
                server_default="unverified",
            )
        )
        batch_op.add_column(
            sa.Column(
                "data_quality",
                sa.String(length=20),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.add_column(sa.Column("original_metric", sa.String(length=120), nullable=True))
        batch_op.add_column(
            sa.Column(
                "collected_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )

    # Backfill provenance from data we already hold.
    op.execute(
        """
        UPDATE trend_observations
        SET provider_name = (
            SELECT data_sources.provider_name
            FROM data_sources
            WHERE data_sources.id = trend_observations.source_id
        )
        WHERE provider_name IS NULL
        """
    )
    op.execute(
        """
        UPDATE trend_observations
        SET period_start = observation_date, period_end = observation_date
        WHERE period_start IS NULL
        """
    )
    op.execute(
        """
        UPDATE trend_observations
        SET verification_status = 'synthetic', data_quality = 'synthetic'
        WHERE is_synthetic = true
        """
    )
    op.execute(
        """
        UPDATE trend_observations
        SET collected_at = ingested_at
        WHERE ingested_at IS NOT NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("trend_observations", schema=None) as batch_op:
        batch_op.drop_column("collected_at")
        batch_op.drop_column("original_metric")
        batch_op.drop_column("data_quality")
        batch_op.drop_column("verification_status")
        batch_op.drop_column("source_url")
        batch_op.drop_column("period_end")
        batch_op.drop_column("period_start")
        batch_op.drop_column("provider_name")
        batch_op.drop_column("metric_type")

    with op.batch_alter_table("data_sources", schema=None) as batch_op:
        batch_op.drop_column("last_success_at")
        batch_op.drop_column("terms_url")
        batch_op.drop_column("docs_url")
        batch_op.drop_column("usage_rights")
        batch_op.drop_column("availability_reason")
        batch_op.drop_column("availability")
        batch_op.drop_column("usage_period")
        batch_op.drop_column("requests_used_month")
        batch_op.drop_column("request_limit_month")
        batch_op.drop_column("cost_currency")
        batch_op.drop_column("monthly_cost")
        batch_op.drop_column("cost_model")
