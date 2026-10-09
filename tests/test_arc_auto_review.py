import hashlib
import json

import pytest
from hypertrade.arc.auto_review import auto_review_once
from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
from hypertrade.arc.paper_review import request_paper_review
from hypertrade.arc.store import configure_store, get_controller, reset_store, save_mission
from hypertrade.db import Database
from test_arc_selection_bias import stats


@pytest.fixture
def ready(monkeypatch):
    db = Database("sqlite:///:memory:")
    db.create_all()
    configure_store(db)
    service = EvolutionService(db)
    service.configure(
        EvolutionConfig(enabled=True, paper_review_mode="agent"), revision=0, actor="user"
    )
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="test",
            research_mode="avo",
            paper_review_required=True,
            symbols=["SOL-USDT-SWAP"],
        )
    )
    code = "class Candidate: pass"
    values = {
        "taker_fee_bps": 5.0,
        "maker_fee_bps": 2.0,
        "slippage_bps": 1.0,
        "funding_mode": "not_modeled",
    }
    policy = {
        "version": "research_costs.v1",
        "source": "bitpro_backtest_cost_resolver",
        "exchange": "okx",
        "market_type": "swap",
        "values": values,
    }
    policy["hash"] = hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    monkeypatch.setattr(
        "hypertrade.arc.auto_review.read_candidate_source",
        lambda sid: {
            "id": sid,
            "script_content": code,
            "config": {**values, "_freeze_research_costs": True, "_research_cost_policy": policy},
        },
    )
    ctrl.apply_event(
        "candidate_proposed",
        {
            "attempt": ARCCandidateAttemptV1(
                attempt_id="candidate",
                candidate_id="candidate",
                strategy_code=code,
                hypothesis="trend",
                strategy_spec={"symbol": "SOL-USDT-SWAP", "timeframe": "1H"},
            ).model_dump(mode="json")
        },
    )
    goal = ctrl.projection.goal
    start, end = goal.research_windows.window("final")
    ctrl.apply_event(
        "bitpro_self_tested",
        {
            "attempt_id": "candidate",
            "passed": True,
            "purpose": "final",
            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "bitpro_strategy_id": "44",
            "backtest_id": "55",
            "validation_id": "validated",
            "metrics": {
                "return_statistics": stats(),
                "net_return": 0.5,
                "sharpe": 2,
                "max_drawdown": 0.01,
                "trades": 100,
                "evaluation_window": {
                    "purpose": "final",
                    "start_date": str(start),
                    "end_date": str(end),
                    "research_id": goal.research_id,
                },
            },
        },
    )
    request_paper_review(ctrl)
    save_mission(ctrl)
    yield db, service, ctrl.mission_id
    reset_store()


class Runner:
    def __init__(self, ok=True):
        self.calls = 0
        self.ok = ok

    def resolve_and_provision_paper_trading(self, attempt, authorization):
        self.calls += 1
        assert authorization.allowed_actions == ["configure", "start", "observe"]
        assert authorization.max_capital_per_instance == 100
        return self.ok, "paper-independent" if self.ok else None, "candidate", "receipt"


def test_enabled_agent_reviews_and_starts_paper_once_without_human_identity(ready):
    db, _, mid = ready
    runner = Runner()
    assert auto_review_once(db, runner)["status"] == "paper_observing"
    assert auto_review_once(db, runner)["status"] == "idle"
    ctrl = get_controller(mid)
    assert runner.calls == 1
    assert ctrl.projection.paper_review["decision"]["identity_source"] == "agent_policy"
    assert ctrl.projection.goal.paper_review_mode == "agent"
    assert ctrl.projection.paper_review["automatic_evaluation"]["live_authorized"] is False
    assert ctrl.projection.attempts[0].paper_instance_id == "paper-independent"


@pytest.mark.parametrize("enabled,mode", [(False, "agent"), (True, "human")])
def test_disabled_or_human_mode_never_auto_starts(ready, enabled, mode):
    db, service, mid = ready
    service.configure(
        EvolutionConfig(enabled=enabled, paper_review_mode=mode), revision=1, actor="user"
    )
    runner = Runner()
    auto_review_once(db, runner)
    assert runner.calls == 0
    assert get_controller(mid).projection.state == "paper_review_ready"


def test_unknown_start_effect_is_not_retried(ready):
    db, _, mid = ready
    runner = Runner(ok=False)
    assert auto_review_once(db, runner)["status"] == "effect_unknown"
    auto_review_once(db, runner)
    assert runner.calls == 1
    assert get_controller(mid).projection.state == "needs_operator"


