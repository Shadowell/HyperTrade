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
    def __init__(self, attempt=None):
        self.calls = 0
        self.code = attempt.strategy_code if attempt else "class Source: pass"
        self.symbol = attempt.strategy_spec["symbol"] if attempt else "BTC-USDT-SWAP"

    def paper_strategy_performance(self, **kwargs):
        return {"strategies": [{"strategy_id": 44, "mode": "paper", "timeframe": "1H"}]}

    def strategy_get(self, **kwargs):
        return {
            "strategy": {
                "id": kwargs["strategy_id"],
                "script_content": self.code,
                "config": {"timeframe": "1H"},
            }
        }

    def strategy_trades(self, **kwargs):
        return [
            {
                "id": 1,
                "strategy_id": 44,
                "timestamp": 1786665600000,
                "symbol": "BTC-USDT-SWAP",
                "fee": 1,
                "pnl": -1,
            }
        ]

    def paper_snapshot(self, **kwargs):
        return {
            "trade_count": 60,
            "strategy": {"symbols": [self.symbol]},
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
        client, "paper-session", "44", datetime(2026, 8, 15, tzinfo=UTC), PaperFeedbackPolicyV1(),
        benchmark_symbols=["BTC-USDT-SWAP"],
    )
    assert result["triggered"] and len(result["receipts"]) == 56
    assert result["degradation_basis"] == "absolute"
    assert result["benchmark"]["status"] == "unknown_timeframe"
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
    from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
    from hypertrade.arc.store import configure_store
    from hypertrade.db import Database

    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    EvolutionService(db).configure(EvolutionConfig(enabled=True), revision=0, actor="test")
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
        check_paper_feedback(parent.mission_id, PaperClient(attempt), now)
    assert len(list_mission_ids()) == 2
    monkeypatch.setattr(parent, "apply_event", original)
    result = check_paper_feedback(parent.mission_id, PaperClient(attempt), now)
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
        check_paper_feedback(parent.mission_id, PaperClient(attempt), now + timedelta(days=1))[
            "status"
        ]
        == "child_active"
    )
    assert len(list_mission_ids()) == 2
    reset_store()


@pytest.mark.parametrize(
    "outcome",
    [
        "final_rejected",
        "development_exhausted",
        "unknown",
        "early_stop",
        "missing_metrics",
        "final_rejected_deflated_sharpe",
        "final_rejected_deflated_sharpe_pending_effect",
        "deflated_sharpe_evidence_missing",
        "deflated_sharpe_probability_invalid",
    ],
)
def test_settled_child_releases_next_day_but_unknown_child_keeps_blocking(outcome):
    from hypertrade.arc.adversarial import BlueTeamQuant
    from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1
    from hypertrade.arc.controller import ARCController, ARCEventV1
    from hypertrade.arc.feedback import check_paper_feedback
    from hypertrade.arc.store import list_mission_ids, reset_store, save_mission

    reset_store()
    from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
    from hypertrade.arc.store import configure_store
    from hypertrade.db import Database

    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    EvolutionService(db).configure(EvolutionConfig(enabled=True), revision=0, actor="test")
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
    passing = {"net_return": 0.08, "sharpe": 1.5, "max_drawdown": 0.05, "trades": 100}
    if outcome in {
        "final_rejected_deflated_sharpe",
        "final_rejected_deflated_sharpe_pending_effect",
    }:
        record["metrics"] = {
            **passing,
            "selection_bias": {"status": "observed", "probability": 0.65},
        }
    if outcome == "deflated_sharpe_evidence_missing":
        record["metrics"] = {**passing, "selection_bias": {"status": "unavailable"}}
    if outcome == "deflated_sharpe_probability_invalid":
        record["metrics"] = {**passing, "selection_bias": {"status": "observed"}}
    reason = "avo_final_validation_failed"
    child.projection.avo = {"final_window_consumed": True, "pending": None}
    if outcome == "final_rejected_deflated_sharpe_pending_effect":
        child.projection.avo["pending"] = {"kind": "tool"}
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
    result = check_paper_feedback(parent.mission_id, PaperClient(attempt), now)
    if outcome in {
        "final_rejected",
        "final_rejected_deflated_sharpe",
        "development_exhausted",
        "early_stop",
    }:
        assert result["child_mission_id"] != child.mission_id
        assert len(list_mission_ids()) == 3
        assert (
            check_paper_feedback(parent.mission_id, PaperClient(attempt), now)["status"]
            == "child_active"
        )
    else:
        assert result["status"] == "child_active"
        assert len(list_mission_ids()) == 2
    assert parent.projection.state == "paper_observing"
    assert parent.projection.attempts[0].paper_instance_id == "paper-session"
    reset_store()


