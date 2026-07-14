"""append-only research evidence v2

Revision ID: 0013_research_evidence_v2
Revises: 0012_agent_sessions_tasks
"""

import sqlalchemy as sa
from alembic import op

revision = "0013_research_evidence_v2"
down_revision = "0012_agent_sessions_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_evidence",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("node_run_id", sa.String(32), nullable=False),
        sa.Column("role_key", sa.String(96), nullable=False),
        sa.Column("symbols_json", sa.JSON(), nullable=False),
        sa.Column("timeframes_json", sa.JSON(), nullable=False),
        sa.Column("market_type", sa.String(32), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("sources_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(10, 8), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("supersedes_id", sa.String(32), nullable=True),
        sa.Column("superseded_by_id", sa.String(32), nullable=True),
        sa.Column("lifecycle_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("content_hash"),
    )
    for column in (
        "schema_version",
        "evidence_type",
        "status",
        "task_id",
        "node_run_id",
        "role_key",
        "market_type",
        "as_of",
        "valid_until",
        "content_hash",
        "supersedes_id",
        "superseded_by_id",
        "created_by",
    ):
        op.create_index(f"ix_research_evidence_{column}", "research_evidence", [column])

    op.create_table(
        "research_evidence_relations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("from_evidence_id", sa.String(32), nullable=False),
        sa.Column("to_evidence_id", sa.String(32), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "from_evidence_id",
            "to_evidence_id",
            "relation_type",
            name="uq_research_evidence_relation",
        ),
    )
    for column in ("from_evidence_id", "to_evidence_id", "relation_type", "created_by"):
        op.create_index(
            f"ix_research_evidence_relations_{column}",
            "research_evidence_relations",
            [column],
        )


def downgrade() -> None:
    op.drop_table("research_evidence_relations")
    op.drop_table("research_evidence")
