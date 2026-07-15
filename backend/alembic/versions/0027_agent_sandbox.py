"""sandbox runs and import review facts

Revision ID: 0027_agent_sandbox
Revises: 0026_agent_supervision
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_agent_sandbox"
down_revision = "0026_agent_supervision"
branch_labels = None
depends_on = None


def _indexes(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "agent_sandbox_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("assignment_ref", sa.String(300), nullable=False),
        sa.Column("context_pack_refs_json", sa.JSON(), nullable=False),
        sa.Column("source_artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("patch_json", sa.JSON(), nullable=False),
        sa.Column("commands_json", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes(
        "agent_sandbox_runs",
        "mission_id",
        "assignment_ref",
        "status",
        "request_hash",
        "artifact_hash",
        "idempotency_key",
    )
    op.create_table(
        "agent_sandbox_artifacts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("sandbox_run_id", sa.String(32), nullable=False),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("path", sa.String(300), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("preview", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes(
        "agent_sandbox_artifacts",
        "sandbox_run_id",
        "mission_id",
        "kind",
        "content_hash",
    )
    op.create_table(
        "agent_sandbox_import_reviews",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("sandbox_run_id", sa.String(32), nullable=False),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("patch_hash", sa.String(64), nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("target_contract", sa.String(128), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("external_write_performed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes(
        "agent_sandbox_import_reviews",
        "sandbox_run_id",
        "mission_id",
        "decision",
        "patch_hash",
        "artifact_hash",
        "target_contract",
        "actor",
        "idempotency_key",
    )


def downgrade() -> None:
    op.drop_table("agent_sandbox_import_reviews")
    op.drop_table("agent_sandbox_artifacts")
    op.drop_table("agent_sandbox_runs")
