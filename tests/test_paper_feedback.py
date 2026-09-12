from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypertrade.arc.contracts import PaperFeedbackPolicyV1
from hypertrade.arc.feedback import evaluate_windows


def series(values):
    start = datetime(2026, 8, 1, tzinfo=UTC)
    return [
        {"timestamp": (start + timedelta(hours=i)).isoformat(), "equity": str(v)}
        for i, v in enumerate(values)
    ]


def test_return_drop_ten_percentage_points_inclusive():
    values = [Decimal(100)] * 169 + [Decimal(90)] * 168
    result = evaluate_windows(
        series(values), datetime(2026, 8, 15, tzinfo=UTC), PaperFeedbackPolicyV1()
    )
    assert result["triggered"]
    assert result["reasons"] == ["return_drop", "drawdown_increase"]
    assert Decimal(result["return_drop_pp"]) == 10


def test_either_drawdown_or_return_triggers_and_threshold_configurable():
    values = [100] * 169 + [80] * 50 + [100] * 118
    result = evaluate_windows(
        series(values), datetime(2026, 8, 15, tzinfo=UTC), PaperFeedbackPolicyV1()
    )
    assert result["reasons"] == ["drawdown_increase"]
    assert not evaluate_windows(
        series(values), datetime(2026, 8, 15, tzinfo=UTC), PaperFeedbackPolicyV1(threshold_pp=21)
    )["triggered"]


@pytest.mark.parametrize("fault", ["gap", "nan", "zero", "duplicate", "short", "future"])
def test_bad_samples_never_trigger(fault):
    points = series([100] * 337)
    if fault == "gap":
        del points[50:60]
    if fault == "nan":
        points[80]["equity"] = "NaN"
    if fault == "zero":
        points[0]["equity"] = "0"
    if fault == "duplicate":
        points.insert(50, dict(points[49]))
    if fault == "short":
        points = points[48:]
    if fault == "future":
        points[-1]["timestamp"] = "2026-08-16T00:00:00Z"
    with pytest.raises(ValueError):
        evaluate_windows(points, datetime(2026, 8, 15, tzinfo=UTC), PaperFeedbackPolicyV1())


def test_same_window_comparison_requires_improvement_without_other_metric_regression():
    from hypertrade.arc.feedback import compare_backtests

    window = {"purpose": "final", "start_date": "2026-01-01", "end_date": "2026-02-01"}
    baseline = {
        "backtest_id": "old",
        "metrics": {"net_return": ".1", "max_drawdown": ".15", "evaluation_window": window},
    }
    assert compare_backtests(
        {"net_return": ".12", "max_drawdown": ".15", "evaluation_window": window}, baseline
    )["passed"]
    assert not compare_backtests(
        {"net_return": ".12", "max_drawdown": ".16", "evaluation_window": window}, baseline
    )["passed"]
    assert not compare_backtests(
        {"net_return": ".1", "max_drawdown": ".15", "evaluation_window": window}, baseline
    )["passed"]
    assert not compare_backtests(
        {"net_return": "NaN", "max_drawdown": ".1", "evaluation_window": window}, baseline
    )["passed"]


class PaperClient:
    def __init__(self):
        self.calls = 0

    def paper_snapshot(self, **kwargs):
        return {
            "instance_id": "paper-session",
            "strategy_id": 44,
            "status": "running",
            "strategy_version": "v1",
            "config_version": "c1",
            "session": {"started_at": "2026-08-01T00:00:00Z"},
        }

    def strategy_return_series(self, **kwargs):
        self.calls += 1
        start, end = (
            datetime.fromisoformat(kwargs["start_at"]),
            datetime.fromisoformat(kwargs["end_at"]),
        )
        points = series([100] * 169 + [90] * 168)
        points = [p for p in points if start <= datetime.fromisoformat(p["timestamp"]) <= end]
        return {
            "schema_version": "strategy_return_series.v1",
            "source_layer": "paper",
            "source_id": "paper-session",
            "strategy_id": 44,
            "strategy_version": "v1",
            "config_version": "c1",
            "currency": "USDT",
            "cost_model": {"fees": "net"},
            "bucket_seconds": 3600,
            "timezone": "UTC",
            "pagination": {"next_cursor": ""},
            "source_hash": "sha",
            "content_hash": "content",
            "points": points,
        }


def test_collects_bounded_days_and_rejects_changed_session():
    from hypertrade.arc.feedback import collect_windows

    client = PaperClient()
    result = collect_windows(
        client, "paper-session", "44", datetime(2026, 8, 15, tzinfo=UTC), PaperFeedbackPolicyV1()
    )
    assert result["triggered"] and len(result["receipts"]) == 56
    assert client.calls == 56
    with pytest.raises(ValueError):
        collect_windows(
            client,
            "wrong-session",
            "44",
            datetime(2026, 8, 15, tzinfo=UTC),
            PaperFeedbackPolicyV1(),
        )


