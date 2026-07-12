from __future__ import annotations

from hypertrade.db import Database, PaperPromotion, ResearchExperimentEvidence, ResearchMandate
from hypertrade.research.strategy_cards import StrategyCardService


def test_strategy_card_joins_passing_evidence_and_paper_review_state() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        mandate = ResearchMandate(
            name="card mandate",
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
            job_id="rjob_card",
            mandate_id=mandate.id,
            variant_id="base",
            status="evidence_recorded",
            strategy_key="btc_trend",
            bitpro_strategy_id="42",
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
        session.add(
            PaperPromotion(
                mandate_id=mandate.id,
                job_id=evidence.job_id,
                evidence_id=evidence.id,
                strategy_key=evidence.strategy_key,
                bitpro_strategy_id="42",
                status="paper_review_required",
                request_reason="review",
                approval_reason="approved",
                approval_idempotency_key="card-key",
                approved_by="admin",
                paper_refs_json={},
                observation_json={"drift": {"data_gaps": ["missing equity"], "alerts": []}},
                transition_json=[],
            )
        )

    card = StrategyCardService(db).list()[0]

    assert card["validation_status"] == "passed"
    assert card["paper_status"] == "paper_review_required"
    assert card["declared_regime_fit"] == ["risk_on", "mixed"]
    assert "missing equity" in card["coverage_flags"]
    assert card["qualified_for_paper_review"] is False
