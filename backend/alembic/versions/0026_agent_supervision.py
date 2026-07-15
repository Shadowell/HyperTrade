"""bounded multi-agent supervision ledger

Revision ID: 0026_agent_supervision
Revises: 0025_agent_context_artifacts
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_agent_supervision"
down_revision = "0025_agent_context_artifacts"
branch_labels = None
depends_on = None


def _indexes(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "agent_assignments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("role_id", sa.String(64), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("capability_id", sa.String(160), nullable=False),
        sa.Column("depends_on_json", sa.JSON(), nullable=False),
        sa.Column("context_pack_refs_json", sa.JSON(), nullable=False),
        sa.Column("artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("reservation_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("agent_assignments", "mission_id", "role_id", "capability_id", "status")
    op.create_table(
        "agent_budget_reservations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("assignment_id", sa.String(32), nullable=False, unique=True),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("agent_budget_reservations", "mission_id", "assignment_id", "status")
    op.create_table(
        "agent_handoffs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("assignment_id", sa.String(32), nullable=False, unique=True),
        sa.Column("role_id", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("claims_json", sa.JSON(), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("artifact_refs_json", sa.JSON(), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("agent_handoffs", "mission_id", "assignment_id", "role_id", "output_hash")
    op.create_table(
        "agent_conflicts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(32), nullable=False),
        sa.Column("claim_key", sa.String(160), nullable=False),
        sa.Column("values_json", sa.JSON(), nullable=False),
        sa.Column("source_refs_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _indexes("agent_conflicts", "mission_id", "claim_key", "status")


def downgrade() -> None:
    op.drop_table("agent_conflicts")
    op.drop_table("agent_handoffs")
    op.drop_table("agent_budget_reservations")
    op.drop_table("agent_assignments")
