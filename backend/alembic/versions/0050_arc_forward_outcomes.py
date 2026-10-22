"""Persist finished BitPro race lane outcomes for research memory."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050_arc_forward_outcomes"
down_revision: str | None = "0049_arc_cognitive_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def upgrade() -> None:
    op.create_table(
        "arc_forward_outcomes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("target_id", sa.String(32), nullable=False),
        sa.Column("parent_strategy_id", sa.String(64), nullable=False),
        sa.Column("challenger_strategy_id", sa.String(64), nullable=False),
        sa.Column("slot_no", sa.Integer(), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("verdict_source", sa.String(32), nullable=False, server_default="race_judge"),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("evidence_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("lineage_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("mission_id", sa.String(64), nullable=True),
        sa.Column("candidate_id", sa.String(128), nullable=True),
        sa.Column("attempt_id", sa.String(128), nullable=True),
        sa.Column("changes_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("scope_json", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.UniqueConstraint(
            "target_id",
            "parent_strategy_id",
            "challenger_strategy_id",
            name="uq_arc_forward_outcome_pair",
        ),
    )
    op.create_index(
        "ix_arc_forward_outcomes_parent_strategy_id",
        "arc_forward_outcomes",
        ["parent_strategy_id"],
    )
    op.create_index(
        "ix_arc_forward_outcomes_challenger_strategy_id",
        "arc_forward_outcomes",
        ["challenger_strategy_id"],
    )
    op.create_index("ix_arc_forward_outcomes_verdict", "arc_forward_outcomes", ["verdict"])
    op.create_index(
        "ix_arc_forward_outcomes_lineage_status",
        "arc_forward_outcomes",
        ["lineage_status"],
    )
    op.create_index(
        "ix_arc_forward_outcomes_mission_id",
        "arc_forward_outcomes",
        ["mission_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_arc_forward_outcomes_mission_id", table_name="arc_forward_outcomes")
    op.drop_index("ix_arc_forward_outcomes_lineage_status", table_name="arc_forward_outcomes")
    op.drop_index("ix_arc_forward_outcomes_verdict", table_name="arc_forward_outcomes")
    op.drop_index(
        "ix_arc_forward_outcomes_challenger_strategy_id",
        table_name="arc_forward_outcomes",
    )
    op.drop_index(
        "ix_arc_forward_outcomes_parent_strategy_id",
        table_name="arc_forward_outcomes",
    )
    op.drop_table("arc_forward_outcomes")
