"""versioned paper cohort snapshots and human label decisions

Revision ID: 0021_paper_cohorts
Revises: 0020_portfolio_windows
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_paper_cohorts"
down_revision = "0020_portfolio_windows"
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
        "paper_cohort_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("cohort_key", sa.String(64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("observation_window_id", sa.String(32), nullable=False),
        sa.Column("intake_count", sa.Integer(), nullable=False),
        sa.Column("comparable_count", sa.Integer(), nullable=False),
        sa.Column("proposal_count", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.UniqueConstraint("cohort_key", "version_number", name="uq_paper_cohort_version"),
        sa.UniqueConstraint("cohort_key", "source_hash", name="uq_paper_cohort_source"),
        *_timestamps(),
    )
    _indexes(
        "paper_cohort_snapshots",
        "cohort_key",
        "schema_version",
        "policy_version",
        "policy_hash",
        "status",
        "observation_window_id",
        "request_hash",
        "source_hash",
        "content_hash",
        "idempotency_key",
        "created_by",
    )
    op.create_table(
        "paper_cohort_label_decisions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("cohort_snapshot_id", sa.String(32), nullable=False),
        sa.Column("proposal_id", sa.String(64), nullable=False),
        sa.Column("strategy_card_id", sa.String(64), nullable=False),
        sa.Column("proposed_label", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "paper_cohort_label_decisions",
        "cohort_snapshot_id",
        "proposal_id",
        "strategy_card_id",
        "proposed_label",
        "decision",
        "request_hash",
        "idempotency_key",
        "valid_until",
        "decided_by",
    )


def downgrade() -> None:
    op.drop_table("paper_cohort_label_decisions")
    op.drop_table("paper_cohort_snapshots")
