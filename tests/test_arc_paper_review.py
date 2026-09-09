from __future__ import annotations

import pytest
from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.paper_review import (
    build_paper_review,
    decide_paper_review,
    request_paper_review,
)
from hypertrade.arc.store import reset_store


@pytest.fixture
def controller():
    reset_store()
    ctrl = ARCController(goal=ARCGoalV1(objective="研究", paper_review_required=True))
    ctrl.apply_event(
        "candidate_proposed",
        {
            "attempt": ARCCandidateAttemptV1(
                attempt_id="attempt-review",
                candidate_id="candidate-review",
                hypothesis="trend",
                strategy_code="class X: pass",
                state="validated",
                bitpro_strategy_id="445",
                bitpro_backtest_id="450",
                validation_id="validation-450",
            ).model_dump()
        },
    )
    request_paper_review(ctrl)
    yield ctrl
    reset_store()


class Provisioner:
    calls = 0

    def resolve_and_provision_paper_trading(self, attempt, preauth):
        self.calls += 1
        assert attempt.bitpro_strategy_id == "445"
        assert preauth.allowed_actions == ["configure", "start", "observe"]
        return True, "9001", "candidate", "started"


def decide(ctrl, provisioner, **kwargs):
    return decide_paper_review(
        ctrl,
        package_hash=kwargs.pop(
            "package_hash", build_paper_review(ctrl.projection)["package_hash"]
        ),
        decision=kwargs.pop("decision", "approve"),
        reason="已阅读证据",
        operator_id="operator",
        identity_source="hypertrade_session",
        idempotency_key="review-1",
        resolver=provisioner,
        **kwargs,
    )


def test_candidate_waits_for_review_without_starting_paper(controller):
    assert controller.projection.state == "paper_review_ready"
    assert controller.projection.attempts[0].paper_instance_id is None
    assert build_paper_review(controller.projection)["status"] == "ready"


def test_approval_starts_once_and_replays_same_receipt(controller):
    runner = Provisioner()
    first = decide(controller, runner)
    second = decide(controller, runner)
    assert first["paper_instance_id"] == second["paper_instance_id"] == "9001"
    assert runner.calls == 1
    assert controller.projection.state == "paper_observing"
    assert second["idempotent"] is True


def test_rejection_has_no_paper_side_effect(controller):
    runner = Provisioner()
    decide(controller, runner, decision="reject")
    assert runner.calls == 0
    assert controller.projection.paper_review["status"] == "rejected"
    with pytest.raises(PermissionError):
        decide(controller, runner)


def test_modified_code_invalidates_review(controller):
    package_hash = build_paper_review(controller.projection)["package_hash"]
    controller.projection.attempts[0].strategy_code += "\n# changed"
    with pytest.raises(PermissionError, match="changed"):
        decide(controller, Provisioner(), package_hash=package_hash)


def test_reading_a_new_hash_cannot_approve_unrevalidated_code(controller):
    controller.projection.attempts[0].strategy_code += "\n# different code"
    runner = Provisioner()
    with pytest.raises(PermissionError):
        decide(controller, runner)
    assert runner.calls == 0


def test_missing_backtest_blocks_approval(controller):
    controller.projection.attempts[0].bitpro_backtest_id = None
    with pytest.raises(PermissionError):
        decide(controller, Provisioner())


def test_unknown_effect_is_not_blindly_retried(controller):
    class Unknown(Provisioner):
        def resolve_and_provision_paper_trading(self, attempt, preauth):
            self.calls += 1
            return False, None, None, "timeout"

    runner = Unknown()
    first = decide(controller, runner)
    second = decide(controller, runner)
    assert first["status"] == second["status"] == "effect_unknown"
    assert runner.calls == 1


def test_claim_is_exclusive_even_before_effect_finishes(controller):
    runner = Provisioner()
    package = build_paper_review(controller.projection)
    controller.apply_event(
        "paper_review_decided",
        {
            "package_hash": package["package_hash"],
            "decision": "approve",
            "idempotency_key": "first",
            "operator_id": "op",
            "identity_source": "hypertrade_session",
            "reason": "reviewed",
        },
    )
    with pytest.raises(PermissionError):
        decide(controller, runner)
    assert runner.calls == 0


def test_replay_restores_review_and_instance(controller):
    decide(controller, Provisioner())
    restored = ARCController(mission_id=controller.mission_id, goal=controller.projection.goal)
    for event in controller.projection.events:
        restored.absorb(event)
    assert restored.projection.paper_review == controller.projection.paper_review
    assert restored.projection.attempts[0].paper_instance_id == "9001"


def test_real_loop_defers_all_paper_effects_until_review(monkeypatch):
    import hypertrade.arc.router as router
    from test_arc_acceptance import _flat_window, _goal, _pass_self_test, _start

    goal = _goal()
    goal.paper_review_required = True
    ctrl = _start(goal)
    monkeypatch.setattr(router, "build_default_window", lambda: _flat_window())
    monkeypatch.setattr(router, "ARCSelfTestService", _pass_self_test)
    monkeypatch.setattr(
        router.ARCAdversarialEngine,
        "run_adversarial_session",
        lambda *args: (
            True,
            {"ranking_basis": "out_of_sample", "ranking_sharpe": 1.4},
            [],
        ),
    )

    def forbidden(*args):
        raise AssertionError("Paper must not execute before review")

    monkeypatch.setattr(
        router.ARCPaperIncubationResolver, "resolve_and_provision_paper_trading", forbidden
    )
    router.run_autonomous_arc_loop(ctrl.mission_id)
    assert ctrl.projection.state == "paper_review_ready"
    assert not any(a.paper_instance_id for a in ctrl.projection.attempts)
    from hypertrade.arc.pipeline_view import build_pipeline_view

    pipeline = build_pipeline_view(ctrl.projection)
    assert pipeline["current_stage"] == "approval"
    assert [stage["key"] for stage in pipeline["stages"]][-2:] == ["approval", "paper"]
    reset_store()
