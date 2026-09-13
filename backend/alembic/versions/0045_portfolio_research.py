"""Immutable portfolio research manifests and comparison receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045_portfolio_research"
down_revision: str | None = "0044_evo_continuation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_research_records",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("portfolio_research_records")
