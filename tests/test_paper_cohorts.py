from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypertrade.cli import handle_slash_command
from hypertrade.config import Settings
from hypertrade.db import (
    Database,
    PaperCohortLabelDecision,
    PaperCohortSnapshot,
    PaperPromotion,
    PaperReviewRequest,
    PortfolioObservationWindow,
)
from hypertrade.main import create_app
from hypertrade.portfolio.cohort_schemas import (
    PaperCohortBuildV1,
    PaperCohortLabelDecisionV1,
)
from hypertrade.portfolio.cohorts import PaperCohortService
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.experiment_schemas import ExperimentRegister
from hypertrade.research.strategy_cards import StrategyCardService
from sqlalchemy import func, select
from test_experiment_manifest import manifest

NOW = datetime(2026, 7, 15, 4, 0, tzinfo=UTC)


def _manifest(db: Database, key: str, *, fee: str = "10") -> dict[str, Any]:
    source = manifest(fee=fee)
    source.strategy_spec = source.strategy_spec.model_copy(
        update={"strategy_key": key, "title": key}
    )
    return ExperimentLedgerService(db).register(
        ExperimentRegister(
            manifest=source,
            idempotency_key=f"cohort-manifest-{key}-{fee}",
        ),
        actor="test",
    )["manifest"]


def _card(card_id: str, manifest_row: dict[str, Any], *, paper: str = "paper_observing") -> dict:
    return {
        "schema_version": "strategy_card.v2",
        "card_id": card_id,
        "snapshot_id": f"snapshot_{card_id}",
        "strategy_key": f"strategy_{card_id}",
        "paper_status": paper,
        "validation_status": "passed",
        "declared_regime_fit": ["risk_on", "mixed"],
        "version": {
            "id": f"version_{card_id}",
            "manifest_fingerprint": manifest_row["fingerprint"],
        },
        "source_refs": {"manifest_id": manifest_row["id"]},
    }


def _window(
    db: Database,
    cards: list[dict],
    metrics: dict[str, tuple[str, str, str]],
    *,
    suffix: str = "one",
    status: str = "available",
    freshness: str = "fresh",
    sample_count: int = 30,
) -> str:
    with db.session() as session:
        row = PortfolioObservationWindow(
            schema_version="portfolio_observation_window.v1",
            policy_version="portfolio_evidence_policy.v1",
            status=status,
            horizon_days=30,
            bucket_minutes=1440,
            window_start=NOW - timedelta(days=30),
            window_end=NOW,
            request_hash=f"request-{suffix}",
            source_hash=f"source-{suffix}",
            content_hash=f"content-{suffix}",
            idempotency_key=f"window-{suffix}",
            source_refs_json={},
            quality_json={"status": status, "coverage_ratio": "1.00000000"},
            strategy_summaries_json=[
                {
                    "card_id": card["card_id"],
                    "status": status,
                    "sample_count": sample_count,
                    "sample_start": (NOW - timedelta(days=30)).isoformat(),
                    "sample_end": NOW.isoformat(),
                    "freshness": freshness,
                    "metrics": {
                        "total_return_pct": metrics[card["card_id"]][0],
                        "max_drawdown_pct": metrics[card["card_id"]][1],
                        "volatility_proxy": metrics[card["card_id"]][2],
                    },
                    "source_refs": {"curve_content_hash": f"curve-{suffix}-{card['card_id']}"},
                }
                for card in cards
            ],
            pairwise_json=[],
            created_by="test",
        )
        session.add(row)
        session.flush()
        return row.id


def _build(window_id: str, key: str = "paper-cohort-build-001") -> PaperCohortBuildV1:
    return PaperCohortBuildV1(
        observation_window_id=window_id,
        min_sample_count=20,
        idempotency_key=key,
    )


