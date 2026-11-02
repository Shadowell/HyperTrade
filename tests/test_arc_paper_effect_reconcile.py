"""A Paper start whose receipt was lost is adopted only from BitPro's own live session."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from hypertrade.arc import paper_effect_reconcile
from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution_continuation import acceptance_entries
from hypertrade.arc.paper_effect_reconcile import (
    reconcile_paper_effects_once,
    reconcile_paper_start,
)
from hypertrade.arc.paper_review import (
    build_paper_review,
    decide_paper_review,
    request_paper_review,
)
from hypertrade.arc.store import reset_store

CODE = "class X: pass"
INSTANCE = "paper_bound"
STRATEGY_VERSION = "sha256:" + "a" * 64
CONFIG_VERSION = "sha256:" + "c" * 64
SESSION_STARTED = "2026-10-24T05:58:32.532641+00:00"
START_FAILED = f"bitpro_paper_start_failed:BitProMcpError:instance_id={INSTANCE}"


class _FailedStart:
    """HyperTrade configured a session at BitPro, then the start request failed."""

    def __init__(
        self, controller: ARCController, message: str, *, configured: bool = True
    ) -> None:
        self.controller = controller
        self.message = message
        self.configured = configured

    def resolve_and_provision_paper_trading(self, attempt: Any, preauth: Any):
        if self.configured:
            self.controller.apply_event(
                "paper_review_configured",
                {
                    "schema_version": "paper_review_receipt.v1",
                    "package_hash": preauth.policy_hash,
                    "paper_instance_id": INSTANCE,
                    "ok": True,
                    "strategy_id": 445,
                    "guard_version": "paper_review_binding.v1",
                    "review_hash": preauth.policy_hash,
                    "code_sha256": hashlib.sha256(attempt.strategy_code.encode()).hexdigest(),
                    "strategy_version": STRATEGY_VERSION,
                    "config_version": CONFIG_VERSION,
                },
            )
        return False, None, "candidate", self.message


class _Snapshots:
    """BitPro's read-only paper snapshot."""

    def __init__(self, payload: dict[str, Any] | None = None, error: Exception | None = None):
        self.payload = payload if payload is not None else snapshot_payload()
        self.error = error
        self.calls: list[tuple[int | None, str | None]] = []

    def paper_snapshot(self, *, strategy_id: int | None = None, instance_id: str | None = None):
        self.calls.append((strategy_id, instance_id))
        if self.error is not None:
            raise self.error
        return self.payload


def snapshot_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "instance_id": INSTANCE,
        "strategy_id": 445,
        "strategy_version": STRATEGY_VERSION,
        "config_version": CONFIG_VERSION,
        "status": "running",
        "trade_count": 3,
        "session": {"started_at": SESSION_STARTED},
        "strategy": {"symbols": ["BTC-USDT-SWAP"]},
        **overrides,
    }


def _parked(message: str = START_FAILED, *, configured: bool = True) -> ARCController:
    reset_store()
    paper_effect_reconcile._last_checked.clear()
    controller = ARCController(goal=ARCGoalV1(objective="研究", paper_review_required=True))
    controller.apply_event(
        "candidate_proposed",
        {
            "attempt": ARCCandidateAttemptV1(
                attempt_id="attempt-review",
                candidate_id="candidate-review",
                hypothesis="trend",
                strategy_code=CODE,
                state="validated",
                bitpro_strategy_id="445",
                bitpro_backtest_id="450",
                validation_id="validation-450",
            ).model_dump()
        },
    )
    request_paper_review(controller)
    decide_paper_review(
        controller,
        package_hash=build_paper_review(controller.projection)["package_hash"],
        decision="approve",
        reason="已阅读证据",
        operator_id="operator",
        identity_source="hypertrade_session",
        idempotency_key="review-1",
        resolver=_FailedStart(controller, message, configured=configured),
    )
    assert controller.projection.state == "needs_operator"
    assert controller.projection.paper_review["status"] == "effect_unknown"
    return controller


@pytest.fixture(autouse=True)
def _clean_store():
    yield
    reset_store()
    paper_effect_reconcile._last_checked.clear()


def test_adopts_the_exact_session_bitpro_is_running() -> None:
    controller = _parked()
    client = _Snapshots()

    result = reconcile_paper_start(controller, client)

    assert result["status"] == "reconciled"
    assert client.calls == [(445, INSTANCE)]
    projection = controller.projection
    assert projection.state == "paper_observing"
    assert projection.paper_review["status"] == "paper_observing"
    assert projection.paper_review["paper_instance_id"] == INSTANCE
    assert projection.paper_review["previous_message"] == START_FAILED
    assert projection.attempts[0].paper_instance_id == INSTANCE
    assert projection.attempts[0].state == "paper_observing"
    # The session's own start time is kept, not the time of the reconciliation.
    assert projection.paper_started_at == datetime.fromisoformat(SESSION_STARTED)
    assert projection.events[-1].event_type == "paper_review_effect_reconciled"


