"""bounded autonomous new-strategy discovery ledger

Revision ID: 0036_strategy_discovery
Revises: 0035_strategy_evolution
"""

import sqlalchemy as sa
from alembic import op

revision = "0036_strategy_discovery"
down_revision = "0035_strategy_evolution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_discovery_runs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("research_mandate_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("mandate_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "research_mandate_id", "status", "request_hash", "idempotency_key", "created_by"
    ):
        op.create_index(
            f"ix_strategy_discovery_runs_{column}", "strategy_discovery_runs", [column]
        )

    op.create_table(
        "strategy_discovery_candidates",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, unique=True),
        sa.Column("phenomenon_hash", sa.String(length=64), nullable=False),
        sa.Column("hypothesis_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("strategy_family", sa.String(length=48), nullable=False),
        sa.Column("bitpro_strategy_id", sa.String(length=64), nullable=False),
        sa.Column("manifest_id", sa.String(length=32), nullable=False),
        sa.Column("experiment_execution_id", sa.String(length=32), nullable=False),
        sa.Column("strategy_version_id", sa.String(length=32), nullable=False),
        sa.Column("phenomenon_json", sa.JSON(), nullable=False),
        sa.Column("hypothesis_json", sa.JSON(), nullable=False),
        sa.Column("novelty_json", sa.JSON(), nullable=False),
        sa.Column("candidate_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "run_id", "schema_version", "phenomenon_hash", "hypothesis_hash", "status",
        "strategy_family", "bitpro_strategy_id", "manifest_id", "experiment_execution_id",
        "strategy_version_id", "created_by",
    ):
        op.create_index(
            f"ix_strategy_discovery_candidates_{column}",
            "strategy_discovery_candidates",
            [column],
        )


def downgrade() -> None:
    op.drop_table("strategy_discovery_candidates")
    op.drop_table("strategy_discovery_runs")
