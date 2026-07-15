"""deterministic context packs and mission artifact index

Revision ID: 0025_agent_context_artifacts
Revises: 0024_agent_capabilities
"""

import sqlalchemy as sa
from alembic import op

revision = "0025_agent_context_artifacts"
down_revision = "0024_agent_capabilities"
branch_labels = None
depends_on = None


def _indexes(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "agent_context_packs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("policy_ref", sa.String(128), nullable=False),
        sa.Column("budget_tokens", sa.Integer(), nullable=False),
        sa.Column("used_tokens", sa.Integer(), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("decisions_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "mission_id", "plan_version", "step_id", "attempt", name="uq_agent_context_attempt"
        ),
    )
    _indexes(
        "agent_context_packs", "mission_id", "step_id", "policy_ref", "manifest_hash"
    )
    op.create_table(
        "agent_mission_artifacts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("inline_preview_json", sa.JSON(), nullable=False),
        sa.Column("producer_ref", sa.String(300), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("supersedes_artifact_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mission_id", "content_hash", name="uq_agent_mission_artifact_hash"),
    )
    _indexes(
        "agent_mission_artifacts",
        "mission_id",
        "kind",
        "content_hash",
        "producer_ref",
        "supersedes_artifact_id",
        "status",
    )
    op.create_table(
        "agent_artifact_relations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("from_artifact_id", sa.String(32), nullable=False),
        sa.Column("to_ref", sa.Text(), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "from_artifact_id", "to_ref", "relation_type", name="uq_agent_artifact_relation"
        ),
    )
    _indexes(
        "agent_artifact_relations",
        "mission_id",
        "from_artifact_id",
        "relation_type",
    )


def downgrade() -> None:
    op.drop_table("agent_artifact_relations")
    op.drop_table("agent_mission_artifacts")
    op.drop_table("agent_context_packs")
