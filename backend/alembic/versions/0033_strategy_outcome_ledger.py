"""reviewed strategy outcome and lesson ledger

Revision ID: 0033_strategy_outcome_ledger
Revises: 0032_effect_governance
"""

import sqlalchemy as sa
from alembic import op

revision = "0033_strategy_outcome_ledger"
down_revision = "0032_effect_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_outcomes",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("outcome_type", sa.String(length=48), nullable=False),
        sa.Column("strategy_lineage_id", sa.String(length=32), nullable=False),
        sa.Column("strategy_version_id", sa.String(length=32), nullable=False),
        sa.Column("strategy_card_id", sa.String(length=64), nullable=False),
        sa.Column("manifest_id", sa.String(length=32), nullable=False),
        sa.Column("experiment_execution_id", sa.String(length=32), nullable=False),
        sa.Column("mission_id", sa.String(length=32), nullable=False),
        sa.Column("observation_window_id", sa.String(length=32), nullable=False),
        sa.Column("corrects_id", sa.String(length=32), nullable=False),
        sa.Column("supersedes_id", sa.String(length=32), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("outcome_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "schema_version",
        "outcome_type",
        "strategy_lineage_id",
        "strategy_version_id",
        "strategy_card_id",
        "manifest_id",
        "experiment_execution_id",
        "mission_id",
        "observation_window_id",
        "corrects_id",
        "supersedes_id",
        "as_of",
        "settled_at",
        "content_hash",
        "idempotency_key",
        "created_by",
    ):
        op.create_index(f"ix_strategy_outcomes_{column}", "strategy_outcomes", [column])

    op.create_table(
        "strategy_lesson_candidates",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("stance", sa.String(length=24), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lesson_json", sa.JSON(), nullable=False),
        sa.Column("reviewed_by", sa.String(length=128), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "schema_version",
        "status",
        "stance",
        "target_type",
        "content_hash",
        "idempotency_key",
        "valid_until",
        "reviewed_by",
        "created_by",
    ):
        op.create_index(
            f"ix_strategy_lesson_candidates_{column}",
            "strategy_lesson_candidates",
            [column],
        )

    op.create_table(
        "strategy_lesson_reviews",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("lesson_id", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("decided_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("lesson_id", "decision", "idempotency_key", "decided_by"):
        op.create_index(f"ix_strategy_lesson_reviews_{column}", "strategy_lesson_reviews", [column])


def downgrade() -> None:
    op.drop_table("strategy_lesson_reviews")
    op.drop_table("strategy_lesson_candidates")
    op.drop_table("strategy_outcomes")
