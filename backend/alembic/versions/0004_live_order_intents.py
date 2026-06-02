"""live order intents

Revision ID: 0004_live_order_intents
Revises: 0003_strategy_backtest
Create Date: 2026-06-02 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_live_order_intents"
down_revision = "0003_strategy_backtest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_order_intents",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=32), nullable=False),
        sa.Column("size", sa.Numeric(30, 12), nullable=False),
        sa.Column("price", sa.Numeric(30, 12), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_run_id", sa.String(length=32), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_live_order_intents_environment", "live_order_intents", ["environment"])
    op.create_index("ix_live_order_intents_status", "live_order_intents", ["status"])
    op.create_index("ix_live_order_intents_inst_id", "live_order_intents", ["inst_id"])
    op.create_index("ix_live_order_intents_source_run_id", "live_order_intents", ["source_run_id"])


def downgrade() -> None:
    op.drop_table("live_order_intents")
