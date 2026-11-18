"""Add expression index on arc_missions for BitPro source_strategy_id lookups."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053_arc_mission_source_idx"
down_revision: str | None = "0052_worker_heartbeats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_arc_missions_bitpro_source_strategy "
                "ON arc_missions ("
                "(projection_json->'goal'->>'platform'), "
                "(projection_json->'goal'->'evolution_context'->>'source_strategy_id'), "
                "updated_at DESC, "
                "mission_id DESC"
                ")"
            )
        )
    else:
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_arc_missions_bitpro_source_strategy "
                "ON arc_missions ("
                "CAST(json_extract(projection_json, '$.goal.platform') AS TEXT), "
                "CAST(json_extract(projection_json, "
                "'$.goal.evolution_context.source_strategy_id') AS TEXT), "
                "updated_at DESC, "
                "mission_id DESC"
                ")"
            )
        )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_arc_missions_bitpro_source_strategy"))
