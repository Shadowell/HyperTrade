"""Unit and integration tests for Layered Cognitive Memory & RD-Agent Hypothesis Storage."""

from decimal import Decimal
from pathlib import Path

import pytest
from hypertrade.db import Database
from hypertrade.memory.layered_service import (
    EpisodicMemoryItemV1,
    HypothesisNodeV1,
    HypothesisStatus,
    LayeredMemoryService,
    MutationType,
    SemanticMemoryAssertionV1,
    compute_regime_match_score,
    cosine_similarity,
    deterministic_embedding,
)


@pytest.fixture
def test_db(tmp_path: Path) -> Database:
    db_file = tmp_path / "test_memory.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_all()
    return db


@pytest.fixture
def memory_svc(test_db: Database) -> LayeredMemoryService:
    return LayeredMemoryService(test_db)


def test_deterministic_embedding_and_cosine() -> None:
    emb1 = deterministic_embedding("BTC breakout trend")
    emb2 = deterministic_embedding("BTC breakout trend")
    emb3 = deterministic_embedding("ETH crash sideways dump")

    assert len(emb1) == 64
    assert emb1 == emb2
    assert cosine_similarity(emb1, emb2) > 0.999
    assert -1.0 <= cosine_similarity(emb1, emb3) <= 1.0
    assert cosine_similarity([], emb1) == 0.0

    related = deterministic_embedding("BTC breakout momentum trend")
    unrelated = deterministic_embedding("funding basis carry arbitrage")
    assert cosine_similarity(emb1, related) > cosine_similarity(emb1, unrelated)


def test_compute_regime_match_score() -> None:
    # Exact match
    assert compute_regime_match_score("bull_trend", ["bull_trend"]) == 1.0

    # Universal / All-weather
    assert compute_regime_match_score("bear_crash", []) == 0.8
    assert compute_regime_match_score("sideways_range", ["ALL"]) == 0.8

    # Volatility is direction-neutral and must not be inferred as bullish.
    score_adjacent = compute_regime_match_score("bull_trend", ["high_volatility"])
    assert score_adjacent == 0.0
    assert compute_regime_match_score("bear_trend", ["high_volatility"]) == 0.0

    # Conflicting polarities (bull vs bear)
    score_conflict = compute_regime_match_score("bear_crash", ["bull_trend"])
    assert score_conflict == -0.8

    score_conflict_rev = compute_regime_match_score("bull_trend", ["bear_crash"])
    assert score_conflict_rev == -0.8


def test_working_memory_lifecycle(memory_svc: LayeredMemoryService) -> None:
    wm = memory_svc.init_working_memory(
        session_id="sess_001",
        turn_id="turn_01",
        goal="Discover high Sharpe momentum breakout strategy for BTC",
        symbol="BTC-USDT-SWAP",
        timeframe="1H",
        current_regime="bull_trend",
        budget_tokens=500,
        recent_market_snapshot={"price": 68000, "funding_rate": 0.0001},
    )

    assert wm.session_id == "sess_001"
    assert memory_svc.get_working_memory("sess_001") is not None

    memory_svc.append_cot_step("sess_001", "Evaluated EMA 20/50 cross, checking volatility.")
    wm_updated = memory_svc.get_working_memory("sess_001")
    assert wm_updated is not None
    assert len(wm_updated.chain_of_thought_buffer) == 1

    prompt_text = wm_updated.format_prompt_context(max_tokens=300)
    assert "BTC-USDT-SWAP" in prompt_text
    assert "bull_trend" in prompt_text
    assert "Evaluated EMA 20/50 cross" in prompt_text

    memory_svc.clear_working_memory("sess_001")
    assert memory_svc.get_working_memory("sess_001") is None


def test_episodic_memory_recording_and_query(memory_svc: LayeredMemoryService) -> None:
    ep1 = EpisodicMemoryItemV1(
        mission_id="m_001",
        experiment_id="exp_001",
        symbols=["BTC-USDT-SWAP"],
        timeframe="1H",
        market_regime="high_volatility",
        event_type="backtest_success",
        metrics_delta={"sharpe": 2.1, "relative_pnl": 0.15},
        reflection_summary="ATR trailing stop outperformed fixed stop in high volatility rally.",
    )
    ep_id = memory_svc.record_episode(ep1)
    assert ep_id.startswith("aepm_")

    fetched = memory_svc.get_episode(ep_id)
    assert fetched is not None
    assert fetched.market_regime == "high_volatility"
    assert fetched.metrics_delta["sharpe"] == 2.1
    assert len(fetched.embedding) == 64

    # Query with filters
    results = memory_svc.list_episodes(symbols=["BTC-USDT-SWAP"], market_regime="high_volatility")
    assert len(results) >= 1
    assert results[0].id == ep_id

    # Query mismatch
    empty_results = memory_svc.list_episodes(symbols=["ETH-USDT-SWAP"])
    assert len(empty_results) == 0


