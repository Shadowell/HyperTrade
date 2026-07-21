"""canonical Thread Turn Item protocol

Revision ID: 0029_canonical_thread_turn
Revises: 0028_mission_delivery
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_canonical_thread_turn"
down_revision = "0028_mission_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_threads",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("owner", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("retention", sa.String(length=32), nullable=False),
        sa.Column("active_turn_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("event_cursor", sa.Integer(), nullable=False),
        sa.Column("projection_hash", sa.String(length=64), nullable=False),
        sa.Column("quarantine_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_threads_tenant_id", "agent_threads", ["tenant_id"])
    op.create_index("ix_agent_threads_owner", "agent_threads", ["owner"])
    op.create_index("ix_agent_threads_status", "agent_threads", ["status"])
    op.create_index("ix_agent_threads_active_turn_id", "agent_threads", ["active_turn_id"])
    op.create_index("ix_agent_threads_projection_hash", "agent_threads", ["projection_hash"])

    op.create_table(
        "agent_turns",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("thread_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("client_message_id", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("input_item_id", sa.String(length=32), nullable=False),
        sa.Column("response_item_id", sa.String(length=32), nullable=False),
        sa.Column("mission_id", sa.String(length=32), nullable=False),
        sa.Column("resolved_context_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("thread_id", "client_message_id", name="uq_agent_turn_client_message"),
    )
    op.create_index("ix_agent_turns_thread_id", "agent_turns", ["thread_id"])
    op.create_index("ix_agent_turns_status", "agent_turns", ["status"])
    op.create_index("ix_agent_turns_request_hash", "agent_turns", ["request_hash"])
    op.create_index("ix_agent_turns_mission_id", "agent_turns", ["mission_id"])

    op.create_table(
        "agent_thread_items",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("thread_id", sa.String(length=32), nullable=False),
        sa.Column("turn_id", sa.String(length=32), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("thread_id", "sequence", "id", name="uq_agent_thread_item_sequence"),
    )
    op.create_index("ix_agent_thread_items_thread_id", "agent_thread_items", ["thread_id"])
    op.create_index("ix_agent_thread_items_turn_id", "agent_thread_items", ["turn_id"])
    op.create_index("ix_agent_thread_items_item_type", "agent_thread_items", ["item_type"])
    op.create_index("ix_agent_thread_items_status", "agent_thread_items", ["status"])

    op.create_table(
        "agent_thread_events",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("thread_id", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=96), nullable=False),
        sa.Column("aggregate_type", sa.String(length=32), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("thread_sequence", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("reducer_version", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("policy_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("thread_id", "thread_sequence", name="uq_agent_thread_event_sequence"),
        sa.UniqueConstraint("thread_id", "aggregate_version", name="uq_agent_thread_event_version"),
        sa.UniqueConstraint(
            "thread_id", "idempotency_key", name="uq_agent_thread_event_idempotency"
        ),
    )
    op.create_index("ix_agent_thread_events_thread_id", "agent_thread_events", ["thread_id"])
    op.create_index("ix_agent_thread_events_event_type", "agent_thread_events", ["event_type"])
    op.create_index("ix_agent_thread_events_tenant_id", "agent_thread_events", ["tenant_id"])
    op.create_index("ix_agent_thread_events_actor", "agent_thread_events", ["actor"])
    op.create_index("ix_agent_thread_events_payload_hash", "agent_thread_events", ["payload_hash"])


def downgrade() -> None:
    op.drop_table("agent_thread_events")
    op.drop_table("agent_thread_items")
    op.drop_table("agent_turns")
    op.drop_table("agent_threads")
