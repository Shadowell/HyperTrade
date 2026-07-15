"""strategy card v2 identity snapshots and decisions

Revision ID: 0019_strategy_card_v2
Revises: 0018_portfolio_lifecycle
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_strategy_card_v2"
down_revision = "0018_portfolio_lifecycle"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _indexes(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "strategy_lineages",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("lineage_key", sa.String(64), nullable=False, unique=True),
        sa.Column("mandate_id", sa.String(32), nullable=False),
        sa.Column("strategy_key", sa.String(128), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    _indexes("strategy_lineages", "lineage_key", "mandate_id", "strategy_key", "created_by")
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("lineage_id", sa.String(32), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("manifest_id", sa.String(32), nullable=False, unique=True),
        sa.Column("manifest_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("strategy_spec_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.UniqueConstraint("lineage_id", "version_number", name="uq_strategy_version_number"),
        *_timestamps(),
    )
    _indexes(
        "strategy_versions",
        "lineage_id",
        "manifest_id",
        "manifest_fingerprint",
        "strategy_spec_hash",
        "created_by",
    )
    op.create_table(
        "strategy_card_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("card_id", sa.String(64), nullable=False),
        sa.Column("lineage_id", sa.String(32), nullable=False),
        sa.Column("version_id", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("lifecycle_status", sa.String(32), nullable=False),
        sa.Column("completeness_score", sa.Numeric(6, 5), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("card_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.UniqueConstraint("version_id", "content_hash", name="uq_strategy_card_content"),
        *_timestamps(),
    )
    _indexes(
        "strategy_card_snapshots",
        "card_id",
        "lineage_id",
        "version_id",
        "schema_version",
        "lifecycle_status",
        "content_hash",
        "created_by",
    )
    op.create_table(
        "strategy_card_lifecycle_decisions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("card_id", sa.String(64), nullable=False),
        sa.Column("lineage_id", sa.String(32), nullable=False),
        sa.Column("version_id", sa.String(32), nullable=False),
        sa.Column("snapshot_id", sa.String(32), nullable=False),
        sa.Column("target_status", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("decided_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "strategy_card_lifecycle_decisions",
        "card_id",
        "lineage_id",
        "version_id",
        "snapshot_id",
        "target_status",
        "decision",
        "request_hash",
        "idempotency_key",
        "decided_by",
    )


def downgrade() -> None:
    op.drop_table("strategy_card_lifecycle_decisions")
    op.drop_table("strategy_card_snapshots")
    op.drop_table("strategy_versions")
    op.drop_table("strategy_lineages")
