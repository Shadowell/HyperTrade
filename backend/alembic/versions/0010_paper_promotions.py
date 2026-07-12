"""paper promotions

Revision ID: 0010_paper_promotions
Revises: 0009_research_evidence
Create Date: 2026-07-12 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_paper_promotions"
down_revision = "0009_research_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_promotions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("mandate_id", sa.String(length=32), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("evidence_id", sa.String(length=32), nullable=False, unique=True),
        sa.Column("strategy_key", sa.String(length=128), nullable=False),
        sa.Column("bitpro_strategy_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("approval_reason", sa.Text(), nullable=False),
        sa.Column("approval_idempotency_key", sa.String(length=128), nullable=True, unique=True),
        sa.Column("approved_by", sa.String(length=128), nullable=False),
        sa.Column("paper_refs_json", sa.JSON(), nullable=False),
        sa.Column("observation_json", sa.JSON(), nullable=False),
        sa.Column("transition_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "mandate_id",
        "job_id",
        "evidence_id",
        "strategy_key",
        "bitpro_strategy_id",
        "status",
    ):
        op.create_index(f"ix_paper_promotions_{column}", "paper_promotions", [column])


def downgrade() -> None:
    for column in (
        "status",
        "bitpro_strategy_id",
        "strategy_key",
        "evidence_id",
        "job_id",
        "mandate_id",
    ):
        op.drop_index(f"ix_paper_promotions_{column}", table_name="paper_promotions")
    op.drop_table("paper_promotions")
