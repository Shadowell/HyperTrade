"""Cognitive-memory migration and idempotency on an isolated PostgreSQL cluster."""

from __future__ import annotations

from decimal import Decimal
from threading import Barrier, Thread
from time import sleep

from sqlalchemy import inspect, select, text
from test_arc_event_journal_postgres import _alembic, _cluster


def test_postgres_upgrade_write_idempotency_query_and_downgrade(tmp_path) -> None:
    with _cluster(tmp_path) as url:
        from hypertrade.db import (
            ArcEpisodicMemory,
            ArcHypothesisNode,
            ArcSemanticAssertion,
            Database,
        )
        from hypertrade.memory.distillation import MemoryDistillationService
        from hypertrade.memory.layered_service import (
            EpisodicMemoryItemV1,
            HypothesisNodeV1,
            LayeredMemoryService,
        )

        db = Database(url)
        with db.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
            )
            connection.execute(
                text("INSERT INTO alembic_version VALUES ('0048_arc_mission_events')")
            )

        _alembic(url, "upgrade", "0049_arc_cognitive_memory")
        memory = LayeredMemoryService(db)
        hypothesis = HypothesisNodeV1(
            tree_id="pg-tree",
            claim="PostgreSQL migration hypothesis",
            idempotency_key="pg-hypothesis-once",
        )
        hypothesis_ready = Barrier(2)
        hypothesis_results: list[str] = []

        def write_hypothesis() -> None:
            hypothesis_ready.wait(timeout=5)
            hypothesis_results.append(memory.record_hypothesis(hypothesis))

        hypothesis_workers = [Thread(target=write_hypothesis) for _ in range(2)]
        for worker in hypothesis_workers:
            worker.start()
        for worker in hypothesis_workers:
            worker.join(timeout=10)
            assert not worker.is_alive()
        assert len(set(hypothesis_results)) == 1

        episode_ids: list[str] = []
        for index in range(3):
            episode = EpisodicMemoryItemV1(
                mission_id=f"pg-mission-{index}",
                idempotency_key=f"pg-episode-{index}",
                symbols=["BTC-USDT-SWAP"],
                timeframe="1H",
                market_regime="high_volatility",
                event_type="paper_decay",
                raw_evidence_ref=f"pg-evidence-{index}",
                reflection_summary="Audited PostgreSQL episode.",
            )
            episode_id = memory.record_episode(episode)
            assert episode_id == memory.record_episode(episode)
            episode_ids.append(episode_id)

        calls = 0

        def summarize(
            _episodes: list[EpisodicMemoryItemV1],
        ) -> tuple[str, str, Decimal]:
            nonlocal calls
            calls += 1
            sleep(0.25)
            return (
                "Repeated audited decay requires a governed stop review.",
                "structural_constraint",
                Decimal("0.7500"),
            )

        distiller = MemoryDistillationService(memory)
        ready = Barrier(2)
        concurrent_results = []

        def run_concurrent_distillation() -> None:
            ready.wait(timeout=5)
            concurrent_results.append(
                distiller.distill_episodes_for_regime(
                    market_regime="high_volatility",
                    symbols=["BTC-USDT-SWAP"],
                    timeframe="1H",
                    causal_summarizer=summarize,
                    summarizer_version="postgres-v1",
                )
            )

        workers = [Thread(target=run_concurrent_distillation) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
            assert not worker.is_alive()
        first = next(result for result in concurrent_results if result is not None)
        replay = distiller.distill_episodes_for_regime(
            market_regime="high_volatility",
            symbols=["BTC-USDT-SWAP"],
            timeframe="1H",
            causal_summarizer=summarize,
            summarizer_version="postgres-v1",
        )
        assert replay is not None
        assert first.id == replay.id
        assert first.derived_from_episodes == sorted(episode_ids)
        assert calls == 1

        with db.session() as session:
            assert len(session.scalars(select(ArcHypothesisNode)).all()) == 1
            assert len(session.scalars(select(ArcEpisodicMemory)).all()) == 3
            assert len(session.scalars(select(ArcSemanticAssertion)).all()) == 1

        db.engine.dispose()
        _alembic(url, "downgrade", "0048_arc_mission_events")
        downgraded = Database(url)
        with downgraded.engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0048_arc_mission_events"
            tables = set(inspect(connection).get_table_names())
            assert "arc_hypothesis_nodes" not in tables
            assert "arc_episodic_memories" not in tables
            assert "arc_semantic_assertions" not in tables
        downgraded.engine.dispose()
