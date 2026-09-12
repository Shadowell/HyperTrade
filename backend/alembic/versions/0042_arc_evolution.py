"""ARC autonomous evolution scheduling and diagnostic receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042_arc_evolution"
down_revision: str | None = "0041_arc_mission_rev"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "arc_evolution_control",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "arc_evolution_cycles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_arc_evolution_cycles_status", "arc_evolution_cycles", ["status"])


def downgrade() -> None:
    op.drop_table("arc_evolution_cycles")
    op.drop_table("arc_evolution_control")