def test_configured_capital_limit_rejects_without_execution(ready):
    db, service, mid = ready
    service.configure(
        EvolutionConfig(enabled=True, paper_review_mode="agent", paper_capital=50),
        revision=1,
        actor="user",
    )
    runner = Runner()
    assert auto_review_once(db, runner)["status"] == "rejected"
    assert runner.calls == 0
    assert "capital" in get_controller(mid).projection.paper_review["decision"]["reason"]


def test_changed_version_cannot_be_approved_by_agent(ready):
    db, _, mid = ready
    ctrl = get_controller(mid)
    ctrl.projection.attempts[0].strategy_code += "\n# different"
    save_mission(ctrl)
    runner = Runner()
    assert auto_review_once(db, runner)["status"] == "blocked"
    assert runner.calls == 0


def test_agent_review_keeps_stream_open_and_labels_reviewer(ready):
    from hypertrade.arc.pipeline_view import build_pipeline_view
    from hypertrade.arc.streaming import stream_frames

    db, _, mid = ready
    ctrl = get_controller(mid)
    ctrl.apply_event("paper_review_policy_selected", {"mode": "agent", "policy_revision": 1})
    assert not any(kind == "checkpoint" for kind, _, _ in stream_frames(ctrl.projection, 0))
    pipeline = build_pipeline_view(ctrl.projection)
    assert (
        next(s for s in pipeline["stages"] if s["key"] == "approval")["label"] == "Agent 自动评审"
    )


def test_referee_rechecks_final_numbers_instead_of_trusting_passed_flag(ready):
    db, _, mid = ready
    ctrl = get_controller(mid)
    ctrl.projection.self_test_records[-1]["metrics"]["net_return"] = -0.5
    save_mission(ctrl)
    runner = Runner()
    outcome = auto_review_once(db, runner)
    assert outcome["status"] in {"blocked", "rejected"}
    assert runner.calls == 0


def test_configured_scope_does_not_approve_an_unrelated_task(ready):
    db, service, mid = ready
    service.configure(
        EvolutionConfig(enabled=True, paper_review_mode="agent", strategy_ids=[999]),
        revision=1,
        actor="user",
    )
    runner = Runner()
    auto_review_once(db, runner)
    assert runner.calls == 0
    assert get_controller(mid).projection.state == "paper_review_ready"


def test_relaxed_task_criteria_cannot_bypass_automatic_policy_floor(ready):
    from hypertrade.arc.auto_review import evaluate_auto_review
    from hypertrade.arc.contracts import ARCSuccessCriteriaV1

    _, _, mid = ready
    ctrl = get_controller(mid)
    ctrl.projection.goal.success_criteria = ARCSuccessCriteriaV1(
        min_oos_net_return=0,
        min_oos_sharpe=0,
        max_drawdown=1,
        min_trades=0,
    )
    ctrl.projection.self_test_records[-1]["metrics"]["trades"] = 1
    result = evaluate_auto_review(ctrl, EvolutionConfig(enabled=True, paper_review_mode="agent"))
    assert result["decision"] != "approve"
    assert any(reason.startswith("policy:") for reason in result["reasons"])


def test_unfrozen_legacy_candidate_is_rejected_without_touching_paper(ready, monkeypatch):
    db, _, mid = ready
    monkeypatch.setattr(
        "hypertrade.arc.auto_review.read_candidate_source",
        lambda sid: {
            "id": sid,
            "script_content": "class Candidate: pass",
            "config": {},
        },
    )
    runner = Runner()
    assert auto_review_once(db, runner)["status"] == "rejected"
    assert runner.calls == 0
    assert (
        get_controller(mid).projection.paper_review["decision"]["identity_source"] == "agent_policy"
    )


def test_cost_source_outage_waits_without_starting(ready, monkeypatch):
    db, _, _ = ready

    def unavailable(sid):
        raise ConnectionError("upstream unavailable")

    monkeypatch.setattr("hypertrade.arc.auto_review.read_candidate_source", unavailable)
    runner = Runner()
    assert auto_review_once(db, runner)["status"] == "blocked"
    assert runner.calls == 0


def test_automatic_budget_end_does_not_require_human_to_release_source(ready):
    from hypertrade.arc.feedback import _feedback_child_active

    _, _, mid = ready
    ctrl = get_controller(mid)
    ctrl.apply_event("paper_review_policy_selected", {"mode": "agent", "policy_revision": 1})
    ctrl.apply_event("operator_needed", {"reason": "avo_model_budget_exhausted"})
    assert _feedback_child_active(ctrl) is False
    ctrl.projection.avo["pending"] = {"kind": "tool", "id": "unsettled"}
    assert _feedback_child_active(ctrl) is True


