"""bounded robustness validation runs and scenario results

Revision ID: 0015_robustness_validation
Revises: 0014_experiment_ledger
"""

import sqlalchemy as sa
from alembic import op

revision = "0015_robustness_validation"
down_revision = "0014_experiment_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "robustness_validation_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("experiment_execution_id", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("final_status", sa.String(32), nullable=False),
        sa.Column("gate_results_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("experiment_execution_id"),
    )
    for column in (
        "experiment_execution_id",
        "fingerprint",
        "policy_version",
        "policy_hash",
        "status",
        "final_status",
        "created_by",
    ):
        op.create_index(
            f"ix_robustness_validation_runs_{column}",
            "robustness_validation_runs",
            [column],
        )

    op.create_table(
        "robustness_scenario_results",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("validation_run_id", sa.String(32), nullable=False),
        sa.Column("scenario_id", sa.String(96), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("window_json", sa.JSON(), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("costs_json", sa.JSON(), nullable=False),
        sa.Column("regime", sa.String(64), nullable=False),
        sa.Column("result_ref_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("gate_results_json", sa.JSON(), nullable=False),
        sa.Column("error_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "validation_run_id", "scenario_id", name="uq_robustness_scenario"
        ),
    )
    for column in ("validation_run_id", "scenario_id", "kind", "status", "regime"):
        op.create_index(
            f"ix_robustness_scenario_results_{column}",
            "robustness_scenario_results",
            [column],
        )


def downgrade() -> None:
    op.drop_table("robustness_scenario_results")
    op.drop_table("robustness_validation_runs")
