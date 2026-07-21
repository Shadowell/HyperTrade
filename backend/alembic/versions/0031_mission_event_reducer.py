"""canonical Mission event reducer and completion proof

Revision ID: 0031_mission_event_reducer
Revises: 0030_thread_worker_fencing
"""

import sqlalchemy as sa
from alembic import op

revision = "0031_mission_event_reducer"
down_revision = "0030_thread_worker_fencing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_missions",
        sa.Column("event_protocol_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "agent_missions",
        sa.Column(
            "replay_status",
            sa.String(length=32),
            nullable=False,
            server_default="legacy_non_replayable",
        ),
    )
    op.add_column(
        "agent_missions",
        sa.Column("projection_hash", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "agent_missions",
        sa.Column("quarantine_reason", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "agent_missions",
        sa.Column("completion_proof_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "agent_missions",
        sa.Column("lease_fencing_token", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_agent_missions_replay_status", "agent_missions", ["replay_status"])
    op.create_index("ix_agent_missions_projection_hash", "agent_missions", ["projection_hash"])

    op.add_column(
        "agent_mission_events",
        sa.Column("aggregate_type", sa.String(length=32), nullable=False, server_default="mission"),
    )
    op.add_column(
        "agent_mission_events",
        sa.Column("aggregate_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_mission_events",
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "agent_mission_events",
        sa.Column("reducer_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_mission_events",
        sa.Column("causation_id", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "agent_mission_events",
        sa.Column("correlation_id", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "agent_mission_events",
        sa.Column(
            "policy_snapshot_hash", sa.String(length=64), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "agent_mission_events",
        sa.Column("payload_hash", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "agent_mission_events",
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_mission_events",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_mission_events",
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE agent_mission_events "
        "SET aggregate_version = sequence, occurred_at = created_at, recorded_at = created_at"
    )
    op.alter_column("agent_mission_events", "occurred_at", nullable=False)
    op.alter_column("agent_mission_events", "recorded_at", nullable=False)
    op.create_unique_constraint(
        "uq_agent_mission_event_version",
        "agent_mission_events",
        ["mission_id", "aggregate_version"],
    )
    op.create_index(
        "ix_agent_mission_events_payload_hash", "agent_mission_events", ["payload_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_mission_events_payload_hash", table_name="agent_mission_events")
    op.drop_constraint(
        "uq_agent_mission_event_version", "agent_mission_events", type_="unique"
    )
    for column in (
        "recorded_at",
        "occurred_at",
        "fencing_token",
        "payload_hash",
        "policy_snapshot_hash",
        "correlation_id",
        "causation_id",
        "reducer_version",
        "schema_version",
        "aggregate_version",
        "aggregate_type",
    ):
        op.drop_column("agent_mission_events", column)
    op.drop_index("ix_agent_missions_projection_hash", table_name="agent_missions")
    op.drop_index("ix_agent_missions_replay_status", table_name="agent_missions")
    for column in (
        "lease_fencing_token",
        "completion_proof_json",
        "quarantine_reason",
        "projection_hash",
        "replay_status",
        "event_protocol_version",
    ):
        op.drop_column("agent_missions", column)
