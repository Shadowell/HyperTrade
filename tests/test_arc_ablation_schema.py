"""Ablation schema: config bounds, idempotent migration, ORM/migration parity, uniques."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from hypertrade.arc.evolution import EvolutionConfig
from hypertrade.arc.evolution_models import ArcAblationRun, ArcAblationStep
from hypertrade.db import Database
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

TABLES = ("arc_ablation_runs", "arc_ablation_steps")
RUN_INDEXES = {
    "ix_arc_ablation_runs_parent_strategy_id",
    "ix_arc_ablation_runs_status",
    "ix_arc_ablation_runs_next_check_at",
}
STEP_INDEXES = {
    "ix_arc_ablation_steps_run_id",
    "ix_arc_ablation_steps_status",
    "ix_arc_ablation_steps_request_hash",
    "ix_arc_ablation_steps_charged_at",
}


def _migration():
    path = Path(__file__).parents[1] / "backend/alembic/versions/0051_arc_ablation_runs.py"
    spec = importlib.util.spec_from_file_location("arc_ablation_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schema(database: Database) -> dict[str, dict[str, set[str]]]:
    inspector = inspect(database.engine)
    return {
        table: {
            "columns": {column["name"] for column in inspector.get_columns(table)},
            "uniques": {
                item["name"] for item in inspector.get_unique_constraints(table)
            },
            "indexes": {item["name"] for item in inspector.get_indexes(table)},
        }
        for table in TABLES
    }


def test_evolution_config_ablation_defaults_and_round_trip() -> None:
    config = EvolutionConfig.model_validate(
        {
            "enabled": True,
            "max_research_per_day": 32,
            "interval_minutes": 30,
            "target_id": "bitpro",
        }
    )

    assert config.ablation_enabled is True
    assert config.ablation_max_backtests_per_day == 6
    assert config.ablation_max_backtests_per_loser == 6
    assert EvolutionConfig.model_validate(config.model_dump(mode="json")) == config


@pytest.mark.parametrize(
    "overrides",
    [
        {"ablation_max_backtests_per_loser": 2},
        {"ablation_max_backtests_per_loser": 7},
        {"ablation_max_backtests_per_day": 0},
        {"ablation_max_backtests_per_day": 61},
        {"ablation_foo": 1},
    ],
)
def test_evolution_config_rejects_out_of_range_ablation_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        EvolutionConfig.model_validate(overrides)


def test_ablation_migration_is_idempotent_and_reversible(tmp_path: Path) -> None:
    migration = _migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")

    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        migration.upgrade()
        inspector = inspect(connection)
        assert set(TABLES).issubset(inspector.get_table_names())
        assert {
            item["name"] for item in inspector.get_unique_constraints("arc_ablation_runs")
        }.issuperset({"uq_arc_ablation_run_challenger", "uq_arc_ablation_run_outcome"})
        assert {
            item["name"] for item in inspector.get_unique_constraints("arc_ablation_steps")
        }.issuperset({"uq_arc_ablation_step"})
        assert RUN_INDEXES.issubset(
            {item["name"] for item in inspector.get_indexes("arc_ablation_runs")}
        )
        assert STEP_INDEXES.issubset(
            {item["name"] for item in inspector.get_indexes("arc_ablation_steps")}
        )

        migration.downgrade()
        assert not set(TABLES) & set(inspect(connection).get_table_names())
        migration.downgrade()
        migration.upgrade()
        assert set(TABLES).issubset(inspect(connection).get_table_names())

    engine.dispose()


def test_ablation_migration_accepts_create_all_database(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'dev.db'}")
    db.create_all()
    migration = _migration()

    with db.engine.begin() as connection, Operations.context(
        MigrationContext.configure(connection)
    ):
        migration.upgrade()

    assert set(TABLES).issubset(set(inspect(db.engine).get_table_names()))
    db.engine.dispose()


def test_ablation_migration_matches_orm_schema(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'orm.db'}")
    db.create_all()
    orm_schema = _schema(db)
    db.engine.dispose()

    migration = _migration()
    migrated = Database(f"sqlite:///{tmp_path / 'migrated.db'}")
    with migrated.engine.begin() as connection, Operations.context(
        MigrationContext.configure(connection)
    ):
        migration.upgrade()
    assert _schema(migrated) == orm_schema
    migrated.engine.dispose()


def test_ablation_unique_constraints() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    run = {
        "outcome_id": "outcome-1",
        "target_id": "bitpro",
        "parent_strategy_id": "41",
        "challenger_strategy_id": "42",
    }

    with db.session() as session:
        session.add(ArcAblationRun(id="run-1", **run))
        session.add(
            ArcAblationStep(
                id="step-1", run_id="run-1", step_key="baseline:41", kind="baseline"
            )
        )

    with pytest.raises(IntegrityError), db.session() as session:
        session.add(
            ArcAblationRun(
                id="run-2",
                **{**run, "outcome_id": "outcome-2", "challenger_strategy_id": "42"},
            )
        )

    with pytest.raises(IntegrityError), db.session() as session:
        session.add(
            ArcAblationRun(
                id="run-3",
                **{**run, "challenger_strategy_id": "43"},
            )
        )

    with pytest.raises(IntegrityError), db.session() as session:
        session.add(
            ArcAblationStep(
                id="step-2", run_id="run-1", step_key="baseline:41", kind="baseline"
            )
        )
