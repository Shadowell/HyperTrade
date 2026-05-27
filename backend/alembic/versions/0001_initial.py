"""initial hypertrade schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-27 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "market_tickers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("inst_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("inst_type", sa.String(length=32), nullable=False),
        sa.Column("last", sa.Numeric(30, 12), nullable=False),
        sa.Column("volume_ccy_24h", sa.Numeric(30, 12), nullable=False),
        sa.Column("change_utc0_pct", sa.Numeric(18, 6), nullable=False),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_tickers_inst_id", "market_tickers", ["inst_id"])
    op.create_index("ix_market_tickers_inst_type", "market_tickers", ["inst_type"])
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("report_markdown", sa.Text(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_table(
        "trace_events",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trace_events_run_id", "trace_events", ["run_id"])
    op.create_index("ix_trace_events_tool_name", "trace_events", ["tool_name"])
    op.create_table(
        "rag_documents",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("source_path", sa.Text(), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rag_documents_content_hash", "rag_documents", ["content_hash"])
    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("document_id", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rag_chunks_document_id", "rag_chunks", ["document_id"])
    op.create_index("ix_rag_chunks_source_path", "rag_chunks", ["source_path"])
    op.execute("ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS embedding vector(1024)")
    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.String(length=32), nullable=False),
        sa.Column("source_tool", sa.String(length=128), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_memory_items_kind", "memory_items", ["kind"])
    op.create_index("ix_memory_items_source_run_id", "memory_items", ["source_run_id"])
    op.create_index("ix_memory_items_disabled", "memory_items", ["disabled"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("kind", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_kind", "jobs", ["kind"])
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade() -> None:
    for table in (
        "jobs",
        "memory_items",
        "rag_chunks",
        "rag_documents",
        "trace_events",
        "agent_runs",
        "market_tickers",
    ):
        op.drop_table(table)
