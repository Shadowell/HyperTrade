"""arc mission revision counter for cross-process writes

Revision ID: 0041_arc_mission_rev
Revises: 0040_arc_missions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041_arc_mission_rev"
down_revision: str | None = "0040_arc_missions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "arc_missions",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("arc_missions", "revision")
