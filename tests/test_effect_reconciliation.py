from __future__ import annotations

from datetime import UTC, timedelta
from pathlib import Path

import pytest
from hypertrade.db import Database
from hypertrade.runtime.adapters.effect_store import (
    InMemoryEffectGovernanceStore,
    SqlEffectGovernanceStore,
)
from hypertrade.runtime.adapters.foundation import (
    FoundationExecutor,
    FoundationPlanner,
    ReadOnlyCapabilityPolicy,
)
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.application import effect_governance as module
from hypertrade.runtime.application.completion import MissionCompletionVerifier
from hypertrade.runtime.application.effect_governance import (
    EffectGovernanceService,
    PersistentCircuitOpen,
    public_effect_item,
)
from hypertrade.runtime.application.entrypoint import mission_request_for_prompt
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.domain.capabilities import CapabilityDefinitionV1, reviewed_snapshot
from hypertrade.runtime.domain.effects import EffectResolutionV1


def _snapshot():
    return reviewed_snapshot(
        CapabilityDefinitionV1(
            capability_id="isolated.timeout_fixture",
            title="Timeout fixture",
            description="An isolated unknown-effect fixture.",
            source_owner="hypertrade-tests",
            handler_key="isolated.timeout_fixture",
            scope="research_write",
            side_effect="idempotent_write",
            approval="none",
            idempotency="required",
        ),
        snapshot_id="timeout-fixture",
    )


class TimeoutThenReconcileAdapter:
    def __init__(self, outcome: str = "unknown") -> None:
        self.outcome = outcome
        self.dispatch_calls = 0
        self.reconcile_calls = 0

    async def dispatch(self, intent, arguments):
        self.dispatch_calls += 1
        raise TimeoutError("isolated transport timeout")

    async def reconcile(self, intent):
        self.reconcile_calls += 1
        return EffectResolutionV1.model_validate(
            {
                "outcome": self.outcome,
                "external_operation_id": (
                    f"fixture:{intent.idempotency_key}"
                    if self.outcome == "committed"
                    else ""
                ),
                "result": {"accepted": True} if self.outcome == "committed" else {},
                "reason": "isolated reconciliation lookup completed",
            }
        )


async def _unknown_call(*, reconciliation_policy="idempotency_key"):
    store = InMemoryEffectGovernanceStore()
    service = EffectGovernanceService(store)
    arguments = {"resource": "LAB", "value": 1}
    decision = await service.evaluate(
        _snapshot(),
        arguments,
        mission_id="mis_unknown",
        subject="operator-a",
        account="fixture-account",
        environment="isolated",
        role="research_operator",
        budget={},
        policy_snapshot={"revision": "effect-v1"},
    )
    intent, _ = await service.prepare_dispatch(
        decision.decision_id,
        arguments,
        operation_scope=("fixture:LAB",),
        idempotency_key=f"unknown-{reconciliation_policy}",
        fencing_token=1,
        reconciliation_policy=reconciliation_policy,
    )
    adapter = TimeoutThenReconcileAdapter()
    call = await service.execute(intent.intent_id, arguments, adapter)
    return store, service, adapter, intent, call


