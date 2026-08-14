from datetime import UTC, datetime, timedelta

import pytest
from hypertrade.arc.contracts import (
    ARCCandidateAttemptV1,
    ARCGoalV1,
    LiveApprovalPackageV1,
    PaperObservationPolicyV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.live_approval import assert_approvable, build_live_approval_package
from hypertrade.arc.live_promote import decide_live_approval
from hypertrade.arc.observation import observe_mission
from hypertrade.arc.store import reset_store


def _ready_controller() -> ARCController:
    reset_store()
    goal = ARCGoalV1(
        objective="live",
        observation=PaperObservationPolicyV1(min_hours=0, min_trades=2),
    )
    ctrl = ARCController(goal=goal)
    ctrl.apply_event("goal_compiled", {"goal": goal.model_dump()})
    ctrl.apply_event(
        "candidate_proposed",
        {
            "attempt": ARCCandidateAttemptV1(
                attempt_id="att_live",
                candidate_id="cand_live",
                state="validated",
                hypothesis="x",
                strategy_code="class X: pass",
                bitpro_strategy_id="9",
                bitpro_backtest_id="bt_9",
                validation_id="val_9",
                observed_metrics={
                    "sharpe": 1.4,
                    "max_drawdown": 0.08,
                    "trades": 20,
                    "net_return": 0.12,
                },
            ).model_dump()
        },
    )
    ctrl.apply_event("paper_started", {"attempt_id": "att_live", "paper_instance_id": "77"})
    ctrl.projection.paper_started_at = datetime.now(UTC) - timedelta(hours=1)
    ctrl.projection.paper_observation = {
        "ok": True,
        "instance_matched": True,
        "trades": 8,
        "equity": 10050,
        "net_return": 0.05,
        "max_drawdown": 0.03,
        "sharpe": 1.1,
        "status": "running",
        "bitpro_health": "healthy",
    }
    return ctrl


def test_package_without_backtest_ref_is_incomplete() -> None:
    ctrl = _ready_controller()
    ctrl.projection.attempts[0].bitpro_backtest_id = None
    package = build_live_approval_package(ctrl.projection)
    assert package.status == "incomplete"
    assert "missing_backtest_ref" in package.unknowns
    with pytest.raises(PermissionError, match="incomplete"):
        assert_approvable(package)


def test_package_built_from_copied_backtest_numbers_is_rejected_by_refs() -> None:
    package = LiveApprovalPackageV1(
        mission_id="arc_fake",
        status="ready",
        recommendation="approve",
        package_hash="deadbeef",
        strategy={"bitpro_strategy_id": "1"},
        backtest={"sharpe": 9.9, "trades": 99},
        paper={"trades": 99, "net_return": 0.5},
        comparison={},
        unknowns=[],
        live_intent={"max_capital_u": "100"},
    )
    with pytest.raises(PermissionError, match="missing BitPro refs"):
        assert_approvable(package)


def test_ready_package_can_be_approved_and_promoted_once() -> None:
    ctrl = _ready_controller()
    package = build_live_approval_package(ctrl.projection)
    ctrl.apply_event("live_approval_ready", {"package": package.model_dump(mode="json")})

    class _Promote:
        def __init__(self) -> None:
            self.calls = 0

        def authorized_live_promote(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls += 1
            assert kwargs["approval_package_hash"] == package.package_hash
            return {"status": "ok", "promotion": {"live_instance_id": "live_1"}}

    client = _Promote()
    first = decide_live_approval(
        ctrl,
        decision="approve",
        reason="numbers match the package",
        operator_id="jie",
        idempotency_key="live-1",
        client=client,
    )
    second = decide_live_approval(
        ctrl,
        decision="approve",
        reason="repeat",
        operator_id="jie",
        idempotency_key="live-1",
        client=client,
    )
    assert first["status"] == "live_canary"
    assert first["live_instance_id"] == "live_1"
    assert second["idempotent"] is True
    assert client.calls == 1
    reset_store()


def test_reject_does_not_promote() -> None:
    ctrl = _ready_controller()
    package = build_live_approval_package(ctrl.projection)
    ctrl.apply_event("live_approval_ready", {"package": package.model_dump(mode="json")})

    class _Promote:
        def authorized_live_promote(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("reject must not promote")

    result = decide_live_approval(
        ctrl,
        decision="reject",
        reason="paper decay",
        operator_id="jie",
        idempotency_key="live-reject",
        client=_Promote(),
    )
    assert result["decision"] == "rejected"
    assert ctrl.projection.state == "needs_operator"
    assert not any(item.live_instance_id for item in ctrl.projection.attempts)
    reset_store()


def test_observe_completes_window_from_bitpro_snapshot() -> None:
    ctrl = _ready_controller()
    ctrl.projection.paper_observation = {}
    ctrl.projection.state = "paper_observing"

    class _Client:
        def paper_snapshot(self, **kwargs):  # type: ignore[no-untyped-def]
            return {
                "snapshot": {
                    "instance_id": "77",
                    "status": "running",
                    "trade_count": 8,
                    "equity": 10100,
                    "cumulative_return_pct": 0.01,
                    "max_drawdown_pct": 0.02,
                    "sharpe_ratio": 1.0,
                }
            }

        def health(self) -> dict:
            return {"status": "ok", "health": {"status": "healthy"}}

    result = observe_mission(ctrl, _Client())
    assert result["status"] == "live_approval_ready"
    assert ctrl.projection.live_approval is not None
    assert ctrl.projection.live_approval.paper["trades"] == 8
    reset_store()
