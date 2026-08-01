from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypertrade.db import Database
from hypertrade.runtime.adapters.effect_store import (
    InMemoryEffectGovernanceStore,
    SqlEffectGovernanceStore,
)
from hypertrade.runtime.application import effect_governance as module
from hypertrade.runtime.application.effect_governance import EffectGovernanceService
from hypertrade.runtime.domain.capabilities import CapabilityDefinitionV1, reviewed_snapshot


def _snapshot():
    return reviewed_snapshot(
        CapabilityDefinitionV1(
            capability_id="isolated.approval_fixture",
            title="Approval fixture",
            description="An isolated approval lifecycle fixture.",
            source_owner="hypertrade-tests",
            handler_key="isolated.approval_fixture",
            scope="research_write",
            side_effect="idempotent_write",
            approval="required",
            idempotency="required",
        ),
        snapshot_id="approval-fixture",
    )


async def _approved(service: EffectGovernanceService):
    decision = await service.evaluate(
        _snapshot(),
        {"resource": "LAB", "amount": "1"},
        mission_id="mis_approval",
        subject="operator-a",
        account="account-a",
        environment="isolated",
        role="reviewer",
        budget={"maximum_amount": "1"},
        policy_snapshot={"revision": "approval-v1"},
    )
    request = await service.request_approval(
        decision.decision_id,
        resource_scope=("fixture:LAB",),
        maximum_amount="1",
        requested_by="operator-a",
    )
    issued = await service.grant_approval(
        request.request_id,
        actor="human-reviewer",
        reason="exact isolated fixture parameters reviewed",
    )
    return decision, request, issued


@pytest.mark.anyio
async def test_approval_is_single_use_but_same_dispatch_message_replays() -> None:
    store = InMemoryEffectGovernanceStore()
    service = EffectGovernanceService(store)
    decision, request, issued = await _approved(service)
    kwargs = {
        "operation_scope": ("fixture:LAB",),
        "fencing_token": 3,
        "reconciliation_policy": "idempotency_key",
        "approval_request_id": request.request_id,
        "approval_grant_id": issued.grant.grant_id,
        "approval_token": issued.consumption_token,
    }
    first = await service.prepare_dispatch(
        decision.decision_id,
        {"resource": "LAB", "amount": "1"},
        idempotency_key="approval-consume-once",
        **kwargs,
    )
    replay = await service.prepare_dispatch(
        decision.decision_id,
        {"resource": "LAB", "amount": "1"},
        idempotency_key="approval-consume-once",
        **kwargs,
    )

    assert replay == first
    persisted_request, persisted_grant = await store.approval(request.request_id)
    assert persisted_request.status == "consumed"
    assert persisted_grant is not None
    assert persisted_grant.consumed_intent_id == first[0].intent_id
    with pytest.raises(PermissionError, match="not consumable"):
        await service.prepare_dispatch(
            decision.decision_id,
            {"resource": "LAB", "amount": "1"},
            idempotency_key="approval-second-dispatch",
            **kwargs,
        )
    approval_events = await store.audit_events(request.request_id)
    assert sum(row.event_type == "approval.consumed" for row in approval_events) == 1
    assert approval_events[-1].event_type == "approval.consumption_rejected"


@pytest.mark.anyio
async def test_expired_revoked_and_agent_self_grants_are_rejected(monkeypatch) -> None:
    clock = datetime(2030, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(module, "_now", lambda: clock)
    store = InMemoryEffectGovernanceStore()
    service = EffectGovernanceService(store)
    decision = await service.evaluate(
        _snapshot(),
        {"resource": "LAB"},
        mission_id="mis_expiry",
        subject="operator-a",
        account="account-a",
        environment="isolated",
        role="reviewer",
        budget={},
        policy_snapshot={"revision": "approval-v1"},
    )
    request = await service.request_approval(
        decision.decision_id,
        resource_scope=("fixture:LAB",),
        maximum_amount="1",
        requested_by="operator-a",
        ttl_seconds=1,
    )
    with pytest.raises(PermissionError, match="cannot grant"):
        await service.grant_approval(request.request_id, actor="agent", reason="self grant")
    monkeypatch.setattr(module, "_now", lambda: clock + timedelta(seconds=2))
    with pytest.raises(PermissionError, match="expired"):
        await service.grant_approval(request.request_id, actor="human-reviewer", reason="too late")
    expired, _ = await store.approval(request.request_id)
    assert expired.status == "expired"

    monkeypatch.setattr(module, "_now", lambda: clock)
    _, second_request, issued = await _approved(service)
    await service.revoke_approval(
        second_request.request_id, actor="human-reviewer", reason="scope withdrawn"
    )
    revoked, revoked_grant = await store.approval(second_request.request_id)
    assert revoked.status == "revoked"
    assert revoked_grant is not None and revoked_grant.status == "revoked"
    assert issued.consumption_token


@pytest.mark.anyio
async def test_cross_account_approval_binding_is_rejected() -> None:
    store = InMemoryEffectGovernanceStore()
    service = EffectGovernanceService(store)
    _, request, issued = await _approved(service)
    other = await service.evaluate(
        _snapshot(),
        {"resource": "LAB", "amount": "1"},
        mission_id="mis_approval",
        subject="operator-a",
        account="account-b",
        environment="isolated",
        role="reviewer",
        budget={"maximum_amount": "1"},
        policy_snapshot={"revision": "approval-v1"},
    )
    with pytest.raises(PermissionError, match="does not match"):
        await service.prepare_dispatch(
            other.decision_id,
            {"resource": "LAB", "amount": "1"},
            operation_scope=("fixture:LAB",),
            idempotency_key="cross-account-dispatch",
            fencing_token=1,
            reconciliation_policy="idempotency_key",
            approval_request_id=request.request_id,
            approval_grant_id=issued.grant.grant_id,
            approval_token=issued.consumption_token,
        )


@pytest.mark.anyio
async def test_sql_approval_token_is_private_durable_and_consumable(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'approval.db'}"
    Database(database_url).create_all()
    first_store = SqlEffectGovernanceStore(database_url)
    first_service = EffectGovernanceService(first_store)
    decision, request, issued = await _approved(first_service)
    public = issued.model_dump(mode="json")
    await first_store.dispose()

    assert "consumption_token" not in public
    assert "token_hash" not in public["grant"]
    reopened_store = SqlEffectGovernanceStore(database_url)
    reopened = EffectGovernanceService(reopened_store)
    try:
        intent, _ = await reopened.prepare_dispatch(
            decision.decision_id,
            {"resource": "LAB", "amount": "1"},
            operation_scope=("fixture:LAB",),
            idempotency_key="durable-approval-consume",
            fencing_token=1,
            reconciliation_policy="idempotency_key",
            approval_request_id=request.request_id,
            approval_grant_id=issued.grant.grant_id,
            approval_token=issued.consumption_token,
        )
        persisted_request, persisted_grant = await reopened_store.approval(request.request_id)
    finally:
        await reopened_store.dispose()

    assert intent.approval_grant_id == issued.grant.grant_id
    assert persisted_request.status == "consumed"
    assert persisted_grant is not None
    assert persisted_grant.consumed_intent_id == intent.intent_id
