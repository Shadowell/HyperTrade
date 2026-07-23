"""unified strategy validation quarantine

Revision ID: 0037_unified_validation
Revises: 0036_strategy_discovery
"""

import sqlalchemy as sa
from alembic import op

revision = "0037_unified_validation"
down_revision = "0036_strategy_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "unified_strategy_validations",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("candidate_kind", sa.String(length=24), nullable=False),
        sa.Column("candidate_id", sa.String(length=32), nullable=False),
        sa.Column("trial_family_id", sa.String(length=128), nullable=False),
        sa.Column("manifest_id", sa.String(length=32), nullable=False),
        sa.Column("experiment_execution_id", sa.String(length=32), nullable=False),
        sa.Column("validation_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False, unique=True),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("source_hash", sa.String(length=72), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("trial_family_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("decision_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "candidate_kind", "candidate_id", "validation_version",
            name="uq_unified_validation_version",
        ),
    )
    for column in (
        "schema_version", "candidate_kind", "candidate_id", "trial_family_id", "manifest_id",
        "experiment_execution_id", "status", "fingerprint", "policy_hash", "source_hash",
        "request_hash", "idempotency_key", "created_by",
    ):
        op.create_index(
            f"ix_unified_strategy_validations_{column}",
            "unified_strategy_validations",
            [column],
        )


def downgrade() -> None:
    op.drop_table("unified_strategy_validations")
