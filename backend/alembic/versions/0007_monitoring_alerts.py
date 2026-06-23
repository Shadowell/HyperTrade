"""monitoring alerts

Revision ID: 0007_monitoring_alerts
Revises: 0006_bp_paper_monitor_snapshots
Create Date: 2026-06-23 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_monitoring_alerts"
down_revision = "0006_bp_paper_monitor_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitor_definitions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("monitor_type", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("thresholds_json", sa.JSON(), nullable=False),
        sa.Column("schedule_json", sa.JSON(), nullable=False),
        sa.Column("notification_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_monitor_definitions_monitor_type",
        "monitor_definitions",
        ["monitor_type"],
    )
    op.create_index(
        "ix_monitor_definitions_enabled",
        "monitor_definitions",
        ["enabled"],
    )

    op.create_table(
        "monitor_runs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("monitor_id", sa.String(length=32), nullable=False),
        sa.Column("monitor_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("previous_run_id", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("source_tools_json", sa.JSON(), nullable=False),
        sa.Column("metric_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("drift_json", sa.JSON(), nullable=False),
        sa.Column("alerts_json", sa.JSON(), nullable=False),
        sa.Column("data_gaps_json", sa.JSON(), nullable=False),
        sa.Column("recommended_actions_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_monitor_runs_monitor_id", "monitor_runs", ["monitor_id"])
    op.create_index("ix_monitor_runs_monitor_type", "monitor_runs", ["monitor_type"])
    op.create_index("ix_monitor_runs_status", "monitor_runs", ["status"])
    op.create_index(
        "ix_monitor_runs_previous_run_id",
        "monitor_runs",
        ["previous_run_id"],
    )

    op.create_table(
        "monitor_alert_events",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("monitor_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=96), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("threshold_json", sa.JSON(), nullable=False),
        sa.Column("metric_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_monitor_alert_events_monitor_id",
        "monitor_alert_events",
        ["monitor_id"],
    )
    op.create_index("ix_monitor_alert_events_run_id", "monitor_alert_events", ["run_id"])
    op.create_index("ix_monitor_alert_events_level", "monitor_alert_events", ["level"])
    op.create_index("ix_monitor_alert_events_code", "monitor_alert_events", ["code"])
    op.create_index(
        "ix_monitor_alert_events_source_id",
        "monitor_alert_events",
        ["source_id"],
    )
    op.create_index("ix_monitor_alert_events_status", "monitor_alert_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_monitor_alert_events_status", table_name="monitor_alert_events")
    op.drop_index("ix_monitor_alert_events_source_id", table_name="monitor_alert_events")
    op.drop_index("ix_monitor_alert_events_code", table_name="monitor_alert_events")
    op.drop_index("ix_monitor_alert_events_level", table_name="monitor_alert_events")
    op.drop_index("ix_monitor_alert_events_run_id", table_name="monitor_alert_events")
    op.drop_index("ix_monitor_alert_events_monitor_id", table_name="monitor_alert_events")
    op.drop_table("monitor_alert_events")
    op.drop_index("ix_monitor_runs_previous_run_id", table_name="monitor_runs")
    op.drop_index("ix_monitor_runs_status", table_name="monitor_runs")
    op.drop_index("ix_monitor_runs_monitor_type", table_name="monitor_runs")
    op.drop_index("ix_monitor_runs_monitor_id", table_name="monitor_runs")
    op.drop_table("monitor_runs")
    op.drop_index("ix_monitor_definitions_enabled", table_name="monitor_definitions")
    op.drop_index("ix_monitor_definitions_monitor_type", table_name="monitor_definitions")
    op.drop_table("monitor_definitions")
