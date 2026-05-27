"""paper trading runtime

Revision ID: 0002_paper_trading
Revises: 0001_initial
Create Date: 2026-05-27 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_paper_trading"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_sessions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("cash", sa.Numeric(30, 12), nullable=False),
        sa.Column("equity", sa.Numeric(30, 12), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(30, 12), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paper_sessions_status", "paper_sessions", ["status"])
    op.create_table(
        "paper_positions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 12), nullable=False),
        sa.Column("entry_price", sa.Numeric(30, 12), nullable=False),
        sa.Column("mark_price", sa.Numeric(30, 12), nullable=False),
        sa.Column("notional", sa.Numeric(30, 12), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(30, 12), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paper_positions_session_id", "paper_positions", ["session_id"])
    op.create_index("ix_paper_positions_inst_id", "paper_positions", ["inst_id"])
    op.create_index("ix_paper_positions_side", "paper_positions", ["side"])
    op.create_index("ix_paper_positions_status", "paper_positions", ["status"])
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 12), nullable=False),
        sa.Column("target_notional", sa.Numeric(30, 12), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paper_orders_session_id", "paper_orders", ["session_id"])
    op.create_index("ix_paper_orders_inst_id", "paper_orders", ["inst_id"])
    op.create_index("ix_paper_orders_status", "paper_orders", ["status"])
    op.create_table(
        "paper_fills",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("order_id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("inst_id", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(30, 12), nullable=False),
        sa.Column("price", sa.Numeric(30, 12), nullable=False),
        sa.Column("fee", sa.Numeric(30, 12), nullable=False),
        sa.Column("slippage_bps", sa.Numeric(18, 6), nullable=False),
        sa.Column("source_ticker_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paper_fills_order_id", "paper_fills", ["order_id"])
    op.create_index("ix_paper_fills_session_id", "paper_fills", ["session_id"])
    op.create_index("ix_paper_fills_inst_id", "paper_fills", ["inst_id"])
    op.create_table(
        "paper_events",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("session_id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_paper_events_session_id", "paper_events", ["session_id"])
    op.create_index("ix_paper_events_kind", "paper_events", ["kind"])


def downgrade() -> None:
    for table in (
        "paper_events",
        "paper_fills",
        "paper_orders",
        "paper_positions",
        "paper_sessions",
    ):
        op.drop_table(table)
