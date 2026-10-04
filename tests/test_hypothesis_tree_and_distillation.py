from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from hypertrade.db import Database
from hypertrade.memory.distillation import MemoryDistillationService
from hypertrade.memory.layered_service import (
    EpisodicMemoryItemV1,
    HypothesisStatus,
    LayeredMemoryService,
    MutationType,
    SemanticMemoryAssertionV1,
)
from hypertrade.research.hypothesis_tree import (
    DuplicateHypothesisError,
    HypothesisTreeService,
    MaxTreeDepthExceededError,
)


@pytest.fixture
def test_db(tmp_path: Path) -> Database:
    db_file = tmp_path / "test_het_distill.db"
    db = Database(f"sqlite:///{db_file}")
    db.create_all()
    return db


@pytest.fixture
def memory_svc(test_db: Database) -> LayeredMemoryService:
    return LayeredMemoryService(test_db)


@pytest.fixture
def tree_svc(memory_svc: LayeredMemoryService) -> HypothesisTreeService:
    return HypothesisTreeService(memory_svc)


@pytest.fixture
def distill_svc(memory_svc: LayeredMemoryService) -> MemoryDistillationService:
    return MemoryDistillationService(memory_svc)


def test_hypothesis_tree_creation_and_branching(tree_svc: HypothesisTreeService) -> None:
    tree_id = "tree_btc_breakout"
    root = tree_svc.create_tree(
        tree_id=tree_id,
        claim="Breakout above 20-day high with expanding volume generates positive alpha",
        rationale="Momentum price discovery",
        target_regimes=["bull_trend"],
    )

    assert root.id is not None
    assert root.depth == 0
    assert root.mutation_type == MutationType.INIT
    assert root.status == HypothesisStatus.PROPOSED

    # Propose child branch
    child1 = tree_svc.propose_branch(
        tree_id=tree_id,
        parent_id=root.id,
        mutation_type=MutationType.FEATURE_ADD,
        claim="Add ATR volatility filter to skip overextended breakouts",
        rationale="Filters out late trend traps",
    )

    assert child1.id is not None
    assert child1.parent_id == root.id
    assert child1.depth == 1
    assert child1.mutation_type == MutationType.FEATURE_ADD


def test_hypothesis_tree_semantic_deduplication(tree_svc: HypothesisTreeService) -> None:
    tree_id = "tree_dedup_test"
    root = tree_svc.create_tree(
        tree_id=tree_id,
        claim="MACD golden cross on 4H timeframe yields trend profit",
    )

    # Attempt to propose exact duplicate claim
    with pytest.raises(DuplicateHypothesisError, match="Redundant hypothesis"):
        tree_svc.propose_branch(
            tree_id=tree_id,
            parent_id=root.id or "",
            mutation_type=MutationType.PARAM_REFINE,
            claim="MACD golden cross on 4H timeframe yields trend profit",
        )


def test_hypothesis_tree_max_depth_exceeded(tree_svc: HypothesisTreeService) -> None:
    tree_id = "tree_depth_test"
    current = tree_svc.create_tree(tree_id=tree_id, claim="Root step 0")

    # Build chain up to depth 2
    for step in range(1, 3):
        current = tree_svc.propose_branch(
            tree_id=tree_id,
            parent_id=current.id or "",
            mutation_type=MutationType.PARAM_REFINE,
            claim=f"Chain mutation step {step}",
            max_depth=2,
        )

    # At depth 2, attempting depth 3 should exceed max_depth=2
    with pytest.raises(MaxTreeDepthExceededError):
        tree_svc.propose_branch(
            tree_id=tree_id,
            parent_id=current.id or "",
            mutation_type=MutationType.DEFENSIVE_ADD,
            claim="Excess step 3",
            max_depth=2,
        )


