from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from hypertrade.arc.evolution_models import ArcForwardOutcome
from hypertrade.db import Database
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError

COLUMNS = {
    "id",
    "target_id",
    "parent_strategy_id",
    "challenger_strategy_id",
    "slot_no",
    "generation",
    "verdict",
    "verdict_source",
    "ended_at",
    "metrics_json",
    "evidence_sha256",
    "lineage_status",
    "mission_id",
    "candidate_id",
    "attempt_id",
    "changes_json",
    "scope_json",
    "created_at",
    "updated_at",
}
INDEXES = {
    "ix_arc_forward_outcomes_parent_strategy_id",
    "ix_arc_forward_outcomes_challenger_strategy_id",
    "ix_arc_forward_outcomes_verdict",
    "ix_arc_forward_outcomes_lineage_status",
    "ix_arc_forward_outcomes_mission_id",
}


def _migration():
    path = (
        Path(__file__).parents[1] / "backend/alembic/versions/0050_arc_forward_outcomes.py"
    )
    spec = importlib.util.spec_from_file_location("arc_forward_outcomes_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_forward_outcome_migration_creates_and_removes_only_its_table(tmp_path: Path) -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = _migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        inspector = inspect(connection)
        assert inspector.get_table_names() == ["arc_forward_outcomes"]
        assert {column["name"] for column in inspector.get_columns(
            "arc_forward_outcomes"
        )} == COLUMNS
        assert inspector.get_pk_constraint("arc_forward_outcomes")["constrained_columns"] == [
            "id"
        ]
        uniques = {
            item["name"]
            for item in inspector.get_unique_constraints("arc_forward_outcomes")
        }
        assert "uq_arc_forward_outcome_pair" in uniques
        indexes = {
            item["name"] for item in inspector.get_indexes("arc_forward_outcomes")
        }
        assert INDEXES.issubset(indexes)

        migration.downgrade()
        assert inspect(connection).get_table_names() == []
    engine.dispose()


def test_forward_outcome_round_trips_json_and_leaves_unknown_optionals_empty() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()

    metrics = {"relative_pnl": 0.08, "ranking": {"rank": 2, "of": 3}, "note": None}
    changes = {"fast_window": 7}
    scope = {"symbols": ["BTC-USDT-SWAP"], "timeframe": "1H"}
    with db.session() as session:
        session.add(
            ArcForwardOutcome(
                id="fo_" + "a" * 32,
                target_id="bitpro",
                parent_strategy_id="41",
                challenger_strategy_id="42",
                verdict="handoff",
                metrics_json=metrics,
                changes_json=changes,
                scope_json=scope,
            )
        )

    with db.session() as session:
        row = session.get(ArcForwardOutcome, "fo_" + "a" * 32)
        assert row is not None
        assert row.metrics_json == metrics
        assert row.changes_json == changes
        assert row.scope_json == scope
        assert row.generation == 1
        assert row.verdict_source == "race_judge"
        assert row.lineage_status == "pending"
        assert row.evidence_sha256 == ""
        assert row.slot_no is None
        assert row.ended_at is None
        assert row.mission_id is None
        assert row.candidate_id is None
        assert row.attempt_id is None


def test_forward_outcome_duplicate_pair_is_rejected() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    pair = {
        "target_id": "bitpro",
        "parent_strategy_id": "41",
        "challenger_strategy_id": "42",
        "verdict": "handoff",
    }

    with db.session() as session:
        session.add(ArcForwardOutcome(id="fo_" + "a" * 32, **pair))

    with pytest.raises(IntegrityError), db.session() as session:
        session.add(ArcForwardOutcome(id="fo_" + "b" * 32, **pair))
