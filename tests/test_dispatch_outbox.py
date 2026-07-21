from __future__ import annotations

from pathlib import Path

import pytest
from hypertrade.db import Database
from hypertrade.runtime.adapters.effect_store import (
    InMemoryEffectGovernanceStore,
    SqlEffectGovernanceStore,
)
from hypertrade.runtime.application.effect_governance import (
    EffectGovernanceService,
    EffectReconciliationRequired,
    InjectedEffectCrash,
)
from hypertrade.runtime.domain.capabilities import CapabilityDefinitionV1, reviewed_snapshot
from hypertrade.runtime.domain.effects import EffectAckV1, EffectResolutionV1


def _snapshot():
    return reviewed_snapshot(
        CapabilityDefinitionV1(
            capability_id="isolated.outbox_fixture",
            title="Outbox fixture",
            description="An isolated idempotent write fixture.",
            source_owner="hypertrade-tests",
            handler_key="isolated.outbox_fixture",
            scope="research_write",
            side_effect="idempotent_write",
            approval="none",
            idempotency="required",
        ),
        snapshot_id="outbox-fixture",
    )


class FakeEffectAdapter:
    def __init__(self) -> None:
        self.dispatch_calls = 0
        self.committed: set[str] = set()

    async def dispatch(self, intent, arguments):
        self.dispatch_calls += 1
        self.committed.add(intent.idempotency_key)
        return EffectAckV1(
            external_operation_id=f"fake:{intent.idempotency_key}",
            result={"accepted": True},
        )

    async def reconcile(self, intent):
        committed = intent.idempotency_key in self.committed
        return EffectResolutionV1(
            outcome="committed" if committed else "not_committed",
            external_operation_id=f"fake:{intent.idempotency_key}" if committed else "",
            result={"accepted": True} if committed else {},
            reason="isolated adapter idempotency lookup completed",
        )


async def _prepare(
    service: EffectGovernanceService, *, key: str, value: int = 1, fencing_token: int = 7
):
    arguments = {"resource": "LAB", "value": value}
    decision = await service.evaluate(
        _snapshot(),
        arguments,
        mission_id="mis_outbox",
        subject="operator-a",
        account="fixture-account",
        environment="isolated",
        role="research_operator",
        budget={},
        policy_snapshot={"revision": "outbox-v1"},
    )
    intent, call = await service.prepare_dispatch(
        decision.decision_id,
        arguments,
        operation_scope=("fixture:LAB",),
        idempotency_key=key,
        fencing_token=fencing_token,
        reconciliation_policy="idempotency_key",
    )
    return arguments, intent, call


@pytest.mark.anyio
async def test_sql_dispatch_intent_survives_restart_before_external_call(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'effect-outbox.db'}"
    Database(database_url).create_all()
    first_store = SqlEffectGovernanceStore(database_url)
    first_service = EffectGovernanceService(first_store)
    arguments, intent, _ = await _prepare(first_service, key="durable-outbox-message")
    await first_store.dispose()

    reopened_store = SqlEffectGovernanceStore(database_url)
    reopened_service = EffectGovernanceService(reopened_store)
    adapter = FakeEffectAdapter()
    try:
        persisted_intent, persisted_call = await reopened_store.dispatch(intent.intent_id)
        completed = await reopened_service.execute(intent.intent_id, arguments, adapter)
        events = await reopened_store.audit_events(intent.intent_id)
    finally:
        await reopened_store.dispose()

    assert persisted_intent.status == "prepared"
    assert persisted_call.status == "prepared"
    assert completed.status == "succeeded"
    assert adapter.dispatch_calls == 1
    assert [event.event_type for event in events][-3:] == [
        "tool_call.dispatched",
        "tool_call.acknowledged",
        "tool_call.succeeded",
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("crash_after", "expected_dispatches", "resolution"),
    [
        ("dispatch_persisted", 0, "not_committed"),
        ("adapter_return", 1, "committed"),
    ],
)
async def test_crash_around_external_call_requires_reconciliation_without_redispatch(
    crash_after: str,
    expected_dispatches: int,
    resolution: str,
) -> None:
    store = InMemoryEffectGovernanceStore()
    service = EffectGovernanceService(store)
    arguments, intent, _ = await _prepare(service, key=f"crash-{crash_after}")
    adapter = FakeEffectAdapter()

    with pytest.raises(InjectedEffectCrash):
        await service.execute(intent.intent_id, arguments, adapter, crash_after=crash_after)
    with pytest.raises(EffectReconciliationRequired):
        await service.execute(intent.intent_id, arguments, adapter)
    call, reconciled = await service.recover_orphan(intent.intent_id, adapter)

    assert adapter.dispatch_calls == expected_dispatches
    assert reconciled is not None
    assert reconciled.outcome == resolution
    assert call.status == "reconciled"


@pytest.mark.anyio
async def test_crash_after_ack_recovers_terminal_without_second_dispatch() -> None:
    store = InMemoryEffectGovernanceStore()
    service = EffectGovernanceService(store)
    arguments, intent, _ = await _prepare(service, key="crash-after-ack")
    adapter = FakeEffectAdapter()

    with pytest.raises(InjectedEffectCrash):
        await service.execute(intent.intent_id, arguments, adapter, crash_after="ack")
    completed, resolution = await service.recover_orphan(intent.intent_id, adapter)
    replay = await service.execute(intent.intent_id, arguments, adapter)

    assert completed.status == replay.status == "succeeded"
    assert resolution is None
    assert adapter.dispatch_calls == 1


@pytest.mark.anyio
async def test_idempotency_key_rejects_different_payload() -> None:
    store = InMemoryEffectGovernanceStore()
    service = EffectGovernanceService(store)
    await _prepare(service, key="content-bound-message", value=1)

    with pytest.raises(ValueError, match="different dispatch payload"):
        await _prepare(service, key="content-bound-message", value=2)


@pytest.mark.anyio
async def test_stale_worker_fencing_cannot_create_a_second_intent() -> None:
    store = InMemoryEffectGovernanceStore()
    service = EffectGovernanceService(store)
    await _prepare(service, key="new-worker-intent", fencing_token=9)

    with pytest.raises(PermissionError, match="stale dispatch fencing"):
        await _prepare(service, key="stale-worker-intent", fencing_token=8)
