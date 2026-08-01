from __future__ import annotations

from hypertrade.db import Database, StrategyCardSnapshot
from hypertrade.portfolio.regime_shadow import RegimeShadowAllocatorServiceV2
from regime_shadow_support import build_request, policy, seed_sources


def test_eligibility_precedes_weights_and_keeps_fixed_denominator() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id, regime_id = seed_sources(db, suffix="eligibility", capacities=("80000", "unknown"))

    target = RegimeShadowAllocatorServiceV2(db).build(
        build_request(cohort_id, regime_id), actor="test"
    )

    assert target["intake_denominator"] == 2
    assert target["eligible_count"] == 1
    assert target["status"] == "infeasible"
    excluded = target["eligibility"][1]
    assert excluded["status"] == "unknown"
    assert "capacity_unknown" in excluded["reasons"]
    assert target["target_weights"] == []


def test_entry_confirmation_dwell_and_risk_pause_are_explicit() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id, regime_id = seed_sources(db, suffix="hysteresis")
    service = RegimeShadowAllocatorServiceV2(db)
    confirming = service.build(
        build_request(
            cohort_id,
            regime_id,
            key="hysteresis-confirm-one",
            allocation_policy=policy(confirmation_windows=2),
        ),
        actor="test",
    )
    assert {item["status"] for item in confirming["eligibility"]} == {"observe"}
    assert all(
        "entry_confirmation_pending" in item["reasons"] for item in confirming["eligibility"]
    )

    with db.session() as session:
        card = session.get(StrategyCardSnapshot, "scsnap-hysteresis-0")
        assert card is not None
        card.card_json = {**card.card_json, "paper_status": "paper_degraded"}
    paused = service.build(
        build_request(
            cohort_id,
            regime_id,
            key="hysteresis-risk-pause",
            allocation_policy=policy(),
        ),
        actor="test",
    )
    first = next(item for item in paused["eligibility"] if item["card_id"].endswith("-a"))
    assert first["status"] == "pause"
    assert "strategy_risk_state" in first["reasons"]
    assert first["cooldown_until"]
