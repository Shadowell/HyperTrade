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
