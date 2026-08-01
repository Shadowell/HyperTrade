from __future__ import annotations

import io
from decimal import Decimal

from fastapi.testclient import TestClient
from hypertrade.cli import handle_regime_shadow_command
from hypertrade.config import Settings
from hypertrade.db import (
    Database,
    LiveOrderIntent,
    PaperOrder,
    PaperPromotion,
    RegimeShadowTargetV2,
)
from hypertrade.main import create_app
from hypertrade.portfolio.regime_shadow import RegimeShadowAllocatorServiceV2
from regime_shadow_support import (
    build_request,
    capture_regime,
    policy,
    seed_sources,
)
from sqlalchemy import func, select


def test_four_fixed_templates_are_bounded_and_never_authorize_execution() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id, regime_id = seed_sources(db, suffix="templates")

    target = RegimeShadowAllocatorServiceV2(db).build(
        build_request(cohort_id, regime_id), actor="test"
    )

    assert target["status"] == "ready"
    assert len(target["allocations"]) == 4
    assert all(item["status"] == "feasible" for item in target["allocations"])
    for allocation in target["allocations"]:
        weights = [Decimal(item["weight"]) for item in allocation["target_weights"]]
        assert sum(weights) == Decimal("1.000000000000")
        assert max(weights) <= Decimal("0.70")
        assert allocation["execution_authorized"] is False
    assert target["exchange_order_payload"] is None
    assert target["execution_authorized"] is False
    assert target["capital_authorized"] is False
    assert target["paper_lifecycle_authorized"] is False
    assert target["live_authorized"] is False
    with db.session() as session:
        assert session.scalar(select(func.count(PaperPromotion.id))) == 0
        assert session.scalar(select(func.count(PaperOrder.id))) == 0
        assert session.scalar(select(func.count(LiveOrderIntent.id))) == 0


def test_missing_correlation_and_infeasible_caps_fail_closed() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id, regime_id = seed_sources(db, suffix="missing-correlation", correlation=None)
    service = RegimeShadowAllocatorServiceV2(db)

    missing = service.build(
        build_request(cohort_id, regime_id, key="missing-correlation-build"),
        actor="test",
    )
    assert missing["status"] == "infeasible"
    assert any(reason.startswith("correlation_missing:") for reason in missing["unknowns"])

    capped = service.build(
        build_request(
            cohort_id,
            regime_id,
            key="infeasible-cap-build",
            allocation_policy=policy(
                min_members=3,
                max_members=3,
                max_strategy_weight=Decimal("0.40"),
            ),
        ),
        actor="test",
    )
    assert capped["status"] == "infeasible"
    assert "member_or_capacity_caps_infeasible" in capped["unknowns"]


def test_content_bound_idempotency_and_immutable_versions() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id, regime_id = seed_sources(db, suffix="idempotency")
    service = RegimeShadowAllocatorServiceV2(db)
    request = build_request(cohort_id, regime_id, key="target-idempotency-one")

    first = service.build(request, actor="test")
    replay = service.build(request, actor="test")
    duplicate = service.build(
        request.model_copy(update={"idempotency_key": "target-idempotency-two"}),
        actor="test",
    )

    assert replay["id"] == first["id"]
    assert replay["replay"] == "idempotency"
    assert duplicate["id"] == first["id"]
    assert duplicate["replay"] == "content"
    with db.session() as session:
        assert session.scalar(select(func.count(RegimeShadowTargetV2.id))) == 1


def test_cost_cap_suppresses_target() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id, regime_id = seed_sources(
        db,
        suffix="churn",
        cost_bps=("200", "200"),
        fits=(["trend"], ["range"]),
    )
    service = RegimeShadowAllocatorServiceV2(db)
    costly = service.build(
        build_request(
            cohort_id,
            regime_id,
            key="cost-cap-build",
            allocation_policy=policy(
                templates=["constrained_risk_adjusted"],
                max_estimated_cost_bps=Decimal("10"),
            ),
        ),
        actor="test",
    )
    assert costly["status"] == "infeasible"
    assert "estimated_cost_cap_exceeded" in costly["unknowns"]


def test_max_delta_and_dwell_prevent_regime_flip_churn() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id, first_regime_id = seed_sources(
        db,
        suffix="delta",
        fits=(["trend"], ["range"]),
    )
    service = RegimeShadowAllocatorServiceV2(db)
    first = service.build(
        build_request(
            cohort_id,
            first_regime_id,
            key="delta-first-target",
            allocation_policy=policy(
                templates=["constrained_risk_adjusted"],
                entry_threshold=Decimal("0.05"),
                exit_threshold=Decimal("0.01"),
            ),
        ),
        actor="test",
    )
    shifted_regime = capture_regime(
        db,
        suffix="delta-shift",
        trend="0.1",
        range_score="0.8",
    )
    second = service.build(
        build_request(
            cohort_id,
            shifted_regime["id"],
            key="delta-second-target",
            previous_target_id=first["id"],
            allocation_policy=policy(
                templates=["constrained_risk_adjusted"],
                max_weight_delta=Decimal("0.05"),
                entry_threshold=Decimal("0.05"),
                exit_threshold=Decimal("0.01"),
            ),
        ),
        actor="test",
    )

    assert {item["status"] for item in second["eligibility"]} == {"eligible"}
    assert second["status"] == "infeasible"
    assert "max_weight_delta_exceeded" in second["unknowns"]
    assert second["target_weights"] == []


def test_authenticated_api_and_cli_render_read_only_target() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id, regime_id = seed_sources(db, suffix="api")
    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                SESSION_SECRET="regime-shadow-api-test",
            ),
            db=db,
        )
    )
    assert client.get("/api/portfolio/regime-shadow-targets-v2").status_code == 401
    client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    response = client.post(
        "/api/portfolio/regime-shadow-targets-v2",
        json=build_request(cohort_id, regime_id, key="regime-shadow-api-build").model_dump(
            mode="json"
        ),
    )
    assert response.status_code == 200
    target = response.json()
    assert target["execution_authorized"] is False
    replay = client.get(f"/api/portfolio/regime-shadow-targets-v2/{target['id']}/replay")
    assert replay.json()["no_lookahead_verified"] is True

    class FakeClient:
        def list_regime_shadow_targets(self) -> list[dict[str, object]]:
            return [target]

    output = io.StringIO()
    handle_regime_shadow_command(
        "/regime-shadow list",
        client=FakeClient(),  # type: ignore[arg-type]
        output=output,
    )
    assert "hypothetical=true execution=false" in output.getvalue()
