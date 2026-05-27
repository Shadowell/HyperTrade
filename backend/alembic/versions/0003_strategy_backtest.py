"""strategy research and backtests

Revision ID: 0003_strategy_backtest
Revises: 0002_paper_trading
Create Date: 2026-05-27 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_strategy_backtest"
down_revision = "0002_paper_trading"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_research",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("strategy_key", sa.String(length=128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_strategy_research_strategy_key", "strategy_research", ["strategy_key"])
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("research_id", sa.String(length=32), nullable=False),
        sa.Column("strategy_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("start_cash", sa.Numeric(30, 12), nullable=False),
        sa.Column("end_value", sa.Numeric(30, 12), nullable=False),
        sa.Column("total_return_pct", sa.Numeric(18, 6), nullable=False),
        sa.Column("max_drawdown_pct", sa.Numeric(18, 6), nullable=False),
        sa.Column("trade_count", sa.Integer(), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_backtest_runs_research_id", "backtest_runs", ["research_id"])
    op.create_index("ix_backtest_runs_strategy_key", "backtest_runs", ["strategy_key"])
    op.create_index("ix_backtest_runs_status", "backtest_runs", ["status"])


def downgrade() -> None:
    op.drop_table("backtest_runs")
    op.drop_table("strategy_research")