def test_semantic_memory_and_counter_evidence(memory_svc: LayeredMemoryService) -> None:
    sem1 = SemanticMemoryAssertionV1(
        assertion_type="causal_heuristic",
        claim=(
            "In high funding rate regimes, momentum long breakout "
            "suffers from liquidation cascades."
        ),
        applicable_regimes=["high_volatility", "bull_surge"],
        confidence=Decimal("0.8000"),
    )
    sem_id = memory_svc.record_semantic_assertion(sem1)
    assert sem_id.startswith("asmt_")

    fetched = memory_svc.get_semantic_assertion(sem_id)
    assert fetched is not None
    assert fetched.status == "active"
    assert fetched.confidence == Decimal("0.8000")

    # Record counter evidence
    for _ in range(4):
        memory_svc.record_counter_evidence(sem_id, penalty=Decimal("0.1000"))

    updated = memory_svc.get_semantic_assertion(sem_id)
    assert updated is not None
    assert updated.counter_evidence_count == 4
    assert updated.confidence == Decimal("0.4000")
    assert updated.status == "active"

    # 5th counter evidence drops confidence <= 0.30 -> automatically marks disputed
    memory_svc.record_counter_evidence(sem_id, penalty=Decimal("0.1500"))
    disputed = memory_svc.get_semantic_assertion(sem_id)
    assert disputed is not None
    assert disputed.counter_evidence_count == 5
    assert disputed.confidence <= Decimal("0.3000")
    assert disputed.status == "disputed"

    # Deprecate assertion
    dep_ok = memory_svc.deprecate_semantic_assertion(sem_id, reason="Superseded by robust filter")
    assert dep_ok is True
    dep = memory_svc.get_semantic_assertion(sem_id)
    assert dep is not None
    assert dep.status == "deprecated"
    assert dep.metadata["deprecation_reason"] == "Superseded by robust filter"


def test_rd_agent_hypothesis_node_lifecycle(memory_svc: LayeredMemoryService) -> None:
    tree_id = "tree_btc_evo_01"
    root_node = HypothesisNodeV1(
        tree_id=tree_id,
        claim="Trend following on 4H BTC with Bollinger Bands expansion captures major swings",
        rationale="Volatility compression leads to directional breakout",
        target_regimes=["bull_trend", "high_volatility"],
        mutation_type=MutationType.INIT,
        depth=0,
    )
    root_id = memory_svc.record_hypothesis(root_node)
    assert root_id.startswith("hypo_")

    # Add child node
    child_node = HypothesisNodeV1(
        tree_id=tree_id,
        parent_id=root_id,
        depth=1,
        claim="Add ADX filter to eliminate choppy false breakouts",
        rationale="ADX > 25 confirms trend strength",
        target_regimes=["bull_trend"],
        mutation_type=MutationType.FEATURE_ADD,
    )
    child_id = memory_svc.record_hypothesis(child_node)

    tree_nodes = memory_svc.list_hypotheses_for_tree(tree_id)
    assert len(tree_nodes) == 2
    assert tree_nodes[0].id == root_id
    assert tree_nodes[1].id == child_id

    # Update child node after backtest
    update_ok = memory_svc.update_hypothesis_status(
        child_id,
        status=HypothesisStatus.TESTED,
        relative_pnl=Decimal("0.1250"),
        sharpe=Decimal("1.8500"),
        strategy_digest="sha256:abcd1234",
    )
    assert update_ok is True

    updated_child = memory_svc.get_hypothesis(child_id)
    assert updated_child is not None
    assert updated_child.status == HypothesisStatus.TESTED
    assert updated_child.sharpe_ratio == Decimal("1.8500")
    assert updated_child.strategy_digest == "sha256:abcd1234"


def test_regime_aware_retrieval_and_cross_regime_penalty(memory_svc: LayeredMemoryService) -> None:
    # Seed semantic memories
    bull_sem = SemanticMemoryAssertionV1(
        claim="Ride parabolic upside with loose trailing stop in bull surges",
        applicable_regimes=["bull_trend", "bull_surge"],
        confidence=Decimal("0.9000"),
    )
    bear_sem = SemanticMemoryAssertionV1(
        claim="Strict rapid trailing stop with funding rate short hedge in bear crashes",
        applicable_regimes=["bear_crash", "extreme_down"],
        confidence=Decimal("0.8500"),
    )
    memory_svc.record_semantic_assertion(bull_sem)
    memory_svc.record_semantic_assertion(bear_sem)

    # When current regime is bear_crash:
    # bull_sem will get -0.8 regime score, strictly filtered out.
    # bear_sem will get 1.0 regime score, rising to top.
    selected_semantics, _ = memory_svc.retrieve_context_for_task(
        goal="Risk management and survival strategy",
        symbol="BTC-USDT-SWAP",
        timeframe="1H",
        current_regime="bear_crash",
    )

    claims = [s.claim for s in selected_semantics]
    assert any("bear crashes" in c for c in claims)
    # The toxic bull surge heuristic should not appear for bear crash task
    assert not any("bull surges" in c for c in claims)


def test_populate_working_memory_integration(memory_svc: LayeredMemoryService) -> None:
    tree_id = "tree_full_integration"
    hypo = HypothesisNodeV1(
        tree_id=tree_id,
        claim="EMA 12/26 cross with RSI filter",
        target_regimes=["high_volatility"],
    )
    memory_svc.record_hypothesis(hypo)

    sem = SemanticMemoryAssertionV1(
        claim="RSI divergence signals reversal",
        applicable_regimes=["high_volatility"],
        confidence=Decimal("0.7500"),
    )
    memory_svc.record_semantic_assertion(sem)

    wm = memory_svc.populate_working_memory_for_task(
        session_id="full_test_sess",
        turn_id="turn_01",
        goal="Test full integration",
        symbol="ETH-USDT-SWAP",
        timeframe="15m",
        current_regime="high_volatility",
        tree_id=tree_id,
    )

    assert len(wm.active_hypotheses) == 1
    assert wm.active_hypotheses[0].claim == "EMA 12/26 cross with RSI filter"
    assert len(wm.retrieved_semantic_assertions) >= 1
    assert "RSI divergence" in wm.retrieved_semantic_assertions[0].claim

    formatted = wm.format_prompt_context()
    assert "ETH-USDT-SWAP" in formatted
    assert "RSI divergence" in formatted
    assert "EMA 12/26 cross" in formatted
