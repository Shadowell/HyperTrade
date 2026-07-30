"""
Unit & Integration Tests for Phase 4: Multi-Agent Parallel MCTS Rollout Engine
"""

from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.mcts import ARCParallelMCTSEngine, MAPElitesGrid, MCTSNode


def test_map_elites_atomic_add():
    grid = MAPElitesGrid()

    attempt1 = ARCCandidateAttemptV1(
        attempt_id="att_p1",
        candidate_id="cand_p1",
        hypothesis="Test P1",
        strategy_code="class Strategy_P1:\n    lookback_period = 20\n",
        observed_metrics={"sharpe_after_attack": 1.2},
    )
    node1 = MCTSNode(
        node_id="att_p1",
        attempt=attempt1,
        total_value=1.2,
        visits=1,
        feature_descriptor=("medium_term", "ranging_moderate"),
    )

    attempt2 = ARCCandidateAttemptV1(
        attempt_id="att_p2",
        candidate_id="cand_p2",
        hypothesis="Test P2",
        strategy_code="class Strategy_P2:\n    lookback_period = 20\n",
        observed_metrics={"sharpe_after_attack": 1.8},
    )
    node2 = MCTSNode(
        node_id="att_p2",
        attempt=attempt2,
        total_value=1.8,
        visits=1,
        feature_descriptor=("medium_term", "ranging_moderate"),
    )

    assert grid.add_candidate(node1) is True
    assert grid.add_candidate(node2) is True
    elites = grid.get_elites()
    assert len(elites) == 1
    assert elites[0].node_id == "att_p2"


def test_arc_parallel_mcts_engine_rollout():
    engine = ARCParallelMCTSEngine(parallel_workers=4)

    cand1 = ARCCandidateAttemptV1(
        attempt_id="cand_w1",
        candidate_id="cand_w1",
        hypothesis="Worker 1",
        strategy_code="class Strategy_W1:\n    stop_loss = 0.08\n",
    )
    cand2 = ARCCandidateAttemptV1(
        attempt_id="cand_w2",
        candidate_id="cand_w2",
        hypothesis="Worker 2",
        strategy_code="class Strategy_W2:\n    stop_loss = 0.08\n",
    )

    def dummy_eval(cand: ARCCandidateAttemptV1) -> tuple[bool, float]:
        return True, 1.85

    results = engine.execute_parallel_rollout(dummy_eval, [cand1, cand2])
    assert len(results) == 2
    for _cand, passed, score in results:
        assert passed is True
        assert score == 1.85
