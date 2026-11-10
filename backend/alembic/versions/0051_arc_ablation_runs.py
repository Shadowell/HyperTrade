"""Persist per-change ablation of forward losers (development-window backtests only).

Ablation records are observations, not causal verdicts. Neither table holds a
foreign key to ``arc_forward_outcomes``: correcting a ledger row must not rewrite
or delete the backtest evidence already produced for it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051_arc_ablation_runs"
down_revision: str | None = "0050_arc_forward_outcomes"
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


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    # Idempotent on purpose: developer databases already got these tables from
    # ``create_all``, and a partially applied migration must be safe to re-run.
    if "arc_ablation_runs" not in _tables():
        op.create_table(
            "arc_ablation_runs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("outcome_id", sa.String(64), nullable=False),
            sa.Column("target_id", sa.String(32), nullable=False),
            sa.Column("parent_strategy_id", sa.String(64), nullable=False),
            sa.Column("challenger_strategy_id", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("reason", sa.String(64), nullable=False, server_default=""),
            sa.Column("message", sa.Text(), nullable=False, server_default=""),
            sa.Column("research_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("window_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("plan_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("result_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint(
                "target_id",
                "challenger_strategy_id",
                name="uq_arc_ablation_run_challenger",
            ),
            sa.UniqueConstraint("outcome_id", name="uq_arc_ablation_run_outcome"),
        )

    run_indexes = _indexes("arc_ablation_runs")
    for name, columns in (
        ("ix_arc_ablation_runs_parent_strategy_id", ["parent_strategy_id"]),
        ("ix_arc_ablation_runs_status", ["status"]),
        ("ix_arc_ablation_runs_next_check_at", ["next_check_at"]),
    ):
        if name not in run_indexes:
            op.create_index(name, "arc_ablation_runs", columns)

    if "arc_ablation_steps" not in _tables():
        op.create_table(
            "arc_ablation_steps",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("step_key", sa.String(160), nullable=False),
            sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("change_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("reason", sa.String(128), nullable=False, server_default=""),
            sa.Column("request_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("checkpoint_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("result_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("charged_at", sa.DateTime(timezone=True), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("run_id", "step_key", name="uq_arc_ablation_step"),
        )

    step_indexes = _indexes("arc_ablation_steps")
    for name, columns in (
        ("ix_arc_ablation_steps_run_id", ["run_id"]),
        ("ix_arc_ablation_steps_status", ["status"]),
        ("ix_arc_ablation_steps_request_hash", ["request_hash"]),
        ("ix_arc_ablation_steps_charged_at", ["charged_at"]),
    ):
        if name not in step_indexes:
            op.create_index(name, "arc_ablation_steps", columns)


def downgrade() -> None:
    tables = _tables()
    if "arc_ablation_steps" in tables:
        op.drop_table("arc_ablation_steps")
    if "arc_ablation_runs" in tables:
        op.drop_table("arc_ablation_runs")
