"""governed memory assertions and code-free skill lifecycle

Revision ID: 0017_memory_skills
Revises: 0016_research_triggers
"""

import sqlalchemy as sa
from alembic import op

revision = "0017_memory_skills"
down_revision = "0016_research_triggers"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _indexes(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "memory_assertions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("source_evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(10, 8), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("linked_memory_id", sa.String(32), nullable=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("reviewed_by", sa.String(128), nullable=False),
        sa.Column("review_reason", sa.Text(), nullable=False),
        sa.Column("audit_json", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "memory_assertions",
        "schema_version",
        "valid_until",
        "status",
        "content_hash",
        "idempotency_key",
        "linked_memory_id",
        "created_by",
    )

    op.create_table(
        "memory_assertion_relations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("from_assertion_id", sa.String(32), nullable=False),
        sa.Column("to_assertion_id", sa.String(32), nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("created_by", sa.String(128), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "from_assertion_id",
            "to_assertion_id",
            "relation_type",
            name="uq_memory_assertion_relation",
        ),
    )
    _indexes(
        "memory_assertion_relations",
        "from_assertion_id",
        "to_assertion_id",
        "relation_type",
        "idempotency_key",
        "created_by",
    )

    op.create_table(
        "memory_assertion_reviews",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("assertion_id", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("decided_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "memory_assertion_reviews",
        "assertion_id",
        "decision",
        "idempotency_key",
        "decided_by",
    )

    op.create_table(
        "skill_proposals",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("skill_key", sa.String(96), nullable=False),
        sa.Column("base_release_id", sa.String(32), nullable=True),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("static_check_json", sa.JSON(), nullable=False),
        sa.Column("diff_text", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("proposed_by", sa.String(128), nullable=False),
        sa.Column("audit_json", sa.JSON(), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "skill_proposals",
        "skill_key",
        "base_release_id",
        "definition_hash",
        "status",
        "idempotency_key",
        "proposed_by",
    )

    op.create_table(
        "skill_evaluations",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("proposal_id", sa.String(32), nullable=False),
        sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("suite_version", sa.String(96), nullable=False),
        sa.Column("baseline_id", sa.String(128), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("runtime", sa.String(64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("evaluated_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "skill_evaluations",
        "proposal_id",
        "proposal_hash",
        "status",
        "suite_version",
        "baseline_id",
        "artifact_hash",
        "runtime",
        "idempotency_key",
        "evaluated_by",
    )

    op.create_table(
        "skill_approvals",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("proposal_id", sa.String(32), nullable=False),
        sa.Column("release_id", sa.String(32), nullable=False),
        sa.Column("target_release_id", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("decided_by", sa.String(128), nullable=False),
        *_timestamps(),
    )
    _indexes(
        "skill_approvals",
        "proposal_id",
        "release_id",
        "target_release_id",
        "decision",
        "idempotency_key",
        "decided_by",
    )

    op.create_table(
        "skill_releases",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("skill_key", sa.String(96), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.String(32), nullable=False, unique=True),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("approved_by", sa.String(128), nullable=False),
        sa.Column("approval_reason", sa.Text(), nullable=False),
        sa.Column("audit_json", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("skill_key", "version", name="uq_skill_release_version"),
    )
    _indexes(
        "skill_releases",
        "skill_key",
        "proposal_id",
        "definition_hash",
        "status",
        "approved_by",
    )

    op.create_table(
        "skill_active_pointers",
        sa.Column("skill_key", sa.String(96), primary_key=True),
        sa.Column("active_release_id", sa.String(32), nullable=False, unique=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        *_timestamps(),
    )
    _indexes("skill_active_pointers", "active_release_id", "updated_by")


def downgrade() -> None:
    for table in (
        "skill_active_pointers",
        "skill_releases",
        "skill_approvals",
        "skill_evaluations",
        "skill_proposals",
        "memory_assertion_reviews",
        "memory_assertion_relations",
        "memory_assertions",
    ):
        op.drop_table(table)
