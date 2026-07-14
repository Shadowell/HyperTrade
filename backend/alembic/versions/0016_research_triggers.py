"""durable bounded research triggers

Revision ID: 0016_research_triggers
Revises: 0015_robustness_validation
"""

import sqlalchemy as sa
from alembic import op

revision = "0016_research_triggers"
down_revision = "0015_robustness_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_triggers",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, unique=True),
        sa.Column("trigger_type", sa.String(48), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("mandate_id", sa.String(32), nullable=False),
        sa.Column("objective_template", sa.Text(), nullable=False),
        sa.Column("condition_json", sa.JSON(), nullable=False),
        sa.Column("schedule_json", sa.JSON(), nullable=False),
        sa.Column("task_budget_json", sa.JSON(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False),
        sa.Column("daily_quota", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("audit_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "name",
        "trigger_type",
        "enabled",
        "mandate_id",
        "next_run_at",
        "lease_owner",
        "lease_expires_at",
        "created_by",
    ):
        op.create_index(f"ix_research_triggers_{column}", "research_triggers", [column])

    op.create_table(
        "research_trigger_fires",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("trigger_id", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_type", sa.String(48), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("event_ref_json", sa.JSON(), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "trigger_id",
        "fingerprint",
        "bucket_start",
        "source_type",
        "source_id",
        "status",
        "task_id",
    ):
        op.create_index(
            f"ix_research_trigger_fires_{column}", "research_trigger_fires", [column]
        )

    op.create_table(
        "research_trigger_control",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("kill_switch", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_research_trigger_control_kill_switch",
        "research_trigger_control",
        ["kill_switch"],
    )


def downgrade() -> None:
    op.drop_table("research_trigger_control")
    op.drop_table("research_trigger_fires")
    op.drop_table("research_triggers")
