"""reviewed capability catalog and typed tool observations

Revision ID: 0024_agent_capabilities
Revises: 0023_agent_missions
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_agent_capabilities"
down_revision = "0023_agent_missions"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _indexes(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "agent_capability_snapshots",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("capability_id", sa.String(160), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("health", sa.String(32), nullable=False),
        sa.Column("contract_hash", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("reviewed_by", sa.String(128), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("capability_id", "version", name="uq_agent_capability_version"),
        *_timestamps(),
    )
    _indexes(
        "agent_capability_snapshots",
        "capability_id",
        "review_status",
        "health",
        "contract_hash",
        "policy_hash",
        "fresh_until",
    )
    op.create_table(
        "agent_capability_proposals",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("capability_id", sa.String(160), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("discovered_from", sa.Text(), nullable=False),
        sa.Column("discovery_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "agent_capability_proposals",
        "capability_id",
        "discovery_hash",
        "status",
        "created_by",
    )
    op.create_table(
        "agent_capability_reviews",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("proposal_id", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes(
        "agent_capability_reviews",
        "proposal_id",
        "decision",
        "actor",
        "idempotency_key",
    )
    op.create_table(
        "agent_tool_observations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("request_id", sa.String(32), nullable=False, unique=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("step_id", sa.String(64), nullable=False),
        sa.Column("capability_id", sa.String(160), nullable=False),
        sa.Column("capability_version", sa.String(32), nullable=False),
        sa.Column("contract_hash", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_preview_json", sa.JSON(), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("error_category", sa.String(32), nullable=False),
        sa.Column("retry_action", sa.String(32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes(
        "agent_tool_observations",
        "request_id",
        "mission_id",
        "step_id",
        "capability_id",
        "contract_hash",
        "policy_hash",
        "status",
        "result_hash",
        "error_category",
        "retry_action",
        "idempotency_key",
    )
    op.create_table(
        "agent_capability_circuits",
        sa.Column("capability_id", sa.String(160), primary_key=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    _indexes("agent_capability_circuits", "state", "retry_after")


def downgrade() -> None:
    op.drop_table("agent_capability_circuits")
    op.drop_table("agent_tool_observations")
    op.drop_table("agent_capability_reviews")
    op.drop_table("agent_capability_proposals")
    op.drop_table("agent_capability_snapshots")