def test_hypothesis_tree_evaluation_and_pruning(tree_svc: HypothesisTreeService) -> None:
    tree_id = "tree_prune_test"
    root = tree_svc.create_tree(tree_id=tree_id, claim="Root hypothesis")
    root_evaluated = tree_svc.evaluate_and_prune_node(
        node_id=root.id or "",
        relative_pnl=Decimal("0.1000"),
        sharpe=Decimal("1.8000"),
    )
    assert root_evaluated.status == HypothesisStatus.PROMOTED

    # Child 1: deteriorates relative PnL and Sharpe vs parent -> PRUNED
    child_bad = tree_svc.propose_branch(
        tree_id=tree_id,
        parent_id=root.id or "",
        mutation_type=MutationType.LOGIC_INVERT,
        claim="Counter-trend short during volume explosion",
    )
    evaluated_bad = tree_svc.evaluate_and_prune_node(
        node_id=child_bad.id or "",
        relative_pnl=Decimal("-0.0500"),
        sharpe=Decimal("0.4000"),
    )
    assert evaluated_bad.status == HypothesisStatus.PRUNED
    assert "Deteriorated relative PnL" in (evaluated_bad.prune_reason or "")

    # Child 2: outperforms parent -> PROMOTED
    child_good = tree_svc.propose_branch(
        tree_id=tree_id,
        parent_id=root.id or "",
        mutation_type=MutationType.DEFENSIVE_ADD,
        claim="Add trailing stop ratchet on 3R profit target",
    )
    evaluated_good = tree_svc.evaluate_and_prune_node(
        node_id=child_good.id or "",
        relative_pnl=Decimal("0.1600"),
        sharpe=Decimal("2.4000"),
    )
    assert evaluated_good.status == HypothesisStatus.PROMOTED

    # Check active leaves and best candidate
    leaves = tree_svc.get_active_leaves(tree_id)
    leaf_ids = [leaf.id for leaf in leaves]
    assert child_good.id in leaf_ids
    assert child_bad.id not in leaf_ids  # Pruned child must not be an active leaf

    best = tree_svc.get_best_candidate(tree_id)
    assert best is not None
    assert best.id == child_good.id
    assert best.benchmark_relative_pnl == Decimal("0.1600")


def test_memory_distillation_pipeline(
    memory_svc: LayeredMemoryService,
    distill_svc: MemoryDistillationService,
) -> None:
    regime = "high_volatility"

    # Seed 2 episodes (less than minimum threshold 3)
    for i in range(2):
        memory_svc.record_episode(
            EpisodicMemoryItemV1(
                mission_id=f"m_{i}",
                market_regime=regime,
                event_type="paper_decay",
                reflection_summary=f"Episode {i}: ATR stop too narrow during funding squeeze.",
            )
        )

    # Should not distill yet
    res_none = distill_svc.distill_episodes_for_regime(
        market_regime=regime,
        min_episode_count=3,
    )
    assert res_none is None

    # Pre-seed an older active semantic assertion that may be superseded
    old_rule_id = memory_svc.record_semantic_assertion(
        SemanticMemoryAssertionV1(
            claim=(
                "Recurrent paper_decay observed across episodes in high_volatility: tighter stops."
            ),
            applicable_regimes=[regime],
            confidence=Decimal("0.6000"),
            status="active",
        )
    )

    # Seed 3rd episode to reach threshold
    memory_svc.record_episode(
        EpisodicMemoryItemV1(
            mission_id="m_2",
            market_regime=regime,
            event_type="paper_decay",
            reflection_summary="Episode 2: Repeated whipsaw stop-out during high volatility.",
        )
    )

    # Custom summarizer to test distillation
    def custom_summarizer(
        episodes: list[EpisodicMemoryItemV1],
    ) -> tuple[str, str, Decimal]:
        return (
            "Recurrent paper_decay observed across episodes in high_volatility: "
            "widen ATR trailing stop by 1.5x.",
            "structural_constraint",
            Decimal("0.9000"),
        )

    distilled = distill_svc.distill_episodes_for_regime(
        market_regime=regime,
        min_episode_count=3,
        causal_summarizer=custom_summarizer,
    )

    assert distilled is not None
    assert distilled.id is not None
    assert distilled.status == "active"
    assert distilled.confidence == Decimal("0.9000")
    assert len(distilled.derived_from_episodes) == 3
    assert "widen ATR trailing stop" in distilled.claim

    # Verify older similar assertion was automatically deprecated
    old_rule = memory_svc.get_semantic_assertion(old_rule_id)
    assert old_rule is not None
    assert old_rule.status == "deprecated"
    assert old_rule.replaced_by == distilled.id
