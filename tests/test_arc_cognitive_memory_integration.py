from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
from hypertrade.db import (
    ArcEpisodicMemory,
    ArcHypothesisNode,
    ArcSemanticAssertion,
    Database,
)
from hypertrade.memory.arc_integration import ingest_projection
from hypertrade.memory.layered_service import (
    EpisodicMemoryItemV1,
    LayeredMemoryService,
    SemanticMemoryAssertionV1,
)
from hypertrade.worker import memory_distillation_worker_once
from sqlalchemy import create_engine, inspect, select


def _projection() -> SimpleNamespace:
    attempt = SimpleNamespace(
        attempt_id="att-memory-1",
        candidate_id="cand-memory-1",
        hypothesis="ATR breakout remains robust in a volatile development window",
        strategy_code="class Strategy: pass",
        strategy_spec={"family": "atr_breakout"},
    )
    goal = SimpleNamespace(
        objective="Research bounded ETH development evidence",
        symbols=["ETH-USDT-SWAP"],
        timeframes=["1H"],
        evolution_context={"market_regime": "high_volatility"},
        feedback_parent=None,
    )
    events = [
        SimpleNamespace(
            event_id="evt-proposal",
            event_type="candidate_proposed",
            payload={"attempt": {"attempt_id": attempt.attempt_id}},
        ),
        SimpleNamespace(
            event_id="evt-development",
            event_type="avo_development_result",
            payload={
                "attempt_id": attempt.attempt_id,
                "result": {
                    "attempt_id": attempt.attempt_id,
                    "passed": True,
                    "backtest_id": "bt-development-1",
                    "metrics": {"sharpe": 1.4, "relative_pnl": 0.08},
                },
            },
        ),
        SimpleNamespace(
            event_id="evt-final",
            event_type="bitpro_self_tested",
            payload={
                "attempt_id": attempt.attempt_id,
                "passed": True,
                "backtest_id": "bt-final-holdout-1",
                "purpose": "final",
                "metrics": {"sharpe": 1.8},
            },
        ),
    ]
    return SimpleNamespace(goal=goal, attempts=[attempt], events=events)


def test_projection_sync_is_idempotent_and_excludes_final_holdout_from_recall(
    tmp_path: Path,
) -> None:
    db = Database(f"sqlite:///{tmp_path / 'cognitive.db'}")
    db.create_all()
    projection = _projection()

    first = ingest_projection(db, "mission-memory-1", projection, max_prompt_tokens=160)
    second = ingest_projection(db, "mission-memory-1", projection, max_prompt_tokens=160)

    assert first.status == "ok"
    assert second.status == "ok"
    assert "bt-final-holdout-1" not in second.prompt_context
    assert "bt-development-1" in second.prompt_context
    with db.session() as session:
        hypotheses = session.scalars(select(ArcHypothesisNode)).all()
        assert len(hypotheses) == 1
        assert hypotheses[0].experiment_id == "bt-development-1"
        assert hypotheses[0].sharpe_ratio == Decimal("1.4000")
        episodes = session.scalars(select(ArcEpisodicMemory)).all()
        assert len(episodes) == 2
        final = next(row for row in episodes if row.experiment_id == "bt-final-holdout-1")
        assert final.metadata_json["recall_eligible"] is False


def test_unknown_backtest_verdict_does_not_become_negative_memory(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'unknown.db'}")
    db.create_all()
    projection = _projection()
    projection.events = [
        SimpleNamespace(
            event_id="evt-unknown",
            event_type="avo_development_result",
            payload={
                "attempt_id": "att-memory-1",
                "result": {
                    "attempt_id": "att-memory-1",
                    "passed": None,
                    "backtest_id": "bt-unknown",
                    "status": "unknown",
                },
            },
        )
    ]

    ingest_projection(db, "mission-memory-unknown", projection)

    with db.session() as session:
        assert session.scalars(select(ArcEpisodicMemory)).all() == []


