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
