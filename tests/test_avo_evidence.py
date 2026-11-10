from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evidence_view import build_evidence_view


def test_development_metrics_stay_separate_from_final_metrics():
    ctrl = ARCController(
        goal=ARCGoalV1(objective="test", paper_review_required=True, research_mode="avo")
    )
    attempt = ARCCandidateAttemptV1(
        attempt_id="a",
        candidate_id="c",
        hypothesis="test",
        strategy_code="class X: pass",
        observed_metrics={
            "sharpe_ratio": "1.5",
            "trade_count": 35,
            "evaluation_window": {"purpose": "development"},
        },
    )
    ctrl.projection.attempts.append(attempt)
    ctrl.projection.avo["development"] = {
        "a": {"attempt_id": "a", "backtest_id": "bt_dev", "purpose": "development"}
    }
    development = build_evidence_view(ctrl.projection)
    assert development["candidates"][0]["oos_sharpe"] is None
    assert development["research"]["development"][0]["backtest_id"] == "bt_dev"
    attempt.observed_metrics["evaluation_window"] = {"purpose": "final"}
    attempt.bitpro_backtest_id = "bt_final"
    final = build_evidence_view(ctrl.projection)
    assert final["candidates"][0]["oos_sharpe"] == 1.5
    assert final["candidates"][0]["trades"] == 35


def test_forward_outcome_memory_is_not_reported_as_development_reference():
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="test",
            research_mode="avo",
            paper_review_required=True,
            evolution_context={
                "memory": [
                    {
                        "mission_id": "m_dev",
                        "candidate_id": "c_dev",
                        "development": {"backtest_id": "bt_dev"},
                    },
                    {
                        "memory_id": "outcome:fo_1",
                        "type": "forward_outcome",
                        "mission_id": "m_outcome",
                        "candidate_id": "c_outcome",
                        "verdict": "won",
                        "relation": "made_current",
                        "generations_back": 1,
                        "parent_strategy_id": "43",
                        "challenger_strategy_id": "44",
                        "ended_at": "2026-01-01T00:00:00",
                    },
                ]
            },
        )
    )
    evolution = build_evidence_view(ctrl.projection)["research"]["evolution"]
    assert evolution["memory_references"] == [
        {"mission_id": "m_dev", "candidate_id": "c_dev", "backtest_id": "bt_dev"}
    ]
    assert evolution["forward_outcome_references"] == [
        {
            "memory_id": "outcome:fo_1",
            "verdict": "won",
            "relation": "made_current",
            "generations_back": 1,
            "parent_strategy_id": "43",
            "challenger_strategy_id": "44",
            "ended_at": "2026-01-01T00:00:00",
        }
    ]


def test_system_prompt_explains_ablations_without_causal_claims():
    from hypertrade.arc.avo import _SYSTEM

    assert "memory_id ablation:" in _SYSTEM
    assert "not causal conclusions" in _SYSTEM


def test_ablation_memory_id_is_citable_evidence():
    import pytest
    from hypertrade.arc.evolution_memory import bind_hypothesis

    proposal = {
        "evolution_hypothesis": {
            "evidence_refs": ["ablation:abl_x"],
            "expected_metric": "net_return",
            "expected_direction": "increase",
            "falsification": "Reject unless the single-factor rerun improves net return",
        }
    }
    context = {"memory": [{"memory_id": "ablation:abl_x", "type": "ablation"}]}

    bound = bind_hypothesis(proposal, context, {})
    assert bound["status"] == "hypothesis_not_causal_fact"

    with pytest.raises(ValueError, match="cites unavailable evidence"):
        bind_hypothesis(
            {
                "evolution_hypothesis": {
                    **proposal["evolution_hypothesis"],
                    "evidence_refs": ["ablation:missing"],
                }
            },
            context,
            {},
        )


def test_ablation_memory_is_reported_separately_from_development_references():
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="test",
            research_mode="avo",
            paper_review_required=True,
            evolution_context={
                "memory": [
                    {
                        "mission_id": "m_dev",
                        "candidate_id": "c_dev",
                        "development": {"backtest_id": "bt_dev"},
                    },
                    {
                        "memory_id": "outcome:fo_1",
                        "type": "forward_outcome",
                        "verdict": "lost_futility",
                        "relation": "variant_of_current",
                        "generations_back": 0,
                        "parent_strategy_id": "44",
                        "challenger_strategy_id": "4401",
                        "ended_at": "2026-01-03T00:00:00",
                    },
                    {
                        "memory_id": "ablation:run_4401",
                        "type": "ablation",
                        "outcome_id": "fo_1",
                        "verdict": "lost_futility",
                        "parent_strategy_id": "44",
                        "challenger_strategy_id": "4401",
                        "window": ["2026-03-15", "2026-07-12"],
                        "harmful": ["fast_window=20"],
                        "helpful": ["slow_window=40"],
                        "effects": [{"label": "fast_window=20", "class": "harmful"}],
                    },
                ]
            },
        )
    )
    evolution = build_evidence_view(ctrl.projection)["research"]["evolution"]

    assert evolution["memory_references"] == [
        {"mission_id": "m_dev", "candidate_id": "c_dev", "backtest_id": "bt_dev"}
    ]
    assert [row["memory_id"] for row in evolution["forward_outcome_references"]] == [
        "outcome:fo_1"
    ]
    assert evolution["ablation_references"] == [
        {
            "memory_id": "ablation:run_4401",
            "outcome_id": "fo_1",
            "verdict": "lost_futility",
            "parent_strategy_id": "44",
            "challenger_strategy_id": "4401",
            "window": ["2026-03-15", "2026-07-12"],
            "harmful": ["fast_window=20"],
            "helpful": ["slow_window=40"],
        }
    ]
