"""bounded portfolio observation window summaries

Revision ID: 0020_portfolio_windows
Revises: 0019_strategy_card_v2
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_portfolio_windows"
down_revision = "0019_strategy_card_v2"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "portfolio_observation_windows",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("bucket_minutes", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("quality_json", sa.JSON(), nullable=False),
        sa.Column("strategy_summaries_json", sa.JSON(), nullable=False),
        sa.Column("pairwise_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    for column in (
        "schema_version",
        "policy_version",
        "status",
        "horizon_days",
        "bucket_minutes",
        "window_end",
        "request_hash",
        "source_hash",
        "content_hash",
        "idempotency_key",
        "created_by",
    ):
        op.create_index(
            f"ix_portfolio_observation_windows_{column}",
            "portfolio_observation_windows",
            [column],
        )


def downgrade() -> None:
    op.drop_table("portfolio_observation_windows")
