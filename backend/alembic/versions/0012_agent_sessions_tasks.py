"""agent sessions and durable tasks

Revision ID: 0012_agent_sessions_tasks
Revises: 0011_paper_review_requests
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_agent_sessions_tasks"
down_revision = "0011_paper_review_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("surface", sa.String(32), nullable=False),
        sa.Column("provider_config_json", sa.JSON(), nullable=False),
        sa.Column("context_policy_json", sa.JSON(), nullable=False),
        sa.Column("summary_markdown", sa.Text(), nullable=False),
        sa.Column("last_event_sequence", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_sessions_status", "agent_sessions", ["status"])
    op.create_index("ix_agent_sessions_surface", "agent_sessions", ["surface"])
    op.create_index("ix_agent_sessions_created_by", "agent_sessions", ["created_by"])

    op.create_table(
        "agent_tasks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), nullable=True),
        sa.Column("parent_task_id", sa.String(32), nullable=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("budget_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("control_json", sa.JSON(), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checkpoint_id", sa.String(32), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("error_json", sa.JSON(), nullable=False),
        sa.Column("last_event_sequence", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key"),
    )
    for column in (
        "session_id",
        "parent_task_id",
        "kind",
        "status",
        "resource_type",
        "resource_id",
        "lease_owner",
        "lease_expires_at",
        "idempotency_key",
    ):
        op.create_index(f"ix_agent_tasks_{column}", "agent_tasks", [column])

    op.create_table(
        "task_node_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("node_key", sa.String(96), nullable=False),
        sa.Column("role_key", sa.String(96), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("depends_on_json", sa.JSON(), nullable=False),
        sa.Column("input_ref_json", sa.JSON(), nullable=False),
        sa.Column("output_ref_json", sa.JSON(), nullable=False),
        sa.Column("tool_policy_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("task_id", "node_key", "role_key", "status"):
        op.create_index(f"ix_task_node_runs_{column}", "task_node_runs", [column])

    op.create_table(
        "task_checkpoints",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("node_run_id", sa.String(32), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("resume_token", sa.String(64), nullable=False),
        sa.Column("reconciliation_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "sequence", name="uq_checkpoint_sequence"),
        sa.UniqueConstraint("resume_token"),
    )
    for column in (
        "task_id",
        "node_run_id",
        "state_hash",
        "resume_token",
        "reconciliation_required",
    ):
        op.create_index(f"ix_task_checkpoints_{column}", "task_checkpoints", [column])

    op.create_table(
        "task_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(96), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("redaction_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "sequence", name="uq_task_event_sequence"),
    )
    for column in ("task_id", "event", "actor"):
        op.create_index(f"ix_task_events_{column}", "task_events", [column])


def downgrade() -> None:
    op.drop_table("task_events")
    op.drop_table("task_checkpoints")
    op.drop_table("task_node_runs")
    op.drop_table("agent_tasks")
    op.drop_table("agent_sessions")
