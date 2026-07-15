from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

import hypertrade.portfolio.lifecycle as lifecycle_module
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import (
    BitProPaperMonitorSnapshot,
    Database,
    PaperPromotion,
    PortfolioAssessment,
    PortfolioObservationWindow,
    ResearchExperimentEvidence,
    ResearchMandate,
)
from hypertrade.main import create_app
from hypertrade.portfolio.lifecycle import (
    ALLOWED_RECOMMENDATIONS,
    PortfolioAssessmentRequestV2,
    PortfolioAssessmentService,
)
from sqlalchemy import select


def _seed_window(
    db: Database,
    *,
    left: str,
    right: str,
    status: str,
    correlation: str | None,
    sample_count: int,
    unknown_reason: str = "",
) -> str:
    with db.session() as session:
        row = PortfolioObservationWindow(
            schema_version="portfolio_observation_window.v1",
            policy_version="portfolio_evidence_policy.v1",
            status="available" if status == "available" else "insufficient",
            horizon_days=30,
            bucket_minutes=60,
            window_start=datetime(2026, 7, 1, tzinfo=UTC),
            window_end=datetime(2026, 7, 2, tzinfo=UTC),
            request_hash=f"request-{left}-{right}",
            source_hash=f"source-{left}-{right}",
            content_hash=f"content-{left}-{right}",
            idempotency_key=f"window-{left}-{right}",
            source_refs_json={},
            quality_json={"status": status, "coverage_ratio": "1.00000000"},
            strategy_summaries_json=[
                {
                    "card_id": card_id,
                    "status": status,
                    "metrics": {
                        "max_drawdown_pct": "2.00000000",
                        "capacity": "unknown",
                        "liquidity": "unknown",
                        "risk_contribution": "unknown",
                    },
                }
                for card_id in (left, right)
            ],
            pairwise_json=[
                {
                    "left_card_id": left,
                    "right_card_id": right,
                    "status": status,
                    "correlation": correlation,
                    "sample_count": sample_count,
                    "sample_start": "2026-07-01T01:00:00+00:00" if sample_count else None,
                    "sample_end": "2026-07-01T07:00:00+00:00" if sample_count else None,
                    "unknown_reason": unknown_reason,
                    "source_hashes": ["curve-left", "curve-right"],
                }
            ],
            created_by="test",
        )
        session.add(row)
        session.flush()
        return row.id


def _seed_strategy(
    db: Database,
    *,
    name: str,
    strategy_id: int,
    status: str = "paper_observing",
    equities: list[str] | None = None,
    start: datetime | None = None,
) -> str:
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
            result_refs_json={"bitpro_result_id": f"result_{strategy_id}"},
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
            request_reason="portfolio fixture",
            approval_reason="reviewed",
            approval_idempotency_key=f"approve-{name}",
            approved_by="admin",
            paper_refs_json={},
            observation_json={},
            transition_json=[],
        )
        session.add(promotion)
        session.flush()
        card_id = f"scard_{promotion.id.removeprefix('ppr_')}"
        base = start or datetime(2026, 7, 1, tzinfo=UTC)
        for index, equity in enumerate(equities or []):
            session.add(
                BitProPaperMonitorSnapshot(
                    scope_key=str(strategy_id),
                    strategy_id=strategy_id,
                    status="completed",
                    dashboard_json={},
                    running_strategies_json={},
                    monitor_summary_json={},
                    event_summary_json={},
                    equity_summary_json={"count": len(equities or [])},
                    metrics_json={
                        "latest_equity": equity,
                        "max_drawdown_pct": "2.0",
                    },
                    drift_json={"alerts": [], "data_gaps": []},
                    tool_calls_json=[],
                    created_at=base + timedelta(hours=index),
                    updated_at=base + timedelta(hours=index),
                )
            )
        return card_id


def _world_state() -> dict:
    return {
        "source_id": "world_state_fixture",
        "generated_at": "2026-07-01T12:00:00+00:00",
        "global_market": {"risk_regime": "risk_on"},
    }


