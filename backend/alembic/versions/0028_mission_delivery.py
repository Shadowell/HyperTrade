"""mission idempotency and delivery identity

Revision ID: 0028_mission_delivery
Revises: 0027_agent_sandbox
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_mission_delivery"
down_revision = "0027_agent_sandbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_missions",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "agent_missions",
        sa.Column("request_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE agent_missions SET idempotency_key = 'legacy:' || id "
        "WHERE idempotency_key IS NULL"
    )
    op.execute(
        "UPDATE agent_missions SET request_hash = 'legacy:' || id "
        "WHERE request_hash IS NULL"
    )
    op.alter_column("agent_missions", "idempotency_key", nullable=False)
    op.alter_column("agent_missions", "request_hash", nullable=False)
    op.create_unique_constraint(
        "uq_agent_missions_idempotency_key", "agent_missions", ["idempotency_key"]
    )
    op.create_index("ix_agent_missions_request_hash", "agent_missions", ["request_hash"])


def downgrade() -> None:
    op.drop_index("ix_agent_missions_request_hash", table_name="agent_missions")
    op.drop_constraint("uq_agent_missions_idempotency_key", "agent_missions", type_="unique")
    op.drop_column("agent_missions", "request_hash")
    op.drop_column("agent_missions", "idempotency_key")
