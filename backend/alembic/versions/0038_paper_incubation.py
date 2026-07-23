"""paper incubation mandates and action ledger

Revision ID: 0038_paper_incubation
Revises: 0037_unified_validation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_paper_incubation"
down_revision: str | None = "0037_unified_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "paper_research_mandates",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("mandate_json", sa.JSON(), nullable=False),
        sa.Column("control_json", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column("kill_switch", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_incubation_members",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mandate_id", sa.String(32), nullable=False),
        sa.Column("candidate_kind", sa.String(24), nullable=False),
        sa.Column("candidate_id", sa.String(32), nullable=False),
        sa.Column("validation_id", sa.String(32), nullable=False),
        sa.Column("manifest_id", sa.String(32), nullable=False),
        sa.Column("experiment_execution_id", sa.String(32), nullable=False),
        sa.Column("bitpro_strategy_id", sa.String(64), nullable=False),
        sa.Column("paper_instance_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_hash", sa.String(72), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("rejection_reasons_json", sa.JSON(), nullable=False),
        sa.Column("observation_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "mandate_id",
            "candidate_kind",
            "candidate_id",
            name="uq_paper_incubation_member",
        ),
    )
    op.create_table(
        "paper_incubation_actions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mandate_id", sa.String(32), nullable=False),
        sa.Column("member_id", sa.String(32), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("dispatch_intent_id", sa.String(64), nullable=False),
        sa.Column("tool_call_id", sa.String(64), nullable=False),
        sa.Column("external_operation_id", sa.String(256), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False),
        sa.Column("after_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("outcome_link", sa.String(256), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table, columns in {
        "paper_research_mandates": ("status", "policy_hash", "valid_until"),
        "paper_incubation_members": ("mandate_id", "status", "candidate_id"),
        "paper_incubation_actions": ("mandate_id", "member_id", "status"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("paper_incubation_actions")
    op.drop_table("paper_incubation_members")
    op.drop_table("paper_research_mandates")
