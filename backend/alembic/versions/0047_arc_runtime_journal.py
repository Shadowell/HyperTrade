"""Durable evolution runtime failures and raw model replies; stdout is not evidence."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047_arc_runtime_journal"
down_revision: str | None = "0046_evolution_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "arc_runtime_errors",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("mission_id", sa.String(64), nullable=True),
        sa.Column("exception_type", sa.String(256), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("recent_messages_json", sa.JSON(), nullable=False),
        sa.Column("frames_json", sa.JSON(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=False, server_default=""),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_arc_runtime_errors_fingerprint", "arc_runtime_errors", ["fingerprint"])
    op.create_index("ix_arc_runtime_errors_component", "arc_runtime_errors", ["component"])
    op.create_index("ix_arc_runtime_errors_mission_id", "arc_runtime_errors", ["mission_id"])
    op.create_index("ix_arc_runtime_errors_last_seen_at", "arc_runtime_errors", ["last_seen_at"])
    op.create_table(
        "arc_model_exchanges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("mission_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False, server_default=""),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("request_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("context_record_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("reasoning_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("tool_calls_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("truncated_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_arc_model_exchanges_mission_id", "arc_model_exchanges", ["mission_id"])


def downgrade() -> None:
    op.drop_table("arc_model_exchanges")
    op.drop_table("arc_runtime_errors")
