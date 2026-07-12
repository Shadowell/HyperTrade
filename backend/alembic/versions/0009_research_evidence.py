"""research experiment evidence

Revision ID: 0009_research_evidence
Revises: 0008_research_mandates_jobs
Create Date: 2026-07-12 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_research_evidence"
down_revision = "0008_research_mandates_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_jobs",
        sa.Column("external_refs_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_table(
        "research_experiment_evidence",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("mandate_id", sa.String(length=32), nullable=False),
        sa.Column("variant_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("strategy_key", sa.String(length=128), nullable=False),
        sa.Column("bitpro_strategy_id", sa.String(length=64), nullable=False),
        sa.Column("result_refs_json", sa.JSON(), nullable=False),
        sa.Column("windows_json", sa.JSON(), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("gate_results_json", sa.JSON(), nullable=False),
        sa.Column("rejection_reasons_json", sa.JSON(), nullable=False),
        sa.Column("tool_calls_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "job_id",
        "mandate_id",
        "variant_id",
        "status",
        "strategy_key",
        "bitpro_strategy_id",
    ):
        op.create_index(
            f"ix_research_experiment_evidence_{column}", "research_experiment_evidence", [column]
        )


def downgrade() -> None:
    for column in (
        "bitpro_strategy_id",
        "strategy_key",
        "status",
        "variant_id",
        "mandate_id",
        "job_id",
    ):
        op.drop_index(
            f"ix_research_experiment_evidence_{column}", table_name="research_experiment_evidence"
        )
    op.drop_table("research_experiment_evidence")
    op.drop_column("research_jobs", "external_refs_json")
