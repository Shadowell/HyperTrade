"""bounded BitPro strategy evidence references

Revision ID: 0034_bitpro_strategy_evidence
Revises: 0033_strategy_outcome_ledger
"""

import sqlalchemy as sa
from alembic import op

revision = "0034_bitpro_strategy_evidence"
down_revision = "0033_strategy_outcome_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bitpro_strategy_evidence_records",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("evidence_type", sa.String(length=48), nullable=False),
        sa.Column("source_layer", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("source_hash", sa.String(length=80), nullable=False),
        sa.Column("content_hash", sa.String(length=80), nullable=False, unique=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("refs_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "schema_version",
        "evidence_type",
        "source_layer",
        "source_id",
        "source_hash",
        "content_hash",
        "created_by",
    ):
        op.create_index(
            f"ix_bitpro_strategy_evidence_records_{column}",
            "bitpro_strategy_evidence_records",
            [column],
        )


def downgrade() -> None:
    op.drop_table("bitpro_strategy_evidence_records")
