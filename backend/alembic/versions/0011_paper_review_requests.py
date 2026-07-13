"""paper review requests

Revision ID: 0011_paper_review_requests
Revises: 0010_paper_promotions
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_paper_review_requests"
down_revision = "0010_paper_promotions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_review_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("promotion_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_paper_review_requests_promotion_id", "paper_review_requests", ["promotion_id"]
    )
    op.create_index("ix_paper_review_requests_status", "paper_review_requests", ["status"])
    op.create_index("ix_paper_review_requests_action", "paper_review_requests", ["action"])


def downgrade() -> None:
    op.drop_table("paper_review_requests")
