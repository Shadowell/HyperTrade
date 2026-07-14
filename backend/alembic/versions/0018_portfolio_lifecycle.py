"""portfolio strategy lifecycle assessments and reviews

Revision ID: 0018_portfolio_lifecycle
Revises: 0017_memory_skills
"""

import sqlalchemy as sa
from alembic import op

revision = "0018_portfolio_lifecycle"
down_revision = "0017_memory_skills"
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
        "portfolio_assessments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("world_state_ref", sa.String(128), nullable=False),
        sa.Column("input_refs_json", sa.JSON(), nullable=False),
        sa.Column("strategy_assessments_json", sa.JSON(), nullable=False),
        sa.Column("pairwise_json", sa.JSON(), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("recommendations_json", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "portfolio_assessments",
        "schema_version",
        "policy_version",
        "policy_hash",
        "status",
        "world_state_ref",
        "request_hash",
        "content_hash",
        "idempotency_key",
        "valid_until",
        "created_by",
    )
    op.create_table(
        "strategy_lifecycle_reviews",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("assessment_id", sa.String(32), nullable=False),
        sa.Column("recommendation_id", sa.String(96), nullable=False),
        sa.Column("strategy_card_id", sa.String(64), nullable=False),
        sa.Column("recommendation_action", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("decided_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "strategy_lifecycle_reviews",
        "assessment_id",
        "recommendation_id",
        "strategy_card_id",
        "recommendation_action",
        "decision",
        "idempotency_key",
        "decided_by",
    )


def downgrade() -> None:
    op.drop_table("strategy_lifecycle_reviews")
    op.drop_table("portfolio_assessments")
