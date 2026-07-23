"""regime-aware shadow allocation v2

Revision ID: 0039_regime_shadow_v2
Revises: 0038_paper_incubation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_regime_shadow_v2"
down_revision: str | None = "0038_paper_incubation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_regime_snapshots_v2",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(72), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "regime_shadow_targets_v2",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("portfolio_key", sa.String(64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("regime_snapshot_id", sa.String(32), nullable=False),
        sa.Column("cohort_snapshot_id", sa.String(32), nullable=False),
        sa.Column("previous_target_id", sa.String(32), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("target_json", sa.JSON(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "portfolio_key",
            "version_number",
            name="uq_regime_shadow_target_version",
        ),
        sa.UniqueConstraint(
            "portfolio_key",
            "source_hash",
            name="uq_regime_shadow_target_source",
        ),
    )
    for table, columns in {
        "market_regime_snapshots_v2": (
            "as_of",
            "available_at",
            "status",
            "policy_hash",
        ),
        "regime_shadow_targets_v2": (
            "portfolio_key",
            "status",
            "regime_snapshot_id",
            "cohort_snapshot_id",
            "valid_until",
        ),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("regime_shadow_targets_v2")
    op.drop_table("market_regime_snapshots_v2")