def test_bounded_aligned_correlation_and_shared_exposure_persist_only_summary() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    left = _seed_strategy(
        db,
        name="trend_left",
        strategy_id=101,
        equities=["100", "101", "103", "102", "105", "107", "106", "109"],
    )
    right = _seed_strategy(
        db,
        name="trend_right",
        strategy_id=102,
        equities=["200", "202", "206", "204", "210", "214", "212", "218"],
    )
    window_id = _seed_window(
        db,
        left=left,
        right=right,
        status="available",
        correlation="1.00000000",
        sample_count=7,
    )

    assessment = PortfolioAssessmentService(db).assess(
        PortfolioAssessmentRequestV2(
            strategy_card_ids=[left, right],
            max_series_points=8,
            min_aligned_returns=6,
            idempotency_key="portfolio-correlation-001",
            observation_window_id=window_id,
        ),
        actor="admin",
        world_state=_world_state(),
    )

    pair = assessment["pairwise"][0]
    assert pair["correlation_status"] == "available"
    assert pair["correlation"] == "1.00000000"
    assert pair["sample_count"] == 7
    assert pair["shared_exposures"] == {
        "symbols": ["BTC"],
        "timeframes": ["1H"],
        "factors": ["TREND"],
    }
    assert any(
        item["action"] == "request_risk_budget_review"
        for item in assessment["recommendations"]
    )
    assert pair["source_snapshot_ids"]
    for recommendation in assessment["recommendations"]:
        assert recommendation["evidence_refs"]
        assert recommendation["valid_until"] == assessment["valid_until"]
        assert recommendation["human_review_status"] in {"pending", "not_required"}
    with db.session() as session:
        stored = session.scalar(select(PortfolioAssessment))
        assert stored is not None
        serialized = str(stored.pairwise_json) + str(stored.strategy_assessments_json)
        assert "equity_curve" not in serialized
        assert "return_series" not in serialized


def test_insufficient_or_misaligned_series_remains_unknown_without_fake_number() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    left = _seed_strategy(
        db,
        name="short_left",
        strategy_id=201,
        equities=["100", "101", "102"],
    )
    right = _seed_strategy(
        db,
        name="misaligned_right",
        strategy_id=202,
        equities=["100", "99", "98"],
        start=datetime(2026, 7, 3, tzinfo=UTC),
    )
    window_id = _seed_window(
        db,
        left=left,
        right=right,
        status="unknown",
        correlation=None,
        sample_count=0,
        unknown_reason="insufficient_aligned_returns",
    )

    assessment = PortfolioAssessmentService(db).assess(
        PortfolioAssessmentRequestV2(
            strategy_card_ids=[left, right],
            idempotency_key="portfolio-unknown-001",
            observation_window_id=window_id,
        ),
        actor="admin",
        world_state=_world_state(),
    )

    pair = assessment["pairwise"][0]
    assert pair["correlation_status"] == "unknown"
    assert pair["correlation"] is None
    assert pair["sample_count"] == 0
    assert pair["unknown_reason"] == "insufficient_aligned_returns"
    assert any(value.startswith("correlation.") for value in assessment["unknowns"])


def test_portfolio_assessment_api_requires_admin_and_persists_read_only_result() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _seed_strategy(db, name="api_strategy", strategy_id=301, equities=[])
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            OKX_REST_URL="http://127.0.0.1:9",
        ),
        db=db,
    )
    client = TestClient(app)
    payload = {"idempotency_key": "portfolio-api-001"}

    assert client.post("/api/portfolio/assessments", json=payload).status_code == 401
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    created = client.post("/api/portfolio/assessments", json=payload)

    assert created.status_code == 200
    assert created.json()["schema_version"] == "portfolio_assessment.v2"
    assert all(
        recommendation["trading_mutation_allowed"] is False
        for recommendation in created.json()["recommendations"]
    )
    assert client.get("/api/portfolio/assessments").json()["items"]


def test_portfolio_lifecycle_has_no_execution_adapter_reachability() -> None:
    source = inspect.getsource(lifecycle_module)

    assert {
        "observe",
        "run_targeted_research",
        "request_paper_review",
        "request_pause_review",
        "retire_candidate_review",
        "request_risk_budget_review",
    } == ALLOWED_RECOMMENDATIONS
    for forbidden in (
        "BitProToolAdapter",
        "paper_start",
        "paper_pause",
        "live_order",
        "place_order",
    ):
        assert forbidden not in source