def test_auto_approve_paper_when_metrics_significantly_better(ready):
    db, service, mid = ready
    ctrl = get_controller(mid)
    goal = ctrl.projection.goal
    start, end = goal.research_windows.window("final")
    window = {
        "purpose": "final",
        "start_date": str(start),
        "end_date": str(end),
        "research_id": goal.research_id,
    }
    # Configure human review mode, but enable auto_approve_paper
    service.configure(
        EvolutionConfig(enabled=True, paper_review_mode="human", auto_approve_paper=True),
        revision=1,
        actor="user",
    )
    # Inject baseline final backtest metrics
    ctrl.projection.avo["baseline_final"] = {
        "backtest_id": "base-55",
        "metrics": {
            "evaluation_window": window,
            "net_return": 0.2,
            "max_drawdown": 0.05,
            "sharpe": 1.2,
        },
    }
    save_mission(ctrl)

    # Candidate in ready fixture has net_return=0.5 (>0.2), sharpe=2 (>1.2), max_dd=0.01 (<0.05)
    runner = Runner()
    result = auto_review_once(db, runner)
    assert result["status"] == "paper_observing"
    assert runner.calls == 1

    ctrl_after = get_controller(mid)
    decision = ctrl_after.projection.paper_review.get("decision") or {}
    assert decision.get("decision") == "approve"
    assert "Auto-Approve" in decision.get("reason", "")
    assert ctrl_after.projection.state == "paper_observing"


def test_auto_approve_paper_leaves_in_review_ready_when_metrics_not_better(ready):
    db, service, mid = ready
    ctrl = get_controller(mid)
    goal = ctrl.projection.goal
    start, end = goal.research_windows.window("final")
    window = {
        "purpose": "final",
        "start_date": str(start),
        "end_date": str(end),
        "research_id": goal.research_id,
    }
    service.configure(
        EvolutionConfig(enabled=True, paper_review_mode="human", auto_approve_paper=True),
        revision=1,
        actor="user",
    )
    # Baseline metrics are superior to candidate (e.g. sharpe=3 > candidate's sharpe=2)
    ctrl.projection.avo["baseline_final"] = {
        "backtest_id": "base-55",
        "metrics": {
            "evaluation_window": window,
            "net_return": 0.8,
            "max_drawdown": 0.005,
            "sharpe": 3.0,
        },
    }
    save_mission(ctrl)

    runner = Runner()
    result = auto_review_once(db, runner)
    assert result["status"] == "idle"
    assert runner.calls == 0
    # Still safely waiting in paper_review_ready for human operator
    assert get_controller(mid).projection.state == "paper_review_ready"


def test_verify_significantly_better_than_baseline_helper():
    from hypertrade.arc.auto_review import verify_significantly_better_than_baseline

    window = {"start_date": "2026-01-01", "end_date": "2026-01-14"}
    base_entry = {
        "backtest_id": "b1",
        "metrics": {
            "evaluation_window": window,
            "net_return": 0.15,
            "max_drawdown": 0.08,
            "sharpe": 1.5,
        },
    }

    # Case 1: Sharpe significantly higher, return higher, drawdown lower -> Pass
    cand_better = {
        "evaluation_window": window,
        "net_return": 0.25,
        "max_drawdown": 0.05,
        "sharpe": 2.2,
    }
    better, reasons = verify_significantly_better_than_baseline(cand_better, base_entry)
    assert better is True
    assert reasons == []

    # Case 2: Sharpe degraded -> Fail
    cand_worse_sharpe = {
        "evaluation_window": window,
        "net_return": 0.20,
        "max_drawdown": 0.05,
        "sharpe": 1.2,
    }
    better, reasons = verify_significantly_better_than_baseline(cand_worse_sharpe, base_entry)
    assert better is False
    assert "sharpe_below_baseline" in reasons

    # Case 3: Drawdown worse -> Fail
    cand_worse_dd = {
        "evaluation_window": window,
        "net_return": 0.25,
        "max_drawdown": 0.12,
        "sharpe": 2.2,
    }
    better, reasons = verify_significantly_better_than_baseline(cand_worse_dd, base_entry)
    assert better is False
    assert "drawdown_worse_than_baseline" in reasons

    # Case 4: No improvement at all (identical) -> Fail
    cand_identical = {
        "evaluation_window": window,
        "net_return": 0.15,
        "max_drawdown": 0.08,
        "sharpe": 1.5,
    }
    better, reasons = verify_significantly_better_than_baseline(cand_identical, base_entry)
    assert better is False
    assert "no_significant_improvement" in reasons

    # Case 5: Missing baseline -> Fail
    better, reasons = verify_significantly_better_than_baseline(cand_better, {})
    assert better is False
    assert "missing_baseline_evidence" in reasons

