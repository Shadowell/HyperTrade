"""
Test ARC MCTS Monte Carlo Tree Search & MAP-Elites Quality-Diversity Engine
"""

from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.mcts import ARCMCTSEngine, MAPElitesGrid


def test_mcts_tree_construction_and_ucb1_selection():
    mcts = ARCMCTSEngine()

    root_attempt = ARCCandidateAttemptV1(
        attempt_id="att_root",
        candidate_id="cand_root",
        hypothesis="Root breakout strategy",
        strategy_code="lookback_period = 20\nstop_loss = 0.12",
        observed_metrics={"sharpe_after_attack": 0.8},
    )

    root_node = mcts.add_root(root_attempt)
    assert root_node.node_id == "att_root"
    assert mcts.root_id == "att_root"

    # Add child 1
    child1_attempt = ARCCandidateAttemptV1(
        attempt_id="att_child1",
        candidate_id="cand_child1",
        hypothesis="Mutated short term",
        strategy_code="lookback_period = 5\nstop_loss = 0.08",
        observed_metrics={"sharpe_after_attack": 1.2},
    )
    child1 = mcts.add_child("att_root", child1_attempt)

    # Add child 2
    child2_attempt = ARCCandidateAttemptV1(
        attempt_id="att_child2",
        candidate_id="cand_child2",
        hypothesis="Mutated long term",
        strategy_code="lookback_period = 50\nstop_loss = 0.05",
        observed_metrics={"sharpe_after_attack": 1.8},
    )
    child2 = mcts.add_child("att_root", child2_attempt)

    # Backpropagate rewards
    mcts.backpropagate("att_child1", 1.2)
    mcts.backpropagate("att_child2", 1.8)

    assert root_node.visits == 2
    assert child1.visits == 1
    assert child2.visits == 1

    # Best node to expand should select child2 due to higher value score
    selected = mcts.select_best_node_to_expand()
    assert selected is not None
    assert selected.node_id == "att_child2"


def test_engine_owns_expansion_and_simulation():
    """The engine offered only Selection and Backpropagation.

    Callers had to build the tree themselves, so the shape of the search lived outside
    the search engine and every caller searched differently.
    """
    mcts = ARCMCTSEngine()
    root = mcts.add_root(
        ARCCandidateAttemptV1(
            attempt_id="att_seed",
            candidate_id="cand_seed",
            hypothesis="seed",
            strategy_code="lookback_period = 20\nstop_loss = 0.12",
        )
    )

    def proposer(parent):
        return [
            ARCCandidateAttemptV1(
                attempt_id=f"att_{parent.attempt_id}_child",
                candidate_id="cand_child",
                hypothesis="child",
                strategy_code="lookback_period = 20\nstop_loss = 0.08",
            )
        ]

    children = mcts.expand(root.node_id, proposer)
    assert [child.node_id for child in children] == ["att_att_seed_child"]
    assert children[0].parent_id == root.node_id
    # Re-proposing an existing node must not duplicate it.
    assert mcts.expand(root.node_id, proposer) == []

    results = mcts.simulate(children, lambda attempt: (True, 1.7))
    assert results[0][1] is True
    assert children[0].visits == 1
    # Simulation backpropagates without the caller having to remember to.
    assert root.visits == 1
    assert root.total_value == 1.7


def test_a_failing_rollout_does_not_halt_the_generation():
    mcts = ARCMCTSEngine()
    root = mcts.add_root(
        ARCCandidateAttemptV1(
            attempt_id="att_boom",
            candidate_id="cand_boom",
            hypothesis="explodes under review",
            strategy_code="stop_loss = 0.05",
        )
    )

    def exploding(attempt):
        raise RuntimeError("reviewer crashed")

    results = mcts.simulate([root], exploding)
    assert results == [(root, False, 0.0)]


def test_quality_diversity_niche_reads_the_declared_span():
    """Matching four literals filed every compiled candidate into one niche."""
    grid = MAPElitesGrid()

    def descriptor_for(code: str) -> tuple[str, str]:
        return grid.get_feature_descriptor(
            ARCCandidateAttemptV1(
                attempt_id="att_span",
                candidate_id="cand_span",
                hypothesis="span probe",
                strategy_code=code,
                observed_metrics={"sharpe_after_attack": 1.6},
            )
        )

    # A compiled candidate declares its window through the research parameter map, and
    # names it after its own indicator rather than calling it `lookback_period`.
    fast = descriptor_for('params = {}\nw = int(params.get("rsi_period", 7))')
    slow = descriptor_for('params = {}\nw = int(params.get("channel_period", 60))')
    assert fast[0] == "short_term"
    assert slow[0] == "long_term"
    assert fast != slow


