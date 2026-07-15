from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from hypertrade.cli import handle_shadow_portfolio_command
from hypertrade.config import Settings
from hypertrade.db import (
    Database,
    LiveOrderIntent,
    PaperCohortLabelDecision,
    PaperCohortSnapshot,
    PaperOrder,
    PaperPromotion,
    PaperReviewRequest,
    ShadowPortfolioProposal,
    ShadowPortfolioReviewDecision,
    StrategyCardSnapshot,
)
from hypertrade.main import create_app
from hypertrade.portfolio.shadow import ShadowPortfolioService
from hypertrade.portfolio.shadow_schemas import (
    ShadowPortfolioBuildV1,
    ShadowPortfolioReviewV1,
)
from sqlalchemy import func, select

NOW = datetime(2026, 7, 15, 8, tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _cohort(
    db: Database,
    *,
    volatilities: tuple[str, str] = ("0.02", "0.04"),
    capacities: tuple[str, str] = ("100000", "50000"),
    liquidities: tuple[str, str] = ("passed", "liquid"),
    decisions: tuple[str, str] = ("accept", "accept"),
    comparison_keys: tuple[str, str] = ("same-group", "same-group"),
    valid_until: datetime | None = None,
    suffix: str = "base",
) -> str:
    expiry = valid_until or NOW + timedelta(days=7)
    card_ids = (f"card-{suffix}-a", f"card-{suffix}-b")
    snapshots: list[StrategyCardSnapshot] = []
    members: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    for index, card_id in enumerate(card_ids):
        snapshot = StrategyCardSnapshot(
            id=f"scsnap-{suffix}-{index}",
            card_id=card_id,
            lineage_id=f"lineage-{suffix}-{index}",
            version_id=f"version-{suffix}-{index}",
            schema_version="strategy_card.v2",
            lifecycle_status="paper_observing",
            completeness_score=Decimal("1"),
            content_hash=_hash(f"card-{suffix}-{index}"),
            card_json={
                "schema_version": "strategy_card.v2",
                "capacity": capacities[index],
                "liquidity": liquidities[index],
            },
            created_by="test",
        )
        snapshots.append(snapshot)
        members.append(
            {
                "card_id": card_id,
                "strategy_version_id": snapshot.version_id,
                "comparison_key": comparison_keys[index],
                "comparable": True,
                "reasons": [],
                "metrics": {"volatility_proxy": volatilities[index]},
                "source_refs": {"card_snapshot_id": snapshot.id},
            }
        )
        proposals.append(
            {
                "proposal_id": f"label-{suffix}-{index}",
                "card_id": card_id,
                "proposed_label": "champion_candidate" if index == 0 else "challenger",
                "valid_until": expiry.isoformat(),
            }
        )
    cohort = PaperCohortSnapshot(
        id=f"pcoh-{suffix}",
        cohort_key=_hash(f"cohort-key-{suffix}"),
        version_number=1,
        schema_version="paper_cohort.v1",
        policy_version="paper_cohort_policy.v1",
        policy_hash=_hash("paper-policy"),
        status="review_ready",
        observation_window_id=f"pwin-{suffix}",
        intake_count=2,
        comparable_count=2,
        proposal_count=2,
        request_hash=_hash(f"request-{suffix}"),
        source_hash=_hash(f"source-{suffix}"),
        content_hash=_hash(f"content-{suffix}"),
        idempotency_key=f"cohort-idempotency-{suffix}",
        snapshot_json={"members": members, "groups": [{"label_proposals": proposals}]},
        created_by="test",
    )
    with db.session() as session:
        session.add_all([*snapshots, cohort])
        session.flush()
        for index, proposal in enumerate(proposals):
            session.add(
                PaperCohortLabelDecision(
                    cohort_snapshot_id=cohort.id,
                    proposal_id=proposal["proposal_id"],
                    strategy_card_id=card_ids[index],
                    proposed_label=proposal["proposed_label"],
                    decision=decisions[index],
                    reason="Human paper label review",
                    request_hash=_hash(f"decision-request-{suffix}-{index}"),
                    idempotency_key=f"label-decision-{suffix}-{index}",
                    valid_until=expiry,
                    decided_by="admin",
                )
            )
    return cohort.id


def _build(
    cohort_id: str,
    idempotency_key: str = "shadow-build-001",
    **updates: Any,
) -> ShadowPortfolioBuildV1:
    return ShadowPortfolioBuildV1(
        cohort_snapshot_id=cohort_id,
        idempotency_key=idempotency_key,
        **updates,
    )


def test_complete_evidence_builds_three_bounded_hypothetical_templates() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id = _cohort(db)

    proposal = ShadowPortfolioService(db).build(
        _build(cohort_id), actor="test", now=NOW
    )

    assert proposal["status"] == "ready_for_review"
    assert proposal["intake_count"] == proposal["eligible_count"] == 2
    assert [item["template"] for item in proposal["scenarios"]] == [
        "equal_weight",
        "inverse_volatility",
        "capped_risk_budget_proxy",
    ]
    for scenario in proposal["scenarios"]:
        weights = [Decimal(item["weight"]) for item in scenario["weights"]]
        assert sum(weights) == Decimal("1")
        assert max(weights) <= Decimal("0.60")
        assert scenario["hypothetical"] is True
        assert scenario["execution_authorized"] is False
        assert scenario["capital_authorized"] is False
        assert len(scenario["stress_tests"]) == 3
        for impact in scenario["hypothetical_order_impacts"]:
            assert impact["hypothetical"] is True
            assert impact["order_created"] is False
            assert not set(impact) & {"exchange", "account", "order_type", "client_order_id"}
    assert proposal["automatic_recommendation"] is None
    assert proposal["orders_created"] is False


@pytest.mark.parametrize(
    ("volatilities", "capacities", "liquidities", "templates"),
    [
        (("unknown", "0.04"), ("100000", "50000"), ("passed", "liquid"), ["equal_weight"]),
        (
            ("0.02", "0.04"),
            ("unknown", "50000"),
            ("passed", "unknown"),
            ["equal_weight", "inverse_volatility"],
        ),
    ],
)
def test_incomplete_inputs_suppress_dependent_templates(
    volatilities: tuple[str, str],
    capacities: tuple[str, str],
    liquidities: tuple[str, str],
    templates: list[str],
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id = _cohort(
        db,
        volatilities=volatilities,
        capacities=capacities,
        liquidities=liquidities,
        suffix="incomplete",
    )

    proposal = ShadowPortfolioService(db).build(
        _build(cohort_id, "shadow-build-incomplete"), actor="test", now=NOW
    )

    assert [item["template"] for item in proposal["scenarios"]] == templates


def test_fixed_denominator_and_infeasible_cap_fail_closed() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id = _cohort(
        db,
        decisions=("accept", "hold"),
        suffix="denominator",
    )
    service = ShadowPortfolioService(db)

    excluded = service.build(
        _build(cohort_id, "shadow-build-denominator"), actor="test", now=NOW
    )
    assert excluded["intake_count"] == 2
    assert excluded["eligible_count"] == 1
    assert excluded["scenario_count"] == 0
    assert excluded["status"] == "needs_data"
    assert excluded["members"][1]["status"] == "excluded"
    assert "label_decision_hold" in excluded["members"][1]["reasons"]

    complete_id = _cohort(db, suffix="cap")
    infeasible = service.build(
        _build(
            complete_id,
            "shadow-build-cap",
            max_strategy_weight=Decimal("0.40"),
        ),
        actor="test",
        now=NOW,
    )
    assert infeasible["scenario_count"] == 0
    assert "max_weight_constraint_infeasible" in infeasible["unknowns"]


def test_accepted_members_from_different_comparison_groups_are_not_mixed() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id = _cohort(
        db,
        comparison_keys=("btc-1h-cost-a", "btc-1h-cost-b"),
        suffix="cross-group",
    )

    proposal = ShadowPortfolioService(db).build(
        _build(cohort_id, "shadow-build-cross-group"), actor="test", now=NOW
    )

    assert proposal["eligible_count"] == 2
    assert proposal["scenario_count"] == 0
    assert "accepted_members_not_in_one_comparison_group" in proposal["unknowns"]


def test_build_is_idempotent_and_source_changes_append_version() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id = _cohort(db, suffix="version")
    service = ShadowPortfolioService(db)
    first = service.build(
        _build(cohort_id, "shadow-build-version-one"), actor="test", now=NOW
    )
    replay = service.build(
        _build(cohort_id, "shadow-build-version-one"), actor="test", now=NOW
    )
    duplicate = service.build(
        _build(cohort_id, "shadow-build-version-duplicate"), actor="test", now=NOW
    )
    second = service.build(
        _build(
            cohort_id,
            "shadow-build-version-two",
            fee_bps=Decimal("20"),
        ),
        actor="test",
        now=NOW + timedelta(hours=1),
    )

    assert replay["id"] == first["id"]
    assert replay["idempotent"] is True
    assert duplicate["id"] == first["id"]
    assert duplicate["idempotent_content"] is True
    assert first["version_number"] == 1
    assert second["version_number"] == 2
    assert first["content_hash"] != second["content_hash"]
    with db.session() as session:
        assert session.scalar(select(func.count(ShadowPortfolioProposal.id))) == 2


def test_review_is_expiring_idempotent_audit_without_trading_side_effects() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id = _cohort(db, suffix="review")
    service = ShadowPortfolioService(db)
    proposal = service.build(
        _build(cohort_id, "shadow-build-review"), actor="test", now=NOW
    )
    scenario_id = proposal["scenarios"][0]["scenario_id"]
    payload = ShadowPortfolioReviewV1(
        scenario_id=scenario_id,
        decision="accept",
        reason="Continue research on this hypothetical scenario",
        idempotency_key="shadow-review-001",
    )

    first = service.review(proposal["id"], payload, actor="admin", now=NOW)
    replay = service.review(proposal["id"], payload, actor="admin", now=NOW)

    assert replay["id"] == first["id"]
    assert first["execution_authorized"] is False
    assert first["capital_authorized"] is False
    assert first["orders_created"] is False
    with db.session() as session:
        assert session.scalar(select(func.count(ShadowPortfolioReviewDecision.id))) == 1
        assert session.scalar(select(func.count(PaperPromotion.id))) == 0
        assert session.scalar(select(func.count(PaperReviewRequest.id))) == 0
        assert session.scalar(select(func.count(PaperOrder.id))) == 0
        assert session.scalar(select(func.count(LiveOrderIntent.id))) == 0
    with pytest.raises(ValueError, match="expired"):
        service.review(
            proposal["id"],
            payload.model_copy(update={"idempotency_key": "shadow-review-expired"}),
            actor="admin",
            now=NOW + timedelta(days=8),
        )


def test_shadow_api_requires_admin_and_cli_renders_governance_boundary() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id = _cohort(db, suffix="api")
    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                SESSION_SECRET="shadow-api-test",
            ),
            db=db,
        )
    )
    assert client.get("/api/portfolio/shadow-portfolios").status_code == 401
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    created = client.post(
        "/api/portfolio/shadow-portfolios",
        json={"cohort_snapshot_id": cohort_id, "idempotency_key": "shadow-api-build-001"},
    )
    assert created.status_code == 200
    proposal = created.json()
    reviewed = client.post(
        f"/api/portfolio/shadow-portfolios/{proposal['id']}/reviews",
        json={
            "scenario_id": proposal["scenarios"][0]["scenario_id"],
            "decision": "hold",
            "reason": "Need more hypothetical evidence",
            "idempotency_key": "shadow-api-review-001",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["capital_authorized"] is False

    class Client:
        def list_shadow_portfolios(self) -> list[dict[str, Any]]:
            return [proposal]

    output = io.StringIO()
    handle_shadow_portfolio_command(
        "/shadow list", client=cast(Any, Client()), output=output
    )
    rendered = output.getvalue()
    assert "hypothetical only" in rendered
    assert "execution=false" in rendered


def test_shadow_module_has_no_data_or_execution_adapter_imports() -> None:
    source = (
        Path(__file__).parents[1]
        / "backend"
        / "src"
        / "hypertrade"
        / "portfolio"
        / "shadow.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "from hypertrade.bitpro",
        "from hypertrade.paper",
        "from hypertrade.live",
        "from hypertrade.risk",
        "PaperTradingService",
        "LiveOrderIntentService",
        "BitProToolAdapter",
    ):
        assert forbidden not in source