def test_comparison_normalizes_signed_drawdown_before_judging_improvement():
    from hypertrade.arc.feedback import compare_backtests

    window = {"purpose": "final", "start_date": "2026-01-01", "end_date": "2026-02-01"}
    baseline = {
        "backtest_id": "source",
        "metrics": {
            "net_return": 0.1,
            "max_drawdown": 0.1,
            "evaluation_window": window,
        },
    }
    assert not compare_backtests(
        {
            "net_return": 0.2,
            "max_drawdown": -0.15,
            "evaluation_window": window,
        },
        baseline,
    )["passed"]
    baseline["metrics"]["max_drawdown"] = -0.1
    assert compare_backtests(
        {
            "net_return": 0.2,
            "max_drawdown": 0.08,
            "evaluation_window": window,
        },
        baseline,
    )["passed"]


_PASSING_METRICS = {"net_return": 0.08, "sharpe": 1.5, "max_drawdown": 0.05, "trades": 100}
_LOW_DSR = {"status": "observed", "probability": 0.65}


@pytest.mark.parametrize(
    ("passed", "backtest_id", "metrics", "expected"),
    [
        pytest.param(
            False,
            "bt-1",
            {"net_return": -0.1, "sharpe": -1, "max_drawdown": 0.1, "trades": 100},
            True,
            id="numeric_miss",
        ),
        pytest.param(
            False,
            "bt-1",
            {**_PASSING_METRICS, "selection_bias": _LOW_DSR},
            True,
            id="deflated_sharpe_low",
        ),
        pytest.param(
            False,
            "bt-1",
            {**_PASSING_METRICS, "selection_bias": {"status": "observed", "probability": 0.0}},
            True,
            id="deflated_sharpe_probability_zero",
        ),
        pytest.param(
            False,
            "bt-1",
            {
                "net_return": -0.1,
                "sharpe": -1,
                "max_drawdown": 0.1,
                "trades": 100,
                "selection_bias": _LOW_DSR,
            },
            True,
            id="numeric_miss_and_deflated_sharpe_low",
        ),
        pytest.param(
            False,
            "bt-1",
            {
                "sharpe_ratio": "0.2079",
                "max_drawdown_pct": "3.9278",
                "trade_count": 32,
                "total_return_pct": "1.4766986266013902",
                "selection_bias": {
                    "status": "observed",
                    "probability": 0.6502542403161149,
                    "num_trials": 2,
                },
                "baseline_comparison": {
                    "passed": False,
                    "backtest_id": "bt-base",
                    "net_return": "0.026645792531116115",
                    "max_drawdown": "0.025218",
                },
            },
            True,
            id="production_shape_509",
        ),
        pytest.param(
            False,
            "bt-1",
            {
                "sharpe_ratio": "0.5688",
                "max_drawdown_pct": "2.9267",
                "trade_count": 142,
                "total_return_pct": "5.199891540505959",
                "selection_bias": {
                    "status": "observed",
                    "probability": 0.8506382862034549,
                    "num_trials": 3,
                },
                "baseline_comparison": {
                    "passed": False,
                    "backtest_id": "bt-base",
                    "net_return": "0.0327",
                    "max_drawdown": "0.0263",
                },
            },
            True,
            id="production_shape_513",
        ),
        pytest.param(
            False,
            "bt-1",
            {
                **_PASSING_METRICS,
                "baseline_comparison": {"passed": False, "backtest_id": "bt-base"},
            },
            True,
            id="baseline_not_improved_after_gates",
        ),
        pytest.param(
            False,
            "bt-1",
            {**_PASSING_METRICS, "selection_bias": {"status": "unavailable"}},
            False,
            id="deflated_sharpe_evidence_missing",
        ),
        pytest.param(
            False,
            "bt-1",
            {**_PASSING_METRICS, "selection_bias": {"status": "observed"}},
            False,
            id="deflated_sharpe_observed_without_probability",
        ),
        pytest.param(
            False,
            "bt-1",
            {
                **_PASSING_METRICS,
                "selection_bias": {"status": "observed", "probability": float("nan")},
            },
            False,
            id="deflated_sharpe_probability_not_finite",
        ),
        pytest.param(
            False,
            "bt-1",
            {**_PASSING_METRICS, "selection_bias": {"status": "observed", "probability": 1.7}},
            False,
            id="deflated_sharpe_probability_above_one",
        ),
        pytest.param(
            False,
            "bt-1",
            {**_PASSING_METRICS, "selection_bias": {"status": "observed", "probability": -0.2}},
            False,
            id="deflated_sharpe_probability_negative",
        ),
        pytest.param(
            False,
            "bt-1",
            {
                "net_return": 0.08,
                "max_drawdown": 0.05,
                "trades": 100,
                "selection_bias": _LOW_DSR,
            },
            False,
            id="deflated_sharpe_low_but_sharpe_missing",
        ),
        pytest.param(False, "bt-1", {}, False, id="metrics_missing"),
        pytest.param(
            False,
            "bt-1",
            dict(_PASSING_METRICS),
            False,
            id="baseline_comparison_missing",
        ),
        pytest.param(
            True,
            "bt-1",
            {**_PASSING_METRICS, "selection_bias": _LOW_DSR},
            False,
            id="record_passed",
        ),
        pytest.param(
            False,
            None,
            {**_PASSING_METRICS, "selection_bias": _LOW_DSR},
            False,
            id="no_backtest_id",
        ),
    ],
)
def test_negative_experiment_finished_classifies_settled_and_unsettled_rejections(
    passed, backtest_id, metrics, expected
):
    from hypertrade.arc.contracts import ARCGoalV1, ARCSuccessCriteriaV1
    from hypertrade.arc.feedback import _negative_experiment_finished

    goal = ARCGoalV1(
        objective="tune",
        success_criteria=ARCSuccessCriteriaV1(
            min_oos_net_return=Decimal("1E-8"),
            min_oos_sharpe=Decimal(0),
            max_drawdown=Decimal("0.2"),
            min_trades=30,
            required_validation_policy="arc_windowed_v1",
        ),
    )
    record = {"passed": passed, "backtest_id": backtest_id, "metrics": metrics}
    assert _negative_experiment_finished(record, goal) is expected


