from __future__ import annotations

import pytest
from hypertrade.research.paper_incubation import AutonomousPaperIncubationService
from hypertrade.research.paper_incubation_schemas import PaperResearchMandateV1
from paper_incubation_fixtures import mandate_request, seeded_paper_incubation


def test_mandate_intake_requires_validated_candidate_and_fixed_scope() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation()
    service = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    )
    request = mandate_request(refs, validation)
    created = service.create_mandate(request, actor="human-operator")
    replay = service.create_mandate(request, actor="human-operator")

    assert created["fixed_denominator"] == 1
    assert created["members"][0]["status"] == "eligible"
    assert created["mutation_boundary"] == {
        "paper_only": True,
        "testnet_writes": False,
        "live_writes": False,
        "real_order_writes": False,
        "capital_transfer_writes": False,
    }
    assert replay["id"] == created["id"]
    assert replay["replay"] == "idempotency"


def test_needs_review_validation_remains_rejected_from_paper_intake() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation(
        validation_status="needs_review"
    )
    created = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    ).create_mandate(mandate_request(refs, validation), actor="human-operator")

    assert created["members"][0]["status"] == "rejected"
    assert created["members"][0]["rejection_reasons"] == ["validation_status:needs_review"]


def test_validation_fingerprint_mismatch_is_rejected_from_intake() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation()
    created = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    ).create_mandate(
        mandate_request(
            refs,
            validation,
            key="paper-fingerprint-mismatch-001",
            updates={
                "validation_fingerprints": {
                    refs["candidate_id"]: "0" * 64,
                }
            },
        ),
        actor="human-operator",
    )

    assert created["members"][0]["status"] == "rejected"
    assert created["members"][0]["rejection_reasons"] == ["validation_fingerprint_mismatch"]


def test_agent_cannot_approve_or_expand_paper_mandate() -> None:
    db, refs, validation, _, _ = seeded_paper_incubation()
    with pytest.raises(ValueError, match="cannot approve"):
        mandate_request(
            refs,
            validation,
            updates={"approved_by": "agent:planner"},
        )
    with pytest.raises(ValueError, match="requires configure"):
        mandate_request(
            refs,
            validation,
            updates={"allowed_actions": ["start"]},
        )
    del db


def test_authenticated_creator_cannot_claim_another_human_approver() -> None:
    db, refs, validation, adapter, effects = seeded_paper_incubation()
    service = AutonomousPaperIncubationService(
        db, effect_governance=effects, bitpro_adapter=adapter
    )

    with pytest.raises(PermissionError, match="authenticated human approver"):
        service.create_mandate(
            mandate_request(refs, validation),
            actor="different-human",
        )


def test_schema_forbids_unknown_live_or_leverage_fields() -> None:
    with pytest.raises(ValueError):
        PaperResearchMandateV1.model_validate(
            {
                "name": "unsafe",
                "candidate_ids": ["candidate"],
                "validation_ids": ["validation"],
                "validation_fingerprints": {"candidate": "0" * 64},
                "symbols": ["BTC/USDT:USDT"],
                "paper_capital": 100,
                "max_instances": 1,
                "observation_days": [30],
                "allowed_actions": ["configure"],
                "maker_fee_bps": 2,
                "taker_fee_bps": 5,
                "slippage_bps": 5,
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2026-02-01T00:00:00Z",
                "approved_by": "human",
                "live_enabled": True,
                "leverage": 20,
            }
        )
