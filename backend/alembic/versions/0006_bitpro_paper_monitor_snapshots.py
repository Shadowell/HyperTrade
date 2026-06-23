"""bitpro paper monitor snapshots

Revision ID: 0006_bitpro_paper_monitor_snapshots
Revises: 0005_agent_capability_expansion
Create Date: 2026-06-23 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_bp_paper_monitor_snapshots"
down_revision = "0005_agent_capability_expansion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bitpro_paper_monitor_snapshots",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("scope_key", sa.String(length=64), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("previous_snapshot_id", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("dashboard_json", sa.JSON(), nullable=False),
        sa.Column("running_strategies_json", sa.JSON(), nullable=False),
        sa.Column("monitor_summary_json", sa.JSON(), nullable=False),
        sa.Column("event_summary_json", sa.JSON(), nullable=False),
        sa.Column("equity_summary_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("drift_json", sa.JSON(), nullable=False),
        sa.Column("tool_calls_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_bitpro_paper_monitor_snapshots_scope_key",
        "bitpro_paper_monitor_snapshots",
        ["scope_key"],
    )
    op.create_index(
        "ix_bitpro_paper_monitor_snapshots_strategy_id",
        "bitpro_paper_monitor_snapshots",
        ["strategy_id"],
    )
    op.create_index(
        "ix_bitpro_paper_monitor_snapshots_previous_snapshot_id",
        "bitpro_paper_monitor_snapshots",
        ["previous_snapshot_id"],
    )
    op.create_index(
        "ix_bitpro_paper_monitor_snapshots_status",
        "bitpro_paper_monitor_snapshots",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bitpro_paper_monitor_snapshots_status",
        table_name="bitpro_paper_monitor_snapshots",
    )
    op.drop_index(
        "ix_bitpro_paper_monitor_snapshots_previous_snapshot_id",
        table_name="bitpro_paper_monitor_snapshots",
    )
    op.drop_index(
        "ix_bitpro_paper_monitor_snapshots_strategy_id",
        table_name="bitpro_paper_monitor_snapshots",
    )
    op.drop_index(
        "ix_bitpro_paper_monitor_snapshots_scope_key",
        table_name="bitpro_paper_monitor_snapshots",
    )
    op.drop_table("bitpro_paper_monitor_snapshots")
