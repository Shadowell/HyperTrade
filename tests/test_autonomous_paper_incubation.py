from __future__ import annotations

import pytest
from hypertrade.db import PaperIncubationAction
from hypertrade.research.paper_incubation import AutonomousPaperIncubationService
from hypertrade.research.paper_incubation_schemas import (
    PaperIncubationActionV1,
    PaperIncubationCaptureV1,
)
from paper_incubation_fixtures import mandate_request, seeded_paper_incubation
from sqlalchemy import func, select


@pytest.mark.anyio
async def test_configure_start_observe_pause_are_mandate_bound_and_idempotent() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation()
    service = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    )
    mandate = service.create_mandate(mandate_request(refs, validation), actor="human-operator")
    member_id = mandate["members"][0]["id"]
    configured_request = PaperIncubationActionV1(
        member_id=member_id,
        action="configure",
        reason="Validated candidate enters bounded Paper",
        idempotency_key="paper-incubation-configure-001",
    )
    configured = await service.act(configured_request, actor="paper-controller")
    replay = await service.act(configured_request, actor="paper-controller")
    started = await service.act(
        PaperIncubationActionV1(
            member_id=member_id,
            action="start",
            reason="Begin approved observation window",
            idempotency_key="paper-incubation-start-001",
        ),
        actor="paper-controller",
    )
    observed = service.observe(member_id, actor="paper-controller")
    paused = await service.act(
        PaperIncubationActionV1(
            member_id=member_id,
            action="pause",
            reason="Bounded operator pause",
            idempotency_key="paper-incubation-pause-001",
        ),
        actor="paper-controller",
    )

    assert configured["status"] == replay["status"] == "succeeded"
    assert replay["replay"] == "idempotency"
    assert configured["outcome_link"].startswith("dispatch_intent:")
    assert configured["after"]["member"]["status"] == "configured"
    assert started["status"] == "succeeded"
    assert observed["status"] == "observing"
    assert paused["status"] == "succeeded"
    assert service.get_member(member_id)["status"] == "paused"
    assert adapter.calls.count("configure") == adapter.calls.count("start") == 1
    with db.session() as session:
        assert session.scalar(select(func.count(PaperIncubationAction.id))) == 3


@pytest.mark.anyio
async def test_action_idempotency_key_cannot_be_rebound() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation()
    service = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    )
    mandate = service.create_mandate(mandate_request(refs, validation), actor="human-operator")
    member_id = mandate["members"][0]["id"]
    await service.act(
        PaperIncubationActionV1(
            member_id=member_id,
            action="configure",
            reason="Original content-bound action",
            idempotency_key="paper-content-bound-action-001",
        ),
        actor="paper-controller",
    )

    with pytest.raises(ValueError, match="content-bound"):
        await service.act(
            PaperIncubationActionV1(
                member_id=member_id,
                action="configure",
                reason="Changed action payload",
                idempotency_key="paper-content-bound-action-001",
            ),
            actor="paper-controller",
        )


@pytest.mark.anyio
async def test_kill_switch_blocks_new_actions_and_keeps_history() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation()
    service = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    )
    mandate = service.create_mandate(mandate_request(refs, validation), actor="human-operator")
    member_id = mandate["members"][0]["id"]
    revoked = service.set_mandate_state(
        mandate["id"],
        status="revoked",
        actor="human-operator",
        reason="Research mandate completed",
    )
    with pytest.raises(PermissionError, match="kill switch"):
        await service.act(
            PaperIncubationActionV1(
                member_id=member_id,
                action="configure",
                reason="must not run",
                idempotency_key="paper-after-revoke-001",
            ),
            actor="paper-controller",
        )

    assert revoked["kill_switch"] is True
    assert revoked["members"][0]["status"] == "eligible"
    assert adapter.calls == []


@pytest.mark.anyio
async def test_revoked_safe_pause_mandate_can_only_contain_running_instance() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation()
    service = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    )
    mandate = service.create_mandate(mandate_request(refs, validation), actor="human-operator")
    member_id = mandate["members"][0]["id"]
    for action in ("configure", "start"):
        await service.act(
            PaperIncubationActionV1(
                member_id=member_id,
                action=action,
                reason=f"Prepare {action} before revocation",
                idempotency_key=f"paper-safe-pause-{action}-001",
            ),
            actor="paper-controller",
        )
    service.set_mandate_state(
        mandate["id"],
        status="revoked",
        actor="human-operator",
        reason="Contain the running Paper instance",
    )

    paused = await service.act(
        PaperIncubationActionV1(
            member_id=member_id,
            action="pause",
            reason="Safe containment after revocation",
            idempotency_key="paper-safe-pause-action-001",
        ),
        actor="paper-controller",
    )

    assert paused["status"] == "succeeded"
    assert service.get_member(member_id)["status"] == "paused"
    assert adapter.calls == ["configure", "start", "pause"]


@pytest.mark.anyio
async def test_risk_alert_automatically_dispatches_governed_pause() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation()
    service = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    )
    mandate = service.create_mandate(mandate_request(refs, validation), actor="human-operator")
    member_id = mandate["members"][0]["id"]
    for action in ("configure", "start"):
        await service.act(
            PaperIncubationActionV1(
                member_id=member_id,
                action=action,
                reason=f"Prepare {action} before risk observation",
                idempotency_key=f"paper-auto-risk-{action}-001",
            ),
            actor="paper-controller",
        )
    adapter.max_drawdown_pct = "20"

    observed = await service.act(
        PaperIncubationActionV1(
            member_id=member_id,
            action="observe",
            reason="Evaluate automatic Paper safety thresholds",
            idempotency_key="paper-auto-risk-observe-001",
        ),
        actor="paper-controller",
    )

    assert observed["observation"]["alerts"] == ["max_drawdown_exceeded"]
    assert observed["automatic_action"]["status"] == "succeeded"
    assert service.get_member(member_id)["status"] == "paused"
    assert adapter.calls[-3:] == ["snapshot", "health", "pause"]


@pytest.mark.anyio
async def test_fixed_mandate_captures_immutable_30_60_90_windows_without_champion() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation()
    service = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    )
    mandate = service.create_mandate(mandate_request(refs, validation), actor="human-operator")
    member_id = mandate["members"][0]["id"]
    for action in ("configure", "start"):
        await service.act(
            PaperIncubationActionV1(
                member_id=member_id,
                action=action,
                reason=f"Prepare {action} before cohort capture",
                idempotency_key=f"paper-window-{action}-001",
            ),
            actor="paper-controller",
        )

    captured = service.capture_windows(
        PaperIncubationCaptureV1(
            mandate_id=mandate["id"],
            idempotency_key="paper-window-capture-001",
        ),
        actor="paper-controller",
    )

    assert [item["horizon_days"] for item in captured["windows"]] == [30, 60, 90]
    assert len(captured["cohorts"]) == 3
    assert {item["status"] for item in captured["cohorts"]} == {"needs_data"}
    assert captured["cohorts"][0]["members"][0]["paper_status"] == "paper_observing"
    assert "paper_status_not_observing" not in captured["cohorts"][0]["members"][0]["reasons"]
    assert captured["fixed_denominator"] == 1
    assert captured["champion_authorized"] is False
    assert captured["live_authorized"] is False
