import hashlib

import pytest
from hypertrade.arc.avo import _perform, needs_research
from hypertrade.arc.evolution_memory import bind_hypothesis
from hypertrade.arc.paper_review import build_paper_review
from hypertrade.arc.self_test import SelfTestResult
from test_arc_paper_review import controller as controller_fixture
from test_backtest_action_recovery import action as action_fixture

action = action_fixture
controller = controller_fixture


@pytest.mark.parametrize(
    "metric,direction",
    [("trade_count", "decrease"), ("net_return", "decrease"), ("max_drawdown", "increase")],
)
def test_activity_or_worsening_is_not_an_improvement_objective(metric, direction):
    with pytest.raises(ValueError, match="improvement"):
        bind_hypothesis(
            {
                "evolution_hypothesis": {
                    "evidence_refs": ["paper_feedback"],
                    "expected_metric": metric,
                    "expected_direction": direction,
                    "falsification": "Reject unless measured net excess return improves",
                }
            },
            {"paper_feedback": {"status": "observed"}},
            {},
        )


def test_falsification_required_even_without_attribution_report():
    with pytest.raises(ValueError, match="falsification"):
        bind_hypothesis(
            {
                "evolution_hypothesis": {
                    "evidence_refs": ["paper_feedback"],
                    "expected_metric": "net_return",
                    "expected_direction": "increase",
                }
            },
            {"paper_feedback": {"status": "observed"}},
            {},
        )


def test_operator_pause_is_not_overridden_by_recorded_development(action):
    action.projection.avo["development"] = {
        "a": {
            "tool_call_id": "call",
            "attempt_id": "a",
            "backtest_id": "r",
            "code_sha256": hashlib.sha256(b"code").hexdigest(),
        }
    }
    action.apply_event("operator_needed", {"reason": "operator_paused"})
    assert not needs_research(action.projection)


def test_failed_execution_closes_epoch_instead_of_becoming_mutation_feedback(action):
    class Broken:
        def run(self, *args, **kwargs):
            return SelfTestResult(
                False,
                None,
                "7",
                None,
                terminal_failure={"job_id": "failed-job", "status": "failed", "stage": "baseline"},
            )

    result = _perform(action, "develop", {"attempt_id": "a"}, Broken(), recovering=True)
    action.apply_event("avo_tool_finished", {"id": "call", "result": result, "recovered": True})
    assert action.projection.state == "failed"
    assert action.projection.avo["pending"] is None
    assert result["terminal_failure"]["job_id"] == "failed-job"


def test_stored_review_cannot_select_failed_candidate(controller):
    controller.projection.attempts[0].state = "failed"
    review = build_paper_review(controller.projection)
    assert review["status"] == "incomplete"
    assert "candidate_not_validated" in review["unknowns"]


def test_comparison_requires_identical_execution_and_verified_data():
    from copy import deepcopy

    from hypertrade.arc.feedback import compare_backtests

    evidence = {
        "status": "completed",
        "runtime_sha256": "r",
        "cost_policy_hash": "c",
        "data_manifests": ["d"],
        "symbols": ["BTC"],
        "timeframes": ["1h"],
        "initial_capital": 100,
        "start_date": "2026-01-01",
        "end_date": "2026-02-01",
    }
    baseline = {
        "backtest_id": "b",
        "metrics": {
            "net_return": -0.1,
            "max_drawdown": 0.2,
            "evaluation_window": {"purpose": "final"},
            "comparison_evidence": evidence,
        },
    }
    candidate = {**deepcopy(baseline["metrics"]), "net_return": 0.1}
    assert compare_backtests(candidate, baseline)["passed"]
    for key, value in [
        ("runtime_sha256", "other"),
        ("data_manifests", ["other"]),
        ("cost_policy_hash", None),
        ("status", "failed"),
    ]:
        changed = deepcopy(candidate)
        changed["comparison_evidence"][key] = value
        assert not compare_backtests(changed, baseline)["passed"]


def test_evolution_review_requires_matching_final_receipt(controller):
    controller.projection.goal.evolution_context = {"source_strategy_id": 1}
    selected = controller.projection.attempts[0]
    selected.observed_metrics = {"baseline_comparison": {"passed": True, "backtest_id": "b"}}
    assert (
        "missing_matching_final_validation_receipt"
        in build_paper_review(controller.projection)["unknowns"]
    )
    receipt = {
        "attempt_id": selected.attempt_id,
        "purpose": "final",
        "passed": True,
        "backtest_id": selected.bitpro_backtest_id,
        "validation_id": selected.validation_id,
        "bitpro_strategy_id": selected.bitpro_strategy_id,
        "code_sha256": hashlib.sha256(selected.strategy_code.encode()).hexdigest(),
        "metrics": selected.observed_metrics.copy(),
    }
    controller.projection.self_test_records.append(receipt)
    assert (
        "missing_matching_final_validation_receipt"
        not in build_paper_review(controller.projection)["unknowns"]
    )
    receipt["passed"] = False
    assert (
        "missing_matching_final_validation_receipt"
        in build_paper_review(controller.projection)["unknowns"]
    )
