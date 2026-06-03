"""agent capability expansion

Revision ID: 0005_agent_capability_expansion
Revises: 0004_live_order_intents
Create Date: 2026-06-03 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_agent_capability_expansion"
down_revision = "0004_live_order_intents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("agent_runs", sa.Column("run_state_json", sa.JSON(), nullable=True))
    op.execute("UPDATE agent_runs SET run_state_json = '{}' WHERE run_state_json IS NULL")
    op.alter_column("agent_runs", "run_state_json", nullable=False)

    op.add_column("rag_chunks", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("rag_chunks", sa.Column("embedding_vector", sa.JSON(), nullable=True))
    op.execute("UPDATE rag_chunks SET title = '', embedding_vector = embedding_json")
    op.alter_column("rag_chunks", "title", nullable=False)
    op.alter_column("rag_chunks", "embedding_vector", nullable=False)

    op.add_column("memory_items", sa.Column("importance", sa.Numeric(10, 4), nullable=True))
    op.add_column("memory_items", sa.Column("tags", sa.JSON(), nullable=True))
    op.add_column("memory_items", sa.Column("confidence", sa.Numeric(10, 4), nullable=True))
    op.add_column(
        "memory_items",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("memory_items", sa.Column("usage_count", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE memory_items SET importance = 0.50, tags = '[]', confidence = 0.70, "
        "usage_count = 0 WHERE importance IS NULL"
    )
    op.alter_column("memory_items", "importance", nullable=False)
    op.alter_column("memory_items", "tags", nullable=False)
    op.alter_column("memory_items", "confidence", nullable=False)
    op.alter_column("memory_items", "usage_count", nullable=False)

    op.add_column(
        "live_order_intents",
        sa.Column("risk_status", sa.String(length=32), nullable=True),
    )
    op.add_column("live_order_intents", sa.Column("risk_json", sa.JSON(), nullable=True))
    op.add_column("live_order_intents", sa.Column("execution_json", sa.JSON(), nullable=True))
    op.add_column(
        "live_order_intents",
        sa.Column("exchange_order_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "live_order_intents",
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE live_order_intents SET risk_status = 'pending', risk_json = '{}', "
        "execution_json = '{}', exchange_order_id = '' WHERE risk_status IS NULL"
    )
    op.alter_column("live_order_intents", "risk_status", nullable=False)
    op.alter_column("live_order_intents", "risk_json", nullable=False)
    op.alter_column("live_order_intents", "execution_json", nullable=False)
    op.alter_column("live_order_intents", "exchange_order_id", nullable=False)
    op.create_index("ix_live_order_intents_risk_status", "live_order_intents", ["risk_status"])

    op.create_table(
        "strategy_experiments",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("research_id", sa.String(length=32), nullable=False),
        sa.Column("backtest_id", sa.String(length=32), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_strategy_experiments_status", "strategy_experiments", ["status"])
    op.create_index("ix_strategy_experiments_research_id", "strategy_experiments", ["research_id"])
    op.create_index("ix_strategy_experiments_backtest_id", "strategy_experiments", ["backtest_id"])


def downgrade() -> None:
    op.drop_table("strategy_experiments")
    op.drop_index("ix_live_order_intents_risk_status", table_name="live_order_intents")
    for column in (
        "executed_at",
        "exchange_order_id",
        "execution_json",
        "risk_json",
        "risk_status",
    ):
        op.drop_column("live_order_intents", column)
    for column in ("usage_count", "last_used_at", "confidence", "tags", "importance"):
        op.drop_column("memory_items", column)
    op.drop_column("rag_chunks", "embedding_vector")
    op.drop_column("rag_chunks", "title")
    op.drop_column("agent_runs", "run_state_json")