def test_projection_builds_actual_hypothesis_lineage(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'lineage.db'}")
    db.create_all()
    projection = _projection()
    parent = projection.attempts[0]
    child = SimpleNamespace(
        attempt_id="att-memory-2",
        candidate_id="cand-memory-2",
        hypothesis="Refine the parent ATR breakout",
        strategy_code="class RefinedStrategy: pass",
        strategy_spec={"parent_attempt_id": parent.attempt_id, "mutation_round": 1},
    )
    projection.attempts.append(child)
    projection.events = []

    ingest_projection(db, "mission-memory-lineage", projection)

    with db.session() as session:
        nodes = session.scalars(
            select(ArcHypothesisNode).order_by(ArcHypothesisNode.depth)
        ).all()
    assert len(nodes) == 2
    assert nodes[1].parent_id == nodes[0].id
    assert nodes[1].depth == 1
    assert nodes[1].mutation_type == "param_refine"


def test_recall_respects_symbol_and_timeframe_scope(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'scope.db'}")
    db.create_all()
    memory = LayeredMemoryService(db)
    memory.record_episode(
        EpisodicMemoryItemV1(
            mission_id="unrelated",
            symbols=["ETH-USDT-SWAP"],
            timeframe="5m",
            market_regime="high_volatility",
            event_type="paper_decay",
            raw_evidence_ref="paper:unrelated",
            reflection_summary="UNRELATED_FIVE_MINUTE_EPISODE",
        )
    )
    memory.record_semantic_assertion(
        SemanticMemoryAssertionV1(
            claim="BTC_ONLY_FIVE_MINUTE_RULE",
            applicable_regimes=["high_volatility"],
            metadata={"symbols": ["BTC-USDT-SWAP"], "timeframe": "5m"},
        )
    )

    result = ingest_projection(db, "mission-memory-scope", _projection(), max_prompt_tokens=160)

    assert "UNRELATED_FIVE_MINUTE_EPISODE" not in result.prompt_context
    assert "BTC_ONLY_FIVE_MINUTE_RULE" not in result.prompt_context
    assert len(result.prompt_context) <= 160 * 4 + 50


def test_cognitive_memory_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    path = (
        Path(__file__).parents[1]
        / "backend/alembic/versions/0049_arc_cognitive_memory.py"
    )
    spec = importlib.util.spec_from_file_location("arc_cognitive_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")

    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
        inspector = inspect(connection)
        assert {
            "arc_hypothesis_nodes",
            "arc_episodic_memories",
            "arc_semantic_assertions",
        }.issubset(inspector.get_table_names())
        semantic_uniques = {item["name"] for item in inspector.get_unique_constraints(
            "arc_semantic_assertions"
        )}
        assert "uq_arc_semantic_evidence_version" in semantic_uniques
        hypothesis_fks = inspector.get_foreign_keys("arc_hypothesis_nodes")
        assert hypothesis_fks[0]["referred_table"] == "arc_hypothesis_nodes"
        migration.downgrade()
        assert "arc_hypothesis_nodes" not in inspect(connection).get_table_names()


def test_create_all_models_include_distillation_identity_constraints(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'models.db'}")
    db.create_all()
    inspector = inspect(db.engine)

    semantic_columns = {
        column["name"] for column in inspector.get_columns(ArcSemanticAssertion.__tablename__)
    }
    assert {"evidence_set_hash", "distillation_version", "idempotency_key"}.issubset(
        semantic_columns
    )


def test_worker_distillation_replay_keeps_one_semantic_assertion(tmp_path: Path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'worker-distillation.db'}")
    db.create_all()
    memory = LayeredMemoryService(db)
    for index in range(3):
        memory.record_episode(
            EpisodicMemoryItemV1(
                mission_id=f"worker-{index}",
                symbols=["BTC-USDT-SWAP"],
                timeframe="1H",
                market_regime="high_volatility",
                event_type="backtest_rejected",
                raw_evidence_ref=f"paper:{index}",
                reflection_summary="Audited trailing-stop decay.",
            )
        )

    calls = 0

    def summarize(
        _episodes: list[EpisodicMemoryItemV1],
    ) -> tuple[str, str, Decimal]:
        nonlocal calls
        calls += 1
        return (
            "High-volatility trailing-stop decay requires review.",
            "structural_constraint",
            Decimal("0.7000"),
        )

    first = memory_distillation_worker_once(db, causal_summarizer=summarize)
    second = memory_distillation_worker_once(db, causal_summarizer=summarize)

    assert first["status"] == "completed"
    assert second["ids"] == first["ids"]
    assert calls == 1
    with db.session() as session:
        assert len(session.scalars(select(ArcSemanticAssertion)).all()) == 1
