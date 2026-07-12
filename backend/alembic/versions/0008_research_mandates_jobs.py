"""research mandates and durable jobs

Revision ID: 0008_research_mandates_jobs
Revises: 0007_monitoring_alerts
Create Date: 2026-07-12 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_research_mandates_jobs"
down_revision = "0007_monitoring_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_mandates",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("market_type", sa.String(length=32), nullable=False),
        sa.Column("symbols_json", sa.JSON(), nullable=False),
        sa.Column("timeframes_json", sa.JSON(), nullable=False),
        sa.Column("strategy_categories_json", sa.JSON(), nullable=False),
        sa.Column("budget_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("paper_promotion_mode", sa.String(length=32), nullable=False),
        sa.Column("live_mode", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("audit_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_mandates_name", "research_mandates", ["name"])
    op.create_index("ix_research_mandates_status", "research_mandates", ["status"])
    op.create_index("ix_research_mandates_market_type", "research_mandates", ["market_type"])
    op.create_index(
        "ix_research_mandates_paper_promotion_mode",
        "research_mandates",
        ["paper_promotion_mode"],
    )
    op.create_index("ix_research_mandates_live_mode", "research_mandates", ["live_mode"])

    op.create_table(
        "research_jobs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("mandate_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("strategy_spec_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("source_run_id", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("transition_json", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_jobs_mandate_id", "research_jobs", ["mandate_id"])
    op.create_index("ix_research_jobs_status", "research_jobs", ["status"])
    op.create_index("ix_research_jobs_idempotency_key", "research_jobs", ["idempotency_key"])
    op.create_index("ix_research_jobs_source_run_id", "research_jobs", ["source_run_id"])


def downgrade() -> None:
    op.drop_index("ix_research_jobs_source_run_id", table_name="research_jobs")
    op.drop_index("ix_research_jobs_idempotency_key", table_name="research_jobs")
    op.drop_index("ix_research_jobs_status", table_name="research_jobs")
    op.drop_index("ix_research_jobs_mandate_id", table_name="research_jobs")
    op.drop_table("research_jobs")
    op.drop_index("ix_research_mandates_live_mode", table_name="research_mandates")
    op.drop_index("ix_research_mandates_paper_promotion_mode", table_name="research_mandates")
    op.drop_index("ix_research_mandates_market_type", table_name="research_mandates")
    op.drop_index("ix_research_mandates_status", table_name="research_mandates")
    op.drop_index("ix_research_mandates_name", table_name="research_mandates")
    op.drop_table("research_mandates")
