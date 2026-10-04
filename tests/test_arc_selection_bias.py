"""Selection evidence must come from server history and complete return observations."""

from decimal import Decimal

import pytest
from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1, ResearchWindowsV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.selection_bias import selection_evidence
from hypertrade.arc.store import reset_store, save_mission
from hypertrade.research.sharpe import calculate_deflated_sharpe_ratio, equity_return_statistics


def stats(sr=0.25):
    return {
        "schema_version": "return_statistics.v1",
        "status": "observed",
        "sample_length": 500,
        "period_seconds": 86400,
        "period_sharpe": sr,
        "skewness": 0.0,
        "kurtosis": 3.0,
        "series_sha256": "a" * 64,
    }


def candidate(name):
    return ARCCandidateAttemptV1(
        attempt_id=name,
        candidate_id=name,
        hypothesis="measured hypothesis",
        strategy_code=f"class Strategy{name}: pass",
        strategy_spec={"timeframe": "1D"},
    )


def test_paper_dsr_example_uses_probability_and_unannualized_sharpe():
    # Bailey & Lopez de Prado (2014), pp. 9-10: 46 trials clear 95%.
    probability = calculate_deflated_sharpe_ratio(
        2.5 / (250**0.5),
        46,
        sample_length=1250,
        skewness=-3,
        kurtosis=10,
        trial_sharpe_variance=0.5 / 250,
    )
    assert probability == pytest.approx(0.9505, abs=0.001)


def test_statistics_reject_irregular_or_partial_curves():
    rows = [{"timestamp": i * 86400000, "equity": 100 + i + (i % 2)} for i in range(6)]
    assert equity_return_statistics(rows)["status"] == "observed"
    rows[-1]["timestamp"] += 1
    assert equity_return_statistics(rows)["status"] == "unknown"


@pytest.fixture
def mission():
    reset_store()
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="research",
            paper_review_required=True,
            research_mode="avo",
            research_windows=ResearchWindowsV1(),
            paper_initial_equity=Decimal("100"),
        )
    )
    save_mission(ctrl)
    yield ctrl
    reset_store()


def test_trials_use_server_receipts_not_metric_claims(mission):
    first, second = candidate("one"), candidate("two")
    for item in (first, second):
        mission.apply_event("candidate_proposed", {"attempt": item.model_dump(mode="json")})
        mission.apply_event("avo_development_requested", {"attempt_id": item.attempt_id})
        mission.apply_event(
            "avo_development_result",
            {
                "attempt_id": item.attempt_id,
                "result": {
                    "backtest_id": "bt-" + item.attempt_id,
                    "code_sha256": __import__("hashlib")
                    .sha256(item.strategy_code.encode())
                    .hexdigest(),
                    "metrics": {"return_statistics": stats(0.1 if item is first else 0.3)},
                },
            },
        )
    evidence = selection_evidence(
        mission,
        second,
        {
            "num_trials": 1,
            "trial_count": 1,
            "return_statistics": stats(),
        },
    )
    assert evidence["num_trials"] == 2
    assert evidence["status"] == "observed"
    assert len(evidence["trial_refs"]) == 2


def test_missing_statistics_cannot_fall_back_to_one_trial(mission):
    item = candidate("missing")
    evidence = selection_evidence(mission, item, {"sharpe_ratio": 3, "num_trials": 1})
    assert evidence["status"] == "unknown"
    assert evidence["reason"] == "return_statistics_missing"


def test_failed_earlier_research_is_counted_and_missing_receipt_blocks(mission):
    first = candidate("failed")
    mission.apply_event("candidate_proposed", {"attempt": first.model_dump(mode="json")})
    mission.apply_event("avo_development_requested", {"attempt_id": first.attempt_id})
    other = ARCController(goal=mission.projection.goal.model_copy(deep=True))
    save_mission(other)
    evidence = selection_evidence(other, candidate("new"), {"return_statistics": stats()})
    assert evidence["num_trials"] == 2
    assert evidence["status"] == "unknown"
    assert evidence["reason"] == "trial_statistics_incomplete"


def test_full_bitpro_curve_statistics_survive_ui_sample_limit():
    from hypertrade.bitpro.mcp import _backtest_detail_item

    rows = [
        {"timestamp": 1770000000000 + i * 3600000, "equity": 100 + i + i % 2} for i in range(100)
    ]
    result = _backtest_detail_item({"id": "bt-full", "equity_curve": rows}, sample_limit=20)
    assert result["artifacts"]["equity_curve"]["sample_count"] == 20
    assert result["metrics"]["return_statistics"]["sample_length"] == 99
    assert result["metrics"]["return_statistics"]["period_seconds"] == 3600
    partial = _backtest_detail_item({"equity_curve": rows, "truncated": True}, sample_limit=20)
    assert partial["metrics"]["return_statistics"]["status"] == "unknown"
    for flag in ({"has_more": True}, {"next_cursor": "page2"}, {"total": 200}):
        partial = _backtest_detail_item({"equity_curve": {"items": rows, **flag}}, sample_limit=20)
        assert partial["metrics"]["return_statistics"]["status"] == "unknown"


def test_injected_experiment_success_without_statistics_is_blocked(mission):
    from hypertrade.arc.avo import run_avo_research
    from test_avo_research import Experiments, ScriptProvider

    class MissingStatistics(Experiments):
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            result.metrics.pop("return_statistics", None)
            result.metrics["num_trials"] = 1
            return result

    # Normal production AVO orchestration must enforce its gate even if an
    # experiment implementation incorrectly claims passed=True.
    mission.projection.goal.success_criteria.required_validation_policy = "arc_windowed_v1"
    provider = ScriptProvider()
    run_avo_research(mission.mission_id, provider=provider, experiments=MissingStatistics())
    assert mission.projection.state == "needs_operator"
    receipt = mission.projection.self_test_records[-1]
    assert receipt["metrics"]["selection_bias"]["num_trials"] == 2
    assert receipt["metrics"]["selection_bias"]["status"] == "unknown"
    assert not receipt["passed"]
