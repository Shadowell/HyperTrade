"""durable ARC mission projections

Revision ID: 0040_arc_missions
Revises: 0039_regime_shadow_v2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_arc_missions"
down_revision: str | None = "0039_regime_shadow_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "arc_missions",
        sa.Column("mission_id", sa.String(64), primary_key=True),
        sa.Column("state", sa.String(48), nullable=False),
        sa.Column("projection_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_arc_missions_state", "arc_missions", ["state"])


def downgrade() -> None:
    op.drop_index("ix_arc_missions_state", table_name="arc_missions")
    op.drop_table("arc_missions")