@pytest.mark.anyio
async def test_timeout_write_stays_unknown_until_reconciliation_and_blocks_completion() -> None:
    _, service, adapter, intent, call = await _unknown_call()
    assert call.status == "effect_unknown"
    assert adapter.dispatch_calls == 1

    mission_store = InMemoryMissionStore()
    runtime = MissionRuntime(
        mission_store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    mission = await runtime.create(
        mission_request_for_prompt(
            "研究 BTC 当前市场状态",
            actor="test",
            idempotency_key="completion-effect-unknown",
        )
    )
    mission = await runtime.run(mission.mission_id)
    plan = (await mission_store.plans(mission.mission_id))[-1]
    attempts = await mission_store.attempts(mission.mission_id)
    proof = MissionCompletionVerifier().verify(
        mission,
        plan,
        attempts,
        context_valid=True,
        tool_calls=(call,),
    )
    assert not proof.passed
    assert proof.effect_unknown
    assert any("unknown effect" in gap for gap in proof.gaps)

    unresolved, resolution = await service.reconcile(intent.intent_id, adapter)
    assert resolution.outcome == "unknown"
    assert unresolved.status == "effect_unknown"
    adapter.outcome = "committed"
    reconciled, resolution = await service.reconcile(intent.intent_id, adapter)
    assert resolution.outcome == "committed"
    assert reconciled.status == "reconciled"
    assert adapter.dispatch_calls == 1


@pytest.mark.anyio
async def test_unconsumed_approval_blocks_completion_proof() -> None:
    effect_store = InMemoryEffectGovernanceStore()
    service = EffectGovernanceService(effect_store)
    definition = _snapshot().definition.model_copy(update={"approval": "required"})
    decision = await service.evaluate(
        reviewed_snapshot(definition, snapshot_id="approval-completion-fixture"),
        {"resource": "LAB"},
        mission_id="mis_approval_gap",
        subject="operator-a",
        account="fixture-account",
        environment="isolated",
        role="research_operator",
        budget={},
        policy_snapshot={"revision": "effect-v1"},
    )
    approval = await service.request_approval(
        decision.decision_id,
        resource_scope=("fixture:LAB",),
        maximum_amount="1",
        requested_by="operator-a",
    )

    mission_store = InMemoryMissionStore()
    runtime = MissionRuntime(
        mission_store,
        FoundationPlanner(),
        FoundationExecutor(),
        ReadOnlyCapabilityPolicy(),
    )
    mission = await runtime.create(
        mission_request_for_prompt(
            "研究 ETH 当前市场状态",
            actor="test",
            idempotency_key="completion-approval-gap",
        )
    )
    mission = await runtime.run(mission.mission_id)
    plan = (await mission_store.plans(mission.mission_id))[-1]
    proof = MissionCompletionVerifier().verify(
        mission,
        plan,
        await mission_store.attempts(mission.mission_id),
        context_valid=True,
        approval_requests=(approval,),
    )

    assert not proof.passed
    assert any("approval requests remain unconsumed" in gap for gap in proof.gaps)


@pytest.mark.anyio
async def test_manual_only_adapter_remains_unknown_and_public_item_is_bounded() -> None:
    _, service, adapter, intent, call = await _unknown_call(
        reconciliation_policy="manual_only"
    )
    unresolved, resolution = await service.reconcile(intent.intent_id, adapter)
    item = public_effect_item(mission_id=intent.mission_id, call=unresolved)

    assert resolution.outcome == "unknown"
    assert unresolved.status == "effect_unknown"
    assert adapter.reconcile_calls == 0
    assert item.status == "effect_unknown"
    public = item.model_dump(mode="json")
    assert "account" not in public
    assert "arguments" not in public
    assert "secret" not in str(public).lower()
    assert call.tool_call_id == item.tool_call_id


@pytest.mark.anyio
async def test_persistent_circuit_is_shared_and_override_is_bounded(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'effect-circuit.db'}"
    Database(database_url).create_all()
    first_store = SqlEffectGovernanceStore(database_url)
    first = EffectGovernanceService(first_store)
    await first.circuit_failure("isolated.timeout_fixture")
    opened = await first.circuit_failure("isolated.timeout_fixture")
    await first_store.dispose()
    assert opened.state == "open"

    second_store = SqlEffectGovernanceStore(database_url)
    second = EffectGovernanceService(second_store)
    try:
        with pytest.raises(PersistentCircuitOpen):
            await second.circuit_preflight("isolated.timeout_fixture")
        assert opened.opened_at is not None
        clock = opened.opened_at.astimezone(UTC)
        monkeypatch.setattr(module, "_now", lambda: clock)
        override = await second.override_circuit(
            "isolated.timeout_fixture",
            actor="human-operator",
            reason="bounded diagnostic window",
            ttl_seconds=2,
        )
        assert override.override_actor == "human-operator"
        await second.circuit_preflight("isolated.timeout_fixture")
        monkeypatch.setattr(module, "_now", lambda: clock + timedelta(seconds=3))
        with pytest.raises(PersistentCircuitOpen):
            await second.circuit_preflight("isolated.timeout_fixture")
        events = await second_store.audit_events("isolated.timeout_fixture")
    finally:
        await second_store.dispose()

    assert events[-1].event_type == "circuit.overridden"
    assert events[-1].payload["reason"] == "bounded diagnostic window"