@pytest.mark.parametrize(
    ("reason", "selection", "expected"),
    [
        pytest.param(
            "sharpe -1.0 below success_criteria.min_oos_sharpe 0",
            None,
            True,
            id="numeric_gate_miss",
        ),
        pytest.param(
            "deflated_sharpe_probability_below_0.95",
            {"status": "observed", "probability": 0.65},
            True,
            id="observed_low_probability",
        ),
        pytest.param(
            "deflated_sharpe_probability_below_0.95",
            {"status": "observed", "probability": 0.0},
            True,
            id="observed_zero_probability",
        ),
        pytest.param(
            "deflated_sharpe_probability_below_0.95",
            {"status": "observed", "probability": 0.95},
            False,
            id="probability_at_the_gate",
        ),
        pytest.param(
            "deflated_sharpe_probability_below_0.95",
            {"status": "pending", "probability": 0.65},
            False,
            id="evidence_not_observed",
        ),
        pytest.param(
            "deflated_sharpe_probability_below_0.95",
            {"status": "observed", "probability": False},
            False,
            id="bool_false_probability",
        ),
        pytest.param(
            "deflated_sharpe_probability_below_0.95",
            {"status": "observed", "probability": True},
            False,
            id="bool_true_probability",
        ),
        pytest.param(
            "deflated_sharpe_probability_below_0.95",
            {"status": "observed", "probability": "0.65"},
            False,
            id="string_probability",
        ),
        pytest.param(
            "deflated_sharpe_probability_below_0.95", None, False, id="selection_bias_missing"
        ),
        pytest.param(
            "deflated_sharpe_unknown:server_trial_evidence_required",
            {"status": "observed", "probability": 0.65},
            False,
            id="evidence_missing_reason",
        ),
        pytest.param(
            "sharpe not reported by the backtest result", None, False, id="metric_not_reported"
        ),
    ],
)
def test_settled_rejection_takes_verdicts_only_from_observed_evidence(reason, selection, expected):
    from hypertrade.arc.feedback import _settled_rejection

    metrics = {} if selection is None else {"selection_bias": selection}
    assert _settled_rejection(reason, metrics) is expected