def test_multidimensional_policy_does_not_choose_highest_return_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    left = _card("high-return", _manifest(db, "high-return"))
    right = _card("stable", _manifest(db, "stable"))
    cards = [left, right]
    monkeypatch.setattr(StrategyCardService, "list", lambda _: cards)
    window_id = _window(
        db,
        cards,
        {
            "high-return": ("20", "10", "0.10"),
            "stable": ("10", "2", "0.02"),
        },
    )

    cohort = PaperCohortService(db).build(_build(window_id), actor="test", now=NOW)

    proposals = cohort["groups"][0]["label_proposals"]
    champion = next(item for item in proposals if item["proposed_label"] == "champion_candidate")
    assert champion["card_id"] == "stable"
    assert champion["rank_basis"][-1] == "total_return_last"
    assert cohort["status"] == "review_ready"
    assert cohort["intake_denominator"] == 2
    assert cohort["comparable_count"] == 2
    assert cohort["execution_authorized"] is False


def test_different_cost_models_never_share_a_comparison_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    left = _card("cost-left", _manifest(db, "cost-left", fee="10"))
    right = _card("cost-right", _manifest(db, "cost-right", fee="11"))
    cards = [left, right]
    monkeypatch.setattr(StrategyCardService, "list", lambda _: cards)
    window_id = _window(
        db,
        cards,
        {"cost-left": ("4", "2", "0.02"), "cost-right": ("5", "2", "0.02")},
        suffix="cost",
    )

    cohort = PaperCohortService(db).build(
        _build(window_id, "paper-cohort-build-cost"), actor="test", now=NOW
    )

    assert len(cohort["groups"]) == 2
    assert all(group["member_count"] == 1 for group in cohort["groups"])
    assert all(
        proposal["proposed_label"] == "watch"
        for group in cohort["groups"]
        for proposal in group["label_proposals"]
    )
    assert cohort["status"] == "needs_data"


def test_incomplete_or_non_paper_members_remain_in_fixed_denominator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    card = _card("candidate", _manifest(db, "candidate"), paper="not_started")
    monkeypatch.setattr(StrategyCardService, "list", lambda _: [card])
    window_id = _window(
        db,
        [card],
        {"candidate": ("3", "1", "0.01")},
        suffix="candidate",
        freshness="stale",
        sample_count=5,
    )

    cohort = PaperCohortService(db).build(
        _build(window_id, "paper-cohort-build-candidate"), actor="test", now=NOW
    )

    assert cohort["intake_denominator"] == 1
    assert cohort["comparable_count"] == 0
    assert cohort["proposal_count"] == 0
    reasons = cohort["members"][0]["reasons"]
    assert "paper_status_not_observing" in reasons
    assert "insufficient_sample_count" in reasons
    assert "window_not_fresh" in reasons


def test_build_versions_are_immutable_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    card = _card("versioned", _manifest(db, "versioned"))
    monkeypatch.setattr(StrategyCardService, "list", lambda _: [card])
    first_window = _window(
        db,
        [card],
        {"versioned": ("3", "2", "0.02")},
        suffix="version-one",
    )
    service = PaperCohortService(db)
    first = service.build(_build(first_window), actor="test", now=NOW)
    replay = service.build(_build(first_window), actor="test", now=NOW)
    duplicate = service.build(
        _build(first_window, "paper-cohort-build-duplicate"), actor="test", now=NOW
    )
    second_window = _window(
        db,
        [card],
        {"versioned": ("-4", "7", "0.08")},
        suffix="version-two",
    )
    second = service.build(
        _build(second_window, "paper-cohort-build-002"),
        actor="test",
        now=NOW + timedelta(days=1),
    )

    assert replay["id"] == first["id"]
    assert replay["idempotent"] is True
    assert duplicate["id"] == first["id"]
    assert duplicate["idempotent_content"] is True
    assert first["version_number"] == 1
    assert second["version_number"] == 2
    assert first["content_hash"] != second["content_hash"]
    with db.session() as session:
        assert session.scalar(select(func.count(PaperCohortSnapshot.id))) == 2
        stored = session.get(PaperCohortSnapshot, first["id"])
        assert stored is not None
        assert stored.content_hash == first["content_hash"]


