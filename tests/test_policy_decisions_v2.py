from __future__ import annotations

import pytest
from hypertrade.runtime.adapters.capability_catalog import builtin_capabilities
from hypertrade.runtime.adapters.effect_store import InMemoryEffectGovernanceStore
from hypertrade.runtime.application.effect_governance import EffectGovernanceService
from hypertrade.runtime.domain.capabilities import CapabilityDefinitionV1, reviewed_snapshot


def _snapshot(*, version: str = "1", approval: str = "required"):
    return reviewed_snapshot(
        CapabilityDefinitionV1.model_validate(
            {
                "capability_id": "isolated.write_fixture",
                "version": version,
                "title": "Isolated write fixture",
                "description": "No-money adapter used only for governance tests.",
                "source_owner": "hypertrade-tests",
                "handler_key": "isolated.write_fixture",
                "scope": "research_write",
                "side_effect": "idempotent_write",
                "approval": approval,
                "idempotency": "required",
            }
        ),
        snapshot_id=f"fixture-{version}-{approval}",
    )


async def _decision(service, snapshot, arguments, *, account="acct-a", environment="isolated"):
    return await service.evaluate(
        snapshot,
        arguments,
        mission_id="mis_policy",
        subject="operator-a",
        account=account,
        environment=environment,
        role="research_operator",
        budget={"maximum_amount": "10"},
        policy_snapshot={"revision": "policy-a"},
    )


@pytest.mark.anyio
async def test_policy_decision_binds_exact_args_hashes_and_capability_version() -> None:
    service = EffectGovernanceService(InMemoryEffectGovernanceStore())
    first = await _decision(service, _snapshot(version="1"), {"symbol": "LAB", "size": 1})
    changed_args = await _decision(
        service, _snapshot(version="1"), {"symbol": "LAB", "size": 2}
    )
    changed_version = await _decision(
        service, _snapshot(version="2"), {"symbol": "LAB", "size": 1}
    )

    assert first.decision == "ask"
    assert first.arguments_hash != changed_args.arguments_hash
    assert first.contract_hash != changed_version.contract_hash
    assert first.capability_version != changed_version.capability_version


@pytest.mark.anyio
async def test_deny_cannot_be_overridden_and_production_write_is_disabled() -> None:
    service = EffectGovernanceService(InMemoryEffectGovernanceStore())
    blocked = await _decision(
        service,
        _snapshot(approval="blocked"),
        {"symbol": "LAB", "size": 1},
    )
    production = await _decision(
        service,
        _snapshot(),
        {"symbol": "LAB", "size": 1},
        environment="production",
    )

    assert blocked.decision == "deny"
    assert production.decision == "deny"
    with pytest.raises(PermissionError, match="ask decision"):
        await service.request_approval(
            blocked.decision_id,
            resource_scope=("fixture:LAB",),
            maximum_amount="1",
            requested_by="operator-a",
        )


@pytest.mark.anyio
async def test_approved_arguments_cannot_be_changed_before_dispatch() -> None:
    service = EffectGovernanceService(InMemoryEffectGovernanceStore())
    decision = await _decision(service, _snapshot(), {"symbol": "LAB", "size": 1})
    request = await service.request_approval(
        decision.decision_id,
        resource_scope=("fixture:LAB",),
        maximum_amount="1",
        requested_by="operator-a",
    )
    issued = await service.grant_approval(
        request.request_id, actor="human-reviewer", reason="bounded isolated fixture"
    )

    with pytest.raises(PermissionError, match="arguments changed"):
        await service.prepare_dispatch(
            decision.decision_id,
            {"symbol": "LAB", "size": 2},
            operation_scope=("fixture:LAB",),
            idempotency_key="policy-changed-args",
            fencing_token=1,
            reconciliation_policy="idempotency_key",
            approval_request_id=request.request_id,
            approval_grant_id=issued.grant.grant_id,
            approval_token=issued.consumption_token,
        )


def test_production_builtin_catalog_physically_contains_no_write_capability() -> None:
    definitions = builtin_capabilities()

    assert definitions
    assert all(row.side_effect == "none" for row in definitions)
    assert all(row.scope in {"read", "live_read"} for row in definitions)
