"""approval and external effect governance

Revision ID: 0032_effect_governance
Revises: 0031_mission_event_reducer
"""

import sqlalchemy as sa
from alembic import op

revision = "0032_effect_governance"
down_revision = "0031_mission_event_reducer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_policy_decisions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_policy_decisions_mission_id", "agent_policy_decisions", ["mission_id"]
    )
    op.create_index("ix_agent_policy_decisions_decision", "agent_policy_decisions", ["decision"])

    op.create_table(
        "agent_approvals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("decision_id", sa.String(length=64), nullable=False),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("grant_json", sa.JSON(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("decision_id", "mission_id", "status", "token_hash", "expires_at"):
        op.create_index(f"ix_agent_approvals_{column}", "agent_approvals", [column])

    op.create_table(
        "agent_dispatch_intents",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column("tool_call_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("intent_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("mission_id", "tool_call_id", "idempotency_key", "payload_hash", "status"):
        op.create_index(f"ix_agent_dispatch_intents_{column}", "agent_dispatch_intents", [column])

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("intent_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column("capability_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("call_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("intent_id", "mission_id", "capability_id", "status"):
        op.create_index(f"ix_agent_tool_calls_{column}", "agent_tool_calls", [column])

    op.create_table(
        "agent_effect_audit_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("aggregate_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("aggregate_id", "sequence", name="uq_agent_effect_event_sequence"),
    )
    for column in ("aggregate_id", "event_type", "actor"):
        op.create_index(
            f"ix_agent_effect_audit_events_{column}",
            "agent_effect_audit_events",
            [column],
        )

    op.create_table(
        "agent_effect_circuits",
        sa.Column("capability_id", sa.String(length=160), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "agent_effect_circuits",
        "agent_effect_audit_events",
        "agent_tool_calls",
        "agent_dispatch_intents",
        "agent_approvals",
        "agent_policy_decisions",
    ):
        op.drop_table(table)
