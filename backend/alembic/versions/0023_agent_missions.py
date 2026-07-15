"""professional agent runtime mission event model

Revision ID: 0023_agent_missions
Revises: 0022_shadow_portfolios
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_agent_missions"
down_revision = "0022_shadow_portfolios"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _indexes(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "agent_missions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("original_objective", sa.Text(), nullable=False),
        sa.Column("success_criteria_json", sa.JSON(), nullable=False),
        sa.Column("constraints_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("budget_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("permission_profile_ref", sa.String(128), nullable=False),
        sa.Column("context_policy_ref", sa.String(128), nullable=False),
        sa.Column("active_plan_version", sa.Integer(), nullable=False),
        sa.Column("current_step_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_event_sequence", sa.Integer(), nullable=False),
        sa.Column("control_requested", sa.String(32), nullable=False),
        sa.Column("terminal_summary", sa.Text(), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    _indexes(
        "agent_missions",
        "status",
        "permission_profile_ref",
        "context_policy_ref",
        "current_step_id",
        "control_requested",
        "created_by",
        "lease_owner",
        "lease_expires_at",
    )
    op.create_table(
        "agent_mission_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mission_id", "sequence", name="uq_agent_mission_event_sequence"),
    )
    _indexes("agent_mission_events", "mission_id", "event_type", "actor")
    op.create_table(
        "agent_plan_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version", sa.Integer(), nullable=True),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mission_id", "version", name="uq_agent_plan_version"),
    )
    _indexes("agent_plan_versions", "mission_id", "content_hash")
    op.create_table(
        "agent_step_attempts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("capability_id", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("observation_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "mission_id",
            "plan_version",
            "step_id",
            "attempt",
            name="uq_agent_step_attempt",
        ),
    )
    _indexes("agent_step_attempts", "mission_id", "step_id", "capability_id", "status")
    op.create_table(
        "agent_steering_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("plan_version_before", sa.Integer(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("agent_steering_events", "mission_id", "actor")


def downgrade() -> None:
    op.drop_table("agent_steering_events")
    op.drop_table("agent_step_attempts")
    op.drop_table("agent_plan_versions")
    op.drop_table("agent_mission_events")
    op.drop_table("agent_missions")
