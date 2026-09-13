"""Private bounded model-context recovery snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043_context_compaction"
down_revision: str | None = "0042_arc_evolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_context_records",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("record_json", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_context_records_run_id", "provider_context_records", ["run_id"])
    op.create_index(
        "ix_provider_context_records_snapshot_hash", "provider_context_records", ["snapshot_hash"]
    )

    op.create_index(
        "ix_provider_context_records_expires_at", "provider_context_records", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_provider_context_records_expires_at", table_name="provider_context_records")
    op.drop_index(
        "ix_provider_context_records_snapshot_hash", table_name="provider_context_records"
    )
    op.drop_index("ix_provider_context_records_run_id", table_name="provider_context_records")
    op.drop_table("provider_context_records")
