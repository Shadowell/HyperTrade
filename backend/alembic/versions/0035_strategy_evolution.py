"""bounded existing-strategy evolution ledger

Revision ID: 0035_strategy_evolution
Revises: 0034_bitpro_strategy_evidence
"""

import sqlalchemy as sa
from alembic import op

revision = "0035_strategy_evolution"
down_revision = "0034_bitpro_strategy_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_evolution_runs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("parent_version_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("mandate_json", sa.JSON(), nullable=False),
        sa.Column("assessment_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "parent_version_id",
        "status",
        "request_hash",
        "idempotency_key",
        "created_by",
    ):
        op.create_index(
            f"ix_strategy_evolution_runs_{column}", "strategy_evolution_runs", [column]
        )
    op.create_table(
        "strategy_evolution_candidates",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, unique=True),
        sa.Column("parent_version_id", sa.String(length=32), nullable=False),
        sa.Column("candidate_version_id", sa.String(length=32), nullable=False),
        sa.Column("manifest_id", sa.String(length=32), nullable=False),
        sa.Column("experiment_execution_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("proposal_kind", sa.String(length=24), nullable=False),
        sa.Column("candidate_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "run_id",
        "schema_version",
        "parent_version_id",
        "candidate_version_id",
        "manifest_id",
        "experiment_execution_id",
        "status",
        "proposal_kind",
        "created_by",
    ):
        op.create_index(
            f"ix_strategy_evolution_candidates_{column}",
            "strategy_evolution_candidates",
            [column],
        )


def downgrade() -> None:
    op.drop_table("strategy_evolution_candidates")
    op.drop_table("strategy_evolution_runs")
