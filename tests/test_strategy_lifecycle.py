from __future__ import annotations

import pytest
from hypertrade.db import (
    Database,
    PaperPromotion,
    ResearchExperimentEvidence,
    ResearchMandate,
    StrategyLifecycleReview,
)
from hypertrade.portfolio.lifecycle import (
    PortfolioAssessmentRequestV2,
    PortfolioAssessmentService,
    StrategyLifecycleDecisionV1,
)
from sqlalchemy import select


def _seed_strategy(
    db: Database,
    *,
    name: str,
    strategy_id: int,
    status: str = "paper_observing",
    equities: list[str] | None = None,
) -> str:
    del equities
    with db.session() as session:
        mandate = ResearchMandate(
            name=f"{name} mandate",
            status="active",
            market_type="SWAP",
            symbols_json=["BTC"],
            timeframes_json=["1H"],
            strategy_categories_json=["TREND"],
            budget_json={},
            validation_json={},
            paper_promotion_mode="manual_approval",
            live_mode="disabled",
            audit_json=[],
        )
        session.add(mandate)
        session.flush()
        evidence = ResearchExperimentEvidence(
            job_id=f"rjob_{name}",
            mandate_id=mandate.id,
            variant_id="base",
            status="evidence_recorded",
            strategy_key=name,
            bitpro_strategy_id=str(strategy_id),
            result_refs_json={},
            windows_json={},
            parameters_json={},
            metrics_json={},
            gate_results_json={"oos": True},
            rejection_reasons_json=[],
            tool_calls_json=[],
        )
        session.add(evidence)
        session.flush()
        promotion = PaperPromotion(
            mandate_id=mandate.id,
            job_id=evidence.job_id,
            evidence_id=evidence.id,
            strategy_key=name,
            bitpro_strategy_id=str(strategy_id),
            status=status,
            request_reason="fixture",
            approval_reason="reviewed",
            approval_idempotency_key=f"approve-{name}",
            approved_by="admin",
            paper_refs_json={},
            observation_json={},
            transition_json=[],
        )
        session.add(promotion)
        session.flush()
        return f"scard_{promotion.id.removeprefix('ppr_')}"


def _world_state() -> dict:
    return {
        "source_id": "world_state_fixture",
        "generated_at": "2026-07-01T12:00:00+00:00",
        "global_market": {"risk_regime": "risk_on"},
    }


def test_lifecycle_review_records_human_fact_without_dispatching_mutation() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    card_id = _seed_strategy(
        db,
        name="degraded_strategy",
        strategy_id=401,
        status="paper_review_required",
        equities=[],
    )
    service = PortfolioAssessmentService(db)
    assessment = service.assess(
        PortfolioAssessmentRequestV2(
            strategy_card_ids=[card_id],
            idempotency_key="lifecycle-assessment-001",
        ),
        actor="admin",
        world_state=_world_state(),
    )
    recommendation = assessment["recommendations"][0]
    assert recommendation["action"] == "request_pause_review"
    assert recommendation["allocation_change_allowed"] is False
    assert recommendation["trading_mutation_allowed"] is False

    reviewed = service.review(
        str(assessment["id"]),
        StrategyLifecycleDecisionV1(
            recommendation_id=str(recommendation["recommendation_id"]),
            decision="hold",
            reason="observe another bounded paper window before operator action",
            idempotency_key="lifecycle-review-001",
        ),
        actor="admin",
    )

    assert reviewed["decision"] == "hold"
    assert reviewed["recommendation_action"] == "request_pause_review"
    with db.session() as session:
        rows = session.scalars(select(StrategyLifecycleReview)).all()
        assert len(rows) == 1


def test_review_rejects_recommendation_from_another_assessment_and_is_idempotent() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    card_id = _seed_strategy(
        db,
        name="review_strategy",
        strategy_id=402,
        equities=[],
    )
    service = PortfolioAssessmentService(db)
    first = service.assess(
        PortfolioAssessmentRequestV2(
            strategy_card_ids=[card_id],
            idempotency_key="lifecycle-first-001",
        ),
        actor="admin",
        world_state=_world_state(),
    )
    second = service.assess(
        PortfolioAssessmentRequestV2(
            strategy_card_ids=[card_id],
            idempotency_key="lifecycle-second-001",
        ),
        actor="admin",
        world_state={**_world_state(), "generated_at": "2026-07-01T13:00:00+00:00"},
    )
    payload = StrategyLifecycleDecisionV1(
        recommendation_id=str(first["recommendations"][0]["recommendation_id"]),
        decision="accept",
        reason="accept research-only observation",
        idempotency_key="lifecycle-idempotent-review",
    )
    accepted = service.review(str(first["id"]), payload, actor="admin")
    replay = service.review(str(first["id"]), payload, actor="admin")

    assert replay["id"] == accepted["id"]
    assert replay["idempotent"] is True
    with pytest.raises(ValueError, match="bound to another decision"):
        service.review(
            str(first["id"]),
            payload.model_copy(update={"reason": "a materially different reason"}),
            actor="admin",
        )
    diff = service.diff(str(first["id"]), str(second["id"]))
    assert diff["content_hash_changed"] is True


def test_assessment_idempotency_key_is_bound_to_the_request() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    card_id = _seed_strategy(db, name="idempotent_strategy", strategy_id=403)
    service = PortfolioAssessmentService(db)
    payload = PortfolioAssessmentRequestV2(
        strategy_card_ids=[card_id],
        idempotency_key="portfolio-request-binding-001",
    )

    created = service.assess(payload, actor="admin", world_state=_world_state())
    replay = service.assess(payload, actor="admin", world_state=_world_state())

    assert replay["id"] == created["id"]
    assert replay["idempotent"] is True
    with pytest.raises(ValueError, match="bound to another request"):
        service.assess(
            payload.model_copy(update={"max_series_points": 32}),
            actor="admin",
            world_state=_world_state(),
        )