def test_map_elites_quality_diversity_grid():
    grid = MAPElitesGrid()

    att1 = ARCCandidateAttemptV1(
        attempt_id="att_1",
        candidate_id="cand_1",
        hypothesis="Short term trend",
        strategy_code="lookback_period = 5",
        observed_metrics={"sharpe_after_attack": 1.6},
    )
    from hypertrade.arc.mcts import MCTSNode

    node1 = MCTSNode(
        node_id="att_1",
        attempt=att1,
        feature_descriptor=grid.get_feature_descriptor(att1),
        visits=1,
        total_value=1.6,
    )
    updated1 = grid.add_candidate(node1)
    assert updated1 is True
    assert ("short_term", "trending_strong") in grid.archive

    # Outperforming candidate in same cell
    att2 = ARCCandidateAttemptV1(
        attempt_id="att_2",
        candidate_id="cand_2",
        hypothesis="Short term trend superior",
        strategy_code="lookback_period = 5",
        observed_metrics={"sharpe_after_attack": 1.9},
    )
    node2 = MCTSNode(
        node_id="att_2",
        attempt=att2,
        feature_descriptor=grid.get_feature_descriptor(att2),
        visits=1,
        total_value=1.9,
    )
    updated2 = grid.add_candidate(node2)
    assert updated2 is True
    assert grid.archive[("short_term", "trending_strong")].node_id == "att_2"


def test_select_mutation_parents_ranks_by_ucb1_and_caps_by_budget():
    """预算压力下：UCB1 高分（高价值/低访问）节点先成为变异父本。"""
    import pytest

    pytest.importorskip("hypertrade.arc.mcts")
    mcts = ARCMCTSEngine()

    root = mcts.add_root(
        ARCCandidateAttemptV1(
            attempt_id="att_root",
            candidate_id="cand_root",
            hypothesis="root",
            strategy_code="lookback_period = 20\nstop_loss = 0.12",
            observed_metrics={"sharpe_after_attack": 0.5},
        )
    )

    rollouts: list[tuple[object, bool, float]] = []
    for index, (score, visits) in enumerate([(1.8, 5), (0.2, 1), (1.5, 1)]):
        attempt = ARCCandidateAttemptV1(
            attempt_id=f"att_{index}",
            candidate_id=f"cand_{index}",
            hypothesis=f"variant {index}",
            strategy_code=f"lookback_period = {10 + index}\nstop_loss = 0.1",
            observed_metrics={"sharpe_after_attack": score},
        )
        node = mcts.add_child(root.node_id, attempt)
        # Simulate prior visit counts to differentiate exploitation/exploration.
        for _ in range(visits):
            mcts.backpropagate(node.node_id, score)
        rollouts.append((node, True, score))

    # Plenty of budget: every rollout is a parent, plus archive elites
    # (here the root, elite of its own cell) reinforce the parent set.
    parents = mcts.select_mutation_parents(rollouts, remaining_budget=10)
    assert {"att_0", "att_1", "att_2"} <= {node.node_id for node in parents}
    assert "att_root" in {node.node_id for node in parents}

    # Budget pressure: strictly the top-UCB1 slice, elites do not dilute focus.
    squeezed = mcts.select_mutation_parents(rollouts, remaining_budget=1)
    assert len(squeezed) == 1
    # att_2 (high value, one visit) must outrank att_0 (high value, five visits):
    # the exploration bonus is exactly what UCB1 adds over raw score sorting.
    assert squeezed[0].node_id == "att_2"


def test_select_mutation_parents_appends_qd_elites():
    """精英反哺：档案里的 cell 精英加入父本集（去重、有界）。"""
    mcts = ARCMCTSEngine()
    root = mcts.add_root(
        ARCCandidateAttemptV1(
            attempt_id="att_root",
            candidate_id="cand_root",
            hypothesis="root",
            strategy_code="lookback_period = 20\nstop_loss = 0.12",
            observed_metrics={"sharpe_after_attack": 0.5},
        )
    )
    mcts.add_child(
        root.node_id,
        ARCCandidateAttemptV1(
            attempt_id="att_strong",
            candidate_id="cand_strong",
            hypothesis="strong in its cell",
            strategy_code="lookback_period = 5\nstop_loss = 0.08",
            observed_metrics={"sharpe_after_attack": 2.2},
        ),
    )
    weak = mcts.add_child(
        root.node_id,
        ARCCandidateAttemptV1(
            attempt_id="att_weak",
            candidate_id="cand_weak",
            hypothesis="weak",
            strategy_code="lookback_period = 50\nstop_loss = 0.05",
            observed_metrics={"sharpe_after_attack": 0.3},
        ),
    )
    rollouts = [(weak, False, 0.3)]

    parents = mcts.select_mutation_parents(rollouts, remaining_budget=1)

    # The only rollout leads the parent set; archive elites (root of its own
    # cell, and the strong performer from another cell) join as extra mutation
    # material even though they were not in this generation.
    assert parents[0].node_id == "att_weak"
    assert {node.node_id for node in parents[1:]} == {"att_root", "att_strong"}
