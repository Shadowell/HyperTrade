"""immutable experiment manifest and execution ledger

Revision ID: 0014_experiment_ledger
Revises: 0013_research_evidence_v2
"""

import sqlalchemy as sa
from alembic import op

revision = "0014_experiment_ledger"
down_revision = "0013_research_evidence_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_manifests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("strategy_key", sa.String(128), nullable=False),
        sa.Column("mandate_id", sa.String(32), nullable=False),
        sa.Column("research_job_id", sa.String(32), nullable=False),
        sa.Column("canonical_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("fingerprint"),
    )
    for column in (
        "schema_version",
        "fingerprint",
        "strategy_key",
        "mandate_id",
        "research_job_id",
        "created_by",
    ):
        op.create_index(f"ix_experiment_manifests_{column}", "experiment_manifests", [column])

    op.create_table(
        "experiment_executions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("manifest_id", sa.String(32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("research_job_id", sa.String(32), nullable=False),
        sa.Column("retry_of_id", sa.String(32), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("force_reason", sa.Text(), nullable=False),
        sa.Column("external_refs_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("artifact_manifest_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("error_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint(
            "manifest_id",
            "attempt",
            name="uq_experiment_execution_attempt",
        ),
    )
    for column in (
        "manifest_id",
        "status",
        "task_id",
        "research_job_id",
        "retry_of_id",
        "idempotency_key",
        "created_by",
    ):
        op.create_index(f"ix_experiment_executions_{column}", "experiment_executions", [column])

    op.create_table(
        "experiment_evidence_links",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("execution_id", sa.String(32), nullable=False),
        sa.Column("evidence_id", sa.String(32), nullable=False),
        sa.Column("evidence_kind", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "execution_id",
            "evidence_id",
            name="uq_experiment_evidence_link",
        ),
    )
    for column in ("execution_id", "evidence_id", "evidence_kind", "created_by"):
        op.create_index(
            f"ix_experiment_evidence_links_{column}",
            "experiment_evidence_links",
            [column],
        )


def downgrade() -> None:
    op.drop_table("experiment_evidence_links")
    op.drop_table("experiment_executions")
    op.drop_table("experiment_manifests")
