"""Append-only ARC mission events.

Upgrade is schema-only: deploy runs it while the previous api/worker still serve, and
they keep writing events inline, which the new readers merge. Moving history is the
separate, verified ``python -m hypertrade.arc.event_migration migrate`` step.
Downgrade folds journalled events back into ``projection_json`` before dropping.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048_arc_mission_events"
down_revision: str | None = "0047_arc_runtime_journal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "arc_mission_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mission_id", sa.String(64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mission_id", "seq", name="uq_arc_mission_events_seq"),
        sa.UniqueConstraint("mission_id", "event_id", name="uq_arc_mission_events_event_id"),
    )
    op.create_index("ix_arc_mission_events_mission_id", "arc_mission_events", ["mission_id"])
    op.create_index("ix_arc_mission_events_event_type", "arc_mission_events", ["event_type"])
    op.add_column(
        "arc_missions",
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
    )


def _json(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


def downgrade() -> None:
    bind = op.get_bind()
    missions = sa.table(
        "arc_missions",
        sa.column("mission_id", sa.String()),
        sa.column("projection_json", sa.JSON()),
    )
    events = sa.table(
        "arc_mission_events",
        sa.column("mission_id", sa.String()),
        sa.column("seq", sa.Integer()),
        sa.column("event_json", sa.JSON()),
    )
    mission_ids = [
        row[0] for row in bind.execute(sa.select(events.c.mission_id).distinct()).all()
    ]
    for mission_id in mission_ids:
        stored = [
            _json(row[0])
            for row in bind.execute(
                sa.select(events.c.event_json)
                .where(events.c.mission_id == mission_id)
                .order_by(events.c.seq)
            ).all()
        ]
        projection = _json(
            bind.execute(
                sa.select(missions.c.projection_json).where(missions.c.mission_id == mission_id)
            ).scalar_one()
        )
        assert isinstance(projection, dict)
        known = {event["event_id"] for event in stored if isinstance(event, dict)}
        inline = [e for e in projection.get("events") or [] if e.get("event_id") not in known]
        bind.execute(
            missions.update()
            .where(missions.c.mission_id == mission_id)
            .values(projection_json={**projection, "events": stored + inline})
        )
    op.drop_column("arc_missions", "event_count")
    op.drop_table("arc_mission_events")
