"""immutable shadow portfolio proposals and human review decisions

Revision ID: 0022_shadow_portfolios
Revises: 0021_paper_cohorts
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_shadow_portfolios"
down_revision = "0021_paper_cohorts"
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
        "shadow_portfolio_proposals",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("portfolio_key", sa.String(64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("cohort_snapshot_id", sa.String(32), nullable=False),
        sa.Column("observation_window_id", sa.String(32), nullable=False),
        sa.Column("intake_count", sa.Integer(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("scenario_count", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("proposal_json", sa.JSON(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.UniqueConstraint(
            "portfolio_key", "version_number", name="uq_shadow_portfolio_version"
        ),
        sa.UniqueConstraint("portfolio_key", "source_hash", name="uq_shadow_portfolio_source"),
        *_timestamps(),
    )
    _indexes(
        "shadow_portfolio_proposals",
        "portfolio_key",
        "schema_version",
        "policy_version",
        "policy_hash",
        "status",
        "cohort_snapshot_id",
        "observation_window_id",
        "request_hash",
        "source_hash",
        "content_hash",
        "idempotency_key",
        "valid_until",
        "created_by",
    )
    op.create_table(
        "shadow_portfolio_review_decisions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("proposal_id", sa.String(32), nullable=False),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("template", sa.String(48), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "shadow_portfolio_review_decisions",
        "proposal_id",
        "scenario_id",
        "template",
        "decision",
        "request_hash",
        "idempotency_key",
        "valid_until",
        "decided_by",
    )


def downgrade() -> None:
    op.drop_table("shadow_portfolio_review_decisions")
    op.drop_table("shadow_portfolio_proposals")