def test_human_label_decision_is_idempotent_and_has_no_paper_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    left = _card("decision-left", _manifest(db, "decision-left"))
    right = _card("decision-right", _manifest(db, "decision-right"))
    cards = [left, right]
    monkeypatch.setattr(StrategyCardService, "list", lambda _: cards)
    window_id = _window(
        db,
        cards,
        {
            "decision-left": ("4", "2", "0.03"),
            "decision-right": ("5", "3", "0.04"),
        },
        suffix="decision",
    )
    service = PaperCohortService(db)
    cohort = service.build(
        _build(window_id, "paper-cohort-build-decision"), actor="test", now=NOW
    )
    proposal = cohort["groups"][0]["label_proposals"][0]
    payload = PaperCohortLabelDecisionV1(
        proposal_id=proposal["proposal_id"],
        decision="accept",
        reason="Accept this expiring paper research label",
        idempotency_key="paper-cohort-decision-001",
    )

    first = service.decide(cohort["id"], payload, actor="admin", now=NOW)
    replay = service.decide(cohort["id"], payload, actor="admin", now=NOW)

    assert first["execution_authorized"] is False
    assert first["paper_lifecycle_authorized"] is False
    assert replay["id"] == first["id"]
    with db.session() as session:
        assert session.scalar(select(func.count(PaperCohortLabelDecision.id))) == 1
        assert session.scalar(select(func.count(PaperPromotion.id))) == 0
        assert session.scalar(select(func.count(PaperReviewRequest.id))) == 0

    expired_payload = payload.model_copy(
        update={"idempotency_key": "paper-cohort-decision-expired"}
    )
    with pytest.raises(ValueError, match="expired"):
        service.decide(
            cohort["id"],
            expired_payload,
            actor="admin",
            now=NOW + timedelta(days=8),
        )


def test_cohort_module_cannot_import_execution_or_paper_adapters() -> None:
    source = (
        Path(__file__).parents[1]
        / "backend"
        / "src"
        / "hypertrade"
        / "portfolio"
        / "cohorts.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "hypertrade.bitpro",
        "hypertrade.paper.service",
        "hypertrade.live",
        "paper_start",
        "paper_pause",
        "live_order",
        "capital_allocation",
    ):
        assert forbidden not in source


def test_paper_cohort_api_requires_admin_and_keeps_decision_non_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    left = _card("api-left", _manifest(db, "api-left"))
    right = _card("api-right", _manifest(db, "api-right"))
    cards = [left, right]
    monkeypatch.setattr(StrategyCardService, "list", lambda _: cards)
    window_id = _window(
        db,
        cards,
        {"api-left": ("5", "2", "0.02"), "api-right": ("4", "3", "0.03")},
        suffix="api",
    )
    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                SESSION_SECRET="paper-cohort-api-test",
            ),
            db=db,
        )
    )

    assert client.get("/api/portfolio/paper-cohorts").status_code == 401
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    created = client.post(
        "/api/portfolio/paper-cohorts",
        json={
            "observation_window_id": window_id,
            "min_sample_count": 20,
            "idempotency_key": "paper-cohort-api-build-001",
        },
    )
    assert created.status_code == 200
    cohort = created.json()
    proposal = cohort["groups"][0]["label_proposals"][0]
    decision = client.post(
        f"/api/portfolio/paper-cohorts/{cohort['id']}/decisions",
        json={
            "proposal_id": proposal["proposal_id"],
            "decision": "hold",
            "reason": "Need another complete paper window",
            "idempotency_key": "paper-cohort-api-decision-001",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["execution_authorized"] is False
    assert client.get("/api/portfolio/paper-cohorts").json()["items"][0]["id"] == cohort["id"]


def test_cohort_cli_renders_server_comparability_without_ranking_logic() -> None:
    class CohortClient:
        def list_paper_cohorts(self) -> list[dict[str, Any]]:
            return [
                {
                    "id": "pcoh_1",
                    "version_number": 2,
                    "status": "review_ready",
                    "intake_count": 3,
                    "comparable_count": 2,
                    "proposal_count": 2,
                }
            ]

    output = StringIO()
    handle_slash_command("/cohorts", client=CohortClient(), output=output)  # type: ignore[arg-type]

    assert "pcoh_1 v2 [review_ready] intake=3 comparable=2 proposals=2" in output.getvalue()
