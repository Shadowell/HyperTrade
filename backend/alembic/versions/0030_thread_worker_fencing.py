"""canonical Turn worker fencing

Revision ID: 0030_thread_worker_fencing
Revises: 0029_canonical_thread_turn
"""

import sqlalchemy as sa
from alembic import op

revision = "0030_thread_worker_fencing"
down_revision = "0029_canonical_thread_turn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_thread_leases",
        sa.Column("thread_id", sa.String(length=32), primary_key=True),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_thread_leases_worker_id", "agent_thread_leases", ["worker_id"])


def downgrade() -> None:
    op.drop_table("agent_thread_leases")