def test_reconciled_start_replays_to_the_same_projection() -> None:
    controller = _parked()
    reconcile_paper_start(controller, _Snapshots())

    restored = ARCController(mission_id=controller.mission_id, goal=controller.projection.goal)
    for event in controller.projection.events:
        restored.absorb(event)

    assert restored.projection.state == "paper_observing"
    assert restored.projection.paper_review == controller.projection.paper_review
    assert restored.projection.paper_started_at == controller.projection.paper_started_at


def test_reconciled_start_counts_as_the_reviewed_start_stage() -> None:
    controller = _parked()
    reconcile_paper_start(controller, _Snapshots())

    entries = acceptance_entries(controller.projection, datetime.now(UTC))

    starts = [e for e in entries if e["stage"] == "reviewed_start"]
    assert [e["result"] for e in starts] == ["passed"]
    unknown_effects = [e for e in entries if e["stage"] == "external_effect"]
    assert [e["result"] for e in unknown_effects] == ["unknown"]


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"status": "stopped"}, "session_status_stopped"),
        ({"status": "configured"}, "session_status_configured"),
        ({"strategy_version": "sha256:" + "b" * 64}, "strategy_version_mismatch"),
        ({"config_version": "sha256:" + "d" * 64}, "config_version_mismatch"),
        ({"session": {}}, "session_not_started"),
        (
            {"session": {"started_at": SESSION_STARTED, "ended_at": "2026-10-30T00:00:00+00:00"}},
            "session_ended",
        ),
        (
            {"session": {"started_at": SESSION_STARTED, "error_level": "critical"}},
            "session_error_level_critical",
        ),
    ],
)
def test_a_session_that_differs_from_the_configured_one_is_not_adopted(override, reason) -> None:
    controller = _parked()

    result = reconcile_paper_start(controller, _Snapshots(snapshot_payload(**override)))

    assert result["status"] == "unverified"
    assert reason in result["reasons"]
    assert controller.projection.state == "needs_operator"
    assert controller.projection.paper_review["status"] == "effect_unknown"


def test_another_instance_is_never_adopted() -> None:
    controller = _parked()

    result = reconcile_paper_start(controller, _Snapshots(snapshot_payload(instance_id="paper_x")))

    assert result == {"status": "unverified", "reasons": ["snapshot_identity_mismatch"]}
    assert controller.projection.state == "needs_operator"


def test_unreadable_bitpro_changes_nothing() -> None:
    controller = _parked()

    result = reconcile_paper_start(controller, _Snapshots(error=RuntimeError("503")))

    assert result == {"status": "unverified", "reasons": ["snapshot_read_failed:RuntimeError"]}
    assert controller.projection.state == "needs_operator"


@pytest.mark.parametrize(
    "message",
    ["bitpro_paper_configure_failed:BitProMcpError:strategy_id=445", "timeout"],
)
def test_failures_before_the_start_request_are_left_for_an_operator(message) -> None:
    controller = _parked(message)
    client = _Snapshots()

    result = reconcile_paper_start(controller, client)

    assert result == {"status": "skipped", "reason": "failure_not_at_start_stage"}
    assert client.calls == []
    assert controller.projection.state == "needs_operator"


def test_a_start_failure_without_a_configure_receipt_is_left_for_an_operator() -> None:
    controller = _parked(configured=False)
    client = _Snapshots()

    result = reconcile_paper_start(controller, client)

    assert result == {"status": "skipped", "reason": "configure_receipt_missing"}
    assert client.calls == []
    assert controller.projection.state == "needs_operator"


def test_unconfirmed_receipt_after_a_real_start_is_also_reconciled() -> None:
    controller = _parked("bitpro_started_review_binding_unconfirmed")

    assert reconcile_paper_start(controller, _Snapshots())["status"] == "reconciled"


def test_verify_only_mode_does_not_write() -> None:
    controller = _parked()
    events_before = len(controller.projection.events)

    result = reconcile_paper_start(controller, _Snapshots(), apply=False)

    assert result["status"] == "verified"
    assert len(controller.projection.events) == events_before
    assert controller.projection.state == "needs_operator"


def test_a_mission_is_adopted_only_once() -> None:
    controller = _parked()
    assert reconcile_paper_start(controller, _Snapshots())["status"] == "reconciled"

    again = reconcile_paper_start(controller, _Snapshots())

    assert again == {"status": "skipped", "reason": "no_unknown_paper_effect"}


