"""Operator-visible evolution alerts: silent data-gap stalls are defects."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046_evolution_alerts"
down_revision: str | None = "0045_portfolio_research"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "arc_evolution_alerts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="warning"),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.String(512), nullable=False, server_default=""),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_result", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_arc_evolution_alerts_code", "arc_evolution_alerts", ["code"])
    op.create_index("ix_arc_evolution_alerts_severity", "arc_evolution_alerts", ["severity"])
    op.create_index("ix_arc_evolution_alerts_strategy_id", "arc_evolution_alerts", ["strategy_id"])
    op.create_index("ix_arc_evolution_alerts_status", "arc_evolution_alerts", ["status"])


def downgrade() -> None:
    op.drop_table("arc_evolution_alerts")
