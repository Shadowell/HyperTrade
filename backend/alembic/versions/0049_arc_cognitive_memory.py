"""Persist ARC hypothesis, episodic, and semantic cognitive memory."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049_arc_cognitive_memory"
down_revision: str | None = "0048_arc_mission_events"
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
        "arc_hypothesis_nodes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("tree_id", sa.String(64), nullable=False),
        sa.Column(
            "parent_id",
            sa.String(32),
            sa.ForeignKey("arc_hypothesis_nodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(96), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_regimes_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("mutation_type", sa.String(32), nullable=False, server_default="init"),
        sa.Column("strategy_digest", sa.String(64), nullable=True),
        sa.Column("experiment_id", sa.String(64), nullable=True),
        sa.Column("benchmark_relative_pnl", sa.Numeric(10, 4), nullable=True),
        sa.Column("sharpe_ratio", sa.Numeric(8, 4), nullable=True),
        sa.Column("max_drawdown", sa.Numeric(8, 4), nullable=True),
        sa.Column("ic_mean", sa.Numeric(8, 4), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="proposed"),
        sa.Column("prune_reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.CheckConstraint("depth >= 0", name="ck_arc_hypothesis_depth"),
        sa.UniqueConstraint("idempotency_key", name="uq_arc_hypothesis_idempotency"),
    )
    op.create_index(
        "ix_arc_hypothesis_tree_parent",
        "arc_hypothesis_nodes",
        ["tree_id", "parent_id"],
    )
    op.create_index("ix_arc_hypothesis_status", "arc_hypothesis_nodes", ["status"])
    op.create_index(
        "ix_arc_hypothesis_strategy_digest", "arc_hypothesis_nodes", ["strategy_digest"]
    )
    op.create_index(
        "ix_arc_hypothesis_experiment_id", "arc_hypothesis_nodes", ["experiment_id"]
    )
    op.create_index(
        "ix_arc_hypothesis_idempotency_key", "arc_hypothesis_nodes", ["idempotency_key"]
    )

    op.create_table(
        "arc_episodic_memories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("mission_id", sa.String(64), nullable=False),
        sa.Column("experiment_id", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(96), nullable=False),
        sa.Column("symbols_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("timeframe", sa.String(16), nullable=False, server_default=""),
        sa.Column("market_regime", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("metrics_delta_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("raw_evidence_ref", sa.String(128), nullable=False, server_default=""),
        sa.Column("reflection_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("embedding_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.UniqueConstraint("idempotency_key", name="uq_arc_episode_idempotency"),
    )
    op.create_index("ix_arc_episode_mission", "arc_episodic_memories", ["mission_id"])
    op.create_index("ix_arc_episode_experiment", "arc_episodic_memories", ["experiment_id"])
    op.create_index("ix_arc_episode_timeframe", "arc_episodic_memories", ["timeframe"])
    op.create_index(
        "ix_arc_episode_regime_event",
        "arc_episodic_memories",
        ["market_regime", "event_type"],
    )
    op.create_index(
        "ix_arc_episode_idempotency_key", "arc_episodic_memories", ["idempotency_key"]
    )

    op.create_table(
        "arc_semantic_assertions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "assertion_type",
            sa.String(32),
            nullable=False,
            server_default="causal_heuristic",
        ),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("applicable_regimes_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0.5000"),
        sa.Column("derived_from_episodes_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("counter_evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column(
            "replaced_by",
            sa.String(32),
            sa.ForeignKey("arc_semantic_assertions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("embedding_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("evidence_set_hash", sa.String(64), nullable=True),
        sa.Column("distillation_version", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("idempotency_key", sa.String(96), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_arc_semantic_confidence"
        ),
        sa.CheckConstraint(
            "counter_evidence_count >= 0", name="ck_arc_semantic_counter_evidence"
        ),
        sa.CheckConstraint("version >= 1", name="ck_arc_semantic_version"),
        sa.UniqueConstraint("idempotency_key", name="uq_arc_semantic_idempotency"),
        sa.UniqueConstraint(
            "evidence_set_hash",
            "distillation_version",
            name="uq_arc_semantic_evidence_version",
        ),
    )
    op.create_index("ix_arc_semantic_status", "arc_semantic_assertions", ["status"])
    op.create_index("ix_arc_semantic_type", "arc_semantic_assertions", ["assertion_type"])
    op.create_index("ix_arc_semantic_replaced_by", "arc_semantic_assertions", ["replaced_by"])
    op.create_index(
        "ix_arc_semantic_evidence_set_hash", "arc_semantic_assertions", ["evidence_set_hash"]
    )
    op.create_index(
        "ix_arc_semantic_idempotency_key", "arc_semantic_assertions", ["idempotency_key"]
    )


def downgrade() -> None:
    op.drop_table("arc_semantic_assertions")
    op.drop_table("arc_episodic_memories")
    op.drop_table("arc_hypothesis_nodes")