def test_feedback_creates_one_child_keeps_parent_running_and_recovers_link(monkeypatch):
    from hypertrade.arc.adversarial import BlueTeamQuant
    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.feedback import check_paper_feedback
    from hypertrade.arc.store import get_controller, list_mission_ids, reset_store, save_mission

    reset_store()
    parent = ARCController(
        goal=ARCGoalV1(
            objective="trend",
            symbols=["SOL-USDT-SWAP", "DOGE-USDT-SWAP"],
            paper_review_required=True,
            research_mode="avo",
            feedback=PaperFeedbackPolicyV1(
                enabled=True,
                research_max_candidates=2,
                research_max_model_calls=8,
                research_max_backtests=4,
            ),
        )
    )
    attempt = BlueTeamQuant().propose_initial_strategy("trend", "DOGE-USDT-SWAP")
    attempt.bitpro_strategy_id = "44"
    attempt.paper_instance_id = "paper-session"
    parent.projection.attempts = [attempt]
    parent.projection.state = "paper_observing"
    save_mission(parent)
    now = datetime(2026, 8, 15, tzinfo=UTC)
    original = parent.apply_event

    def crash(event, payload):
        if event == "paper_feedback_checked":
            raise RuntimeError("crash after child creation")
        return original(event, payload)

    monkeypatch.setattr(parent, "apply_event", crash)
    with pytest.raises(RuntimeError):
        check_paper_feedback(parent.mission_id, PaperClient(), now)
    assert len(list_mission_ids()) == 2
    monkeypatch.setattr(parent, "apply_event", original)
    result = check_paper_feedback(parent.mission_id, PaperClient(), now)
    child = get_controller(result["child_mission_id"])
    assert child.projection.goal.feedback_parent["instance_id"] == "paper-session"
    assert child.projection.goal.budget.max_candidates == 2
    assert child.projection.goal.budget.max_model_calls == 8
    assert child.projection.goal.budget.max_backtests == 4
    assert child.projection.goal.symbols == ["DOGE-USDT-SWAP"]
    assert parent.projection.goal.symbols == ["SOL-USDT-SWAP", "DOGE-USDT-SWAP"]
    assert child.projection.goal.paper_authorization is None
    assert child.projection.goal.paper_review_required
    assert child.projection.goal.research_id == child.mission_id
    assert parent.projection.state == "paper_observing"
    assert parent.projection.attempts[0].paper_instance_id == "paper-session"
    assert (
        check_paper_feedback(parent.mission_id, PaperClient(), now + timedelta(days=1))["status"]
        == "child_active"
    )
    assert len(list_mission_ids()) == 2
    reset_store()


@pytest.mark.parametrize(
    "outcome",
    ["final_rejected", "development_exhausted", "unknown", "early_stop", "missing_metrics"],
)
def test_settled_child_releases_next_day_but_unknown_child_keeps_blocking(outcome):
    from hypertrade.arc.adversarial import BlueTeamQuant
    from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1
    from hypertrade.arc.controller import ARCController, ARCEventV1
    from hypertrade.arc.feedback import check_paper_feedback
    from hypertrade.arc.store import list_mission_ids, reset_store, save_mission

    reset_store()
    parent = ARCController(
        goal=ARCGoalV1(
            objective="trend",
            paper_review_required=True,
            research_mode="avo",
            feedback=PaperFeedbackPolicyV1(enabled=True),
        )
    )
    attempt = BlueTeamQuant().propose_initial_strategy("trend", "BTC-USDT-SWAP")
    attempt.bitpro_strategy_id = "44"
    attempt.paper_instance_id = "paper-session"
    parent.projection.attempts = [attempt]
    parent.projection.state = "paper_observing"
    child = ARCController(
        goal=ARCGoalV1(
            objective="tune",
            paper_review_required=True,
            research_mode="avo",
            budget=ARCBudgetV1(max_candidates=1, candidates_used=1),
        )
    )
    child.projection.state = "needs_operator"
    trial = attempt.model_copy(deep=True)
    trial.paper_instance_id = None
    child.projection.attempts = [trial]
    record = {
        "passed": False,
        "backtest_id": "real-shape-test-result",
        "metrics": {"net_return": -0.1, "sharpe": -1, "max_drawdown": 0.1, "trades": 100},
    }
    reason = "avo_final_validation_failed"
    child.projection.avo = {"final_window_consumed": True, "pending": None}
    child.projection.self_test_records = [record]
    if outcome in {"development_exhausted", "early_stop"}:
        reason = "avo_no_candidate"
        child.projection.avo = {"development": {trial.attempt_id: record}, "pending": None}
        if outcome == "early_stop":
            child.projection.goal.budget.max_candidates = 3
    if outcome == "unknown":
        reason = "avo_effect_unknown"
        child.projection.avo["pending"] = {"kind": "tool"}
    if outcome == "missing_metrics":
        record["metrics"] = {}
    child.projection.events = [
        ARCEventV1(
            mission_id=child.mission_id, event_type="operator_needed", payload={"reason": reason}
        )
    ]
    save_mission(child)
    parent.projection.paper_feedback = {
        "child_mission_id": child.mission_id,
        "checked_end_at": "2026-08-14T00:00:00+00:00",
    }
    save_mission(parent)
    now = datetime(2026, 8, 15, tzinfo=UTC)
    result = check_paper_feedback(parent.mission_id, PaperClient(), now)
    if outcome in {"final_rejected", "development_exhausted"}:
        assert result["child_mission_id"] != child.mission_id
        assert len(list_mission_ids()) == 3
        assert (
            check_paper_feedback(parent.mission_id, PaperClient(), now)["status"] == "child_active"
        )
    else:
        assert result["status"] == "child_active"
        assert len(list_mission_ids()) == 2
    assert parent.projection.state == "paper_observing"
    assert parent.projection.attempts[0].paper_instance_id == "paper-session"
    reset_store()
