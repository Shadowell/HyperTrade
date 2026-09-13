"""Source-bound continuation checkpoints and immutable acceptance receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_evo_continuation"
down_revision: str | None = "0043_context_compaction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("arc_evolution_continuations", "arc_evolution_acceptance"):
        columns = [sa.Column("id", sa.String(64), primary_key=True)]
        if name == "arc_evolution_acceptance":
            columns.append(sa.Column("source_id", sa.String(64), nullable=False))
        op.create_table(
            name,
            *columns,
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    op.create_index(
        "ix_arc_evolution_acceptance_source_id", "arc_evolution_acceptance", ["source_id"]
    )


def downgrade() -> None:
    op.drop_table("arc_evolution_acceptance")
    op.drop_table("arc_evolution_continuations")
