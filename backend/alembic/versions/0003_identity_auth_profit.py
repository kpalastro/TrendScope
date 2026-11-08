"""identity, refresh tokens and profit scenarios

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08

Closes the remaining Phase 1 identity/workflow gap:

* ``auth_refresh_tokens`` holds revocable, rotating refresh-token hashes.
* ``product_identifiers`` / ``product_aliases`` / ``product_matches`` provide
  deterministic deduplication keys and a reviewable merge queue.
* ``products.merged_into_product_id`` records a non-destructive merge.
* ``profit_scenarios`` stores the GST-aware calculator snapshots.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.add_column(sa.Column("merged_into_product_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_products_merged_into",
            "products",
            ["merged_into_product_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"], ["auth_refresh_tokens.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_refresh_user_expires", "auth_refresh_tokens", ["user_id", "expires_at"]
    )

    op.create_table(
        "product_identifiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("scheme", sa.String(length=30), nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scheme", "value", name="uq_identifier_scheme_value"),
    )
    op.create_index("ix_identifiers_product", "product_identifiers", ["product_id"])

    op.create_table(
        "product_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=300), nullable=False),
        sa.Column("normalised_alias", sa.String(length=300), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id", "normalised_alias", name="uq_alias_product_normalised"
        ),
    )
    op.create_index("ix_aliases_normalised", "product_aliases", ["normalised_alias"])

    op.create_table(
        "product_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_a_id", sa.Uuid(), nullable=False),
        sa.Column("product_b_id", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("similarity", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_a_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_b_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_a_id", "product_b_id", name="uq_match_pair"),
    )
    op.create_index("ix_matches_status", "product_matches", ["status"])

    op.create_table(
        "profit_scenarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="AUD"),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("assumptions_version", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_profit_scenarios_user", "profit_scenarios", ["user_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_profit_scenarios_user", table_name="profit_scenarios")
    op.drop_table("profit_scenarios")
    op.drop_index("ix_matches_status", table_name="product_matches")
    op.drop_table("product_matches")
    op.drop_index("ix_aliases_normalised", table_name="product_aliases")
    op.drop_table("product_aliases")
    op.drop_index("ix_identifiers_product", table_name="product_identifiers")
    op.drop_table("product_identifiers")
    op.drop_index("ix_refresh_user_expires", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.drop_constraint("fk_products_merged_into", type_="foreignkey")
        batch_op.drop_column("merged_into_product_id")