def test_reducer_refuses_reconciliation_that_is_not_bound_to_an_unknown_effect() -> None:
    controller = _parked()
    package_hash = controller.projection.paper_review["package_hash"]
    payload = {"package_hash": package_hash, "ok": True, "paper_instance_id": INSTANCE}

    with pytest.raises(PermissionError):
        controller.apply_event("paper_review_effect_reconciled", {**payload, "ok": False})
    with pytest.raises(PermissionError):
        controller.apply_event(
            "paper_review_effect_reconciled", {**payload, "package_hash": "f" * 64}
        )
    assert controller.projection.state == "needs_operator"

    controller.apply_event("paper_review_effect_reconciled", payload)
    assert controller.projection.state == "paper_observing"
    # Once adopted the effect is no longer unknown, so the same event cannot be applied again.
    with pytest.raises(PermissionError):
        controller.apply_event("paper_review_effect_reconciled", payload)


def test_reducer_requires_the_parked_state_not_only_the_unknown_status() -> None:
    controller = _parked()
    package_hash = controller.projection.paper_review["package_hash"]
    # A resumed mission keeps its unknown receipt; adopting it must not resurrect old state.
    controller.projection.state = "paper_provisioning"

    with pytest.raises(PermissionError):
        controller.apply_event(
            "paper_review_effect_reconciled",
            {"package_hash": package_hash, "ok": True, "paper_instance_id": INSTANCE},
        )
    assert controller.projection.state == "paper_provisioning"


def test_a_rejected_review_can_never_be_adopted_as_a_started_paper() -> None:
    reset_store()
    controller = ARCController(goal=ARCGoalV1(objective="研究", paper_review_required=True))
    controller.apply_event(
        "candidate_proposed",
        {
            "attempt": ARCCandidateAttemptV1(
                attempt_id="attempt-review",
                candidate_id="candidate-review",
                hypothesis="trend",
                strategy_code=CODE,
                state="validated",
                bitpro_strategy_id="445",
                bitpro_backtest_id="450",
                validation_id="validation-450",
            ).model_dump()
        },
    )
    request_paper_review(controller)
    package_hash = build_paper_review(controller.projection)["package_hash"]
    decide_paper_review(
        controller,
        package_hash=package_hash,
        decision="reject",
        reason="证据不足",
        operator_id="operator",
        identity_source="hypertrade_session",
        idempotency_key="review-1",
    )
    # Rejection also parks the mission in needs_operator, but with a rejected, not unknown, effect.
    assert controller.projection.state == "needs_operator"
    assert controller.projection.paper_review["status"] == "rejected"

    with pytest.raises(PermissionError):
        controller.apply_event(
            "paper_review_effect_reconciled",
            {"package_hash": package_hash, "ok": True, "paper_instance_id": INSTANCE},
        )
    assert controller.projection.state == "needs_operator"
    assert controller.projection.attempts[0].paper_instance_id is None


def test_sweep_adopts_parked_missions_and_rechecks_unverified_ones_later() -> None:
    controller = _parked()
    stopped = _Snapshots(snapshot_payload(status="stopped"))

    first = reconcile_paper_effects_once(stopped, now=1000.0)
    immediately = reconcile_paper_effects_once(stopped, now=1060.0)
    later = reconcile_paper_effects_once(_Snapshots(), now=1000.0 + 601.0)

    assert (first["checked"], first["reconciled"]) == (1, 0)
    assert first["results"][0]["status"] == "unverified"
    assert immediately["checked"] == 0
    assert (later["checked"], later["reconciled"]) == (1, 1)
    assert controller.projection.state == "paper_observing"
    # Nothing parked is left to look at.
    assert reconcile_paper_effects_once(_Snapshots(), now=9999.0)["checked"] == 0


def test_worker_loop_sweeps_then_waits_for_the_configured_interval(monkeypatch) -> None:
    import asyncio

    from hypertrade import worker
    from hypertrade.config import Settings

    sweeps: list[int] = []
    sleeps: list[float] = []

    async def stop_after_first_wait(seconds: float) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(worker, "configure_store", lambda db: None)
    monkeypatch.setattr(worker.asyncio, "sleep", stop_after_first_wait)
    monkeypatch.setattr(
        paper_effect_reconcile,
        "reconcile_paper_effects_once",
        lambda: sweeps.append(1) or {"checked": 0, "reconciled": 0},
    )
    settings = Settings(ARC_PAPER_EFFECT_RECONCILE_INTERVAL_SECONDS=45)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.arc_paper_effect_reconcile_loop(None, settings=settings))

    assert sweeps == [1]
    assert sleeps == [45]


def test_reconciliation_is_on_by_default_and_can_be_switched_off() -> None:
    from hypertrade.config import Settings

    assert Settings().arc_paper_effect_reconcile_enabled is True
    assert Settings().arc_paper_effect_reconcile_interval_seconds == 120
    disabled = Settings(ARC_PAPER_EFFECT_RECONCILE_ENABLED=False)
    assert disabled.arc_paper_effect_reconcile_enabled is False
