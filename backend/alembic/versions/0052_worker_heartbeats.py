"""Add the worker liveness table read by /api/healthz.

One row per worker process, rewritten every few seconds by the worker itself. It holds only
operational telemetry (timestamps, counters, exception *types*); nothing in it is research or
trading state, so it can be dropped or truncated at any time without losing evidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052_worker_heartbeats"
down_revision: str | None = "0051_arc_ablation_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    # Idempotent on purpose: developer databases already got this table from ``create_all``, and
    # a partially applied migration must be safe to re-run.
    if "worker_heartbeats" not in _tables():
        op.create_table(
            "worker_heartbeats",
            sa.Column("worker_id", sa.String(64), primary_key=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("build_sha", sa.String(40), nullable=True),
            sa.Column("components_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("process_json", sa.JSON(), nullable=False, server_default="{}"),
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
    if "ix_worker_heartbeats_heartbeat_at" not in _indexes("worker_heartbeats"):
        op.create_index(
            "ix_worker_heartbeats_heartbeat_at", "worker_heartbeats", ["heartbeat_at"]
        )


def downgrade() -> None:
    if "worker_heartbeats" in _tables():
        op.drop_table("worker_heartbeats")
