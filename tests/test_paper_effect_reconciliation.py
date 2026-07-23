from __future__ import annotations

import pytest
from hypertrade.research.paper_incubation import AutonomousPaperIncubationService
from hypertrade.research.paper_incubation_schemas import PaperIncubationActionV1
from paper_incubation_fixtures import mandate_request, seeded_paper_incubation


@pytest.mark.anyio
async def test_timeout_stays_effect_unknown_until_read_state_reconciliation() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation()
    adapter.timeout_action = "configure"
    service = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    )
    mandate = service.create_mandate(mandate_request(refs, validation), actor="human-operator")
    member_id = mandate["members"][0]["id"]
    unknown = await service.act(
        PaperIncubationActionV1(
            member_id=member_id,
            action="configure",
            reason="Configure with injected transport timeout",
            idempotency_key="paper-timeout-configure-001",
        ),
        actor="paper-controller",
    )
    assert unknown["status"] == "effect_unknown"
    assert service.get_member(member_id)["status"] == "effect_unknown"

    adapter.status = "configured"
    reconciled = await service.reconcile(unknown["id"], actor="paper-reconciler")

    assert reconciled["status"] == "reconciled"
    assert reconciled["after"]["reconciliation"]["outcome"] == "committed"
    assert service.get_member(member_id)["status"] == "configured"
    assert adapter.calls.count("configure") == 1


def test_controller_has_no_testnet_live_or_order_adapter_surface() -> None:
    import inspect

    import hypertrade.research.paper_incubation as module

    source = inspect.getsource(module.PaperIncubationAdapter)
    assert "testnet_" not in source
    assert "live_" not in source
    assert "order_" not in source
