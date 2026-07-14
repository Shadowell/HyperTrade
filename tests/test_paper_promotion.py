from __future__ import annotations

from typing import Any

import pytest
from hypertrade.db import (
    Database,
    ExperimentEvidenceLink,
    ResearchExperimentEvidence,
    ResearchMandate,
    RobustnessValidationRun,
)
from hypertrade.research.paper_promotion import PaperPromotionService


class PaperFixtureAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.missing_metrics = False

    def paper_configure(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("paper_configure")
        assert kwargs["idempotency_key"]
        return {"paper": {"instance_id": 901}, "tool_calls": []}

    def paper_start(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("paper_start")
        assert kwargs["strategy_id"] == 901
        assert kwargs["idempotency_key"]
        return {"paper": {"status": "running"}, "tool_calls": []}

    def paper_snapshot(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("paper_snapshot")
        snapshot = {
            "instance_id": "paper_901",
            "strategy_id": 42,
            "strategy_version": "script-sha",
            "config_version": "config-v1",
            "status": "running",
            "equity": 10010,
            "pnl": 10,
            "cumulative_return_pct": 0.1,
            "max_drawdown_pct": 1,
            "sharpe_ratio": 1.2,
            "trade_count": 1,
            "error_count": 0,
            "generated_at": "2026-07-13T00:00:00Z",
            "data_coverage": {"equity_sample_count": 2},
        }
        if self.missing_metrics:
            snapshot["data_coverage"] = {"equity_sample_count": 0}
        return {
            "snapshot": snapshot,
            "tool_calls": [],
        }


def _passing_evidence(db: Database) -> str:
    with db.session() as session:
        mandate = ResearchMandate(
            name="paper mandate",
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
            job_id="rjob_001",
            mandate_id=mandate.id,
            variant_id="baseline",
            status="evidence_recorded",
            strategy_key="btc_trend",
            bitpro_strategy_id="42",
            result_refs_json={},
            windows_json={},
            parameters_json={},
            metrics_json={},
            gate_results_json={"real_data": True, "locked": True},
            rejection_reasons_json=[],
            tool_calls_json=[],
        )
        session.add(evidence)
        session.flush()
        return evidence.id


def test_paper_promotion_requires_passing_evidence_and_human_approval() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    evidence_id = _passing_evidence(db)
    adapter = PaperFixtureAdapter()
    service = PaperPromotionService(db, bitpro_adapter=adapter)

    pending = service.request(evidence_id=evidence_id, reason="operator wants paper evidence")
    assert pending["status"] == "pending_paper_approval"
    assert adapter.calls == []
    with pytest.raises(ValueError, match="reason and idempotency"):
        service.approve(
            promotion_id=pending["id"], reason="", idempotency_key="", approved_by="admin"
        )
    assert adapter.calls == []

    observing = service.approve(
        promotion_id=pending["id"],
        reason="approved",
        idempotency_key="paper-key-0001",
        approved_by="admin",
    )
    assert observing["status"] == "paper_observing"
    assert adapter.calls == ["paper_configure", "paper_start"]
    assert (
        service.approve(
            promotion_id=pending["id"],
            reason="ignored",
            idempotency_key="paper-key-0001",
            approved_by="admin",
        )["id"]
        == pending["id"]
    )


def test_ledger_evidence_requires_validated_robustness_before_paper_queue() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    evidence_id = _passing_evidence(db)
    with db.session() as session:
        session.add(
            ExperimentEvidenceLink(
                execution_id="exex_robustness_test",
                evidence_id=evidence_id,
                evidence_kind="legacy_experiment",
                created_by="test",
            )
        )
        session.add(
            RobustnessValidationRun(
                experiment_execution_id="exex_robustness_test",
                fingerprint="a" * 64,
                policy_version="robustness_policy.v2",
                policy_hash="b" * 64,
                policy_json={},
                plan_json={},
                final_status="needs_data",
                gate_results_json={"cost_stress": {"outcome": "unknown"}},
                summary_json={},
                unknowns_json=["gate:cost_stress"],
                created_by="test",
            )
        )

    with pytest.raises(ValueError, match="requires a validated robustness run"):
        PaperPromotionService(db).request(
            evidence_id=evidence_id, reason="should remain blocked"
        )
    with db.session() as session:
        run = session.query(RobustnessValidationRun).one()
        run.final_status = "validated"

    pending = PaperPromotionService(db).request(
        evidence_id=evidence_id, reason="robustness now validated"
    )
    assert pending["status"] == "pending_paper_approval"


def test_paper_observation_is_read_only_and_keeps_data_gaps_visible() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    evidence_id = _passing_evidence(db)
    adapter = PaperFixtureAdapter()
    service = PaperPromotionService(db, bitpro_adapter=adapter)
    pending = service.request(evidence_id=evidence_id, reason="paper review")
    service.approve(
        promotion_id=pending["id"],
        reason="approved",
        idempotency_key="paper-key-0002",
        approved_by="admin",
    )

    observed = service.observe(pending["id"])

    assert observed["status"] == "paper_observing"
    assert observed["observation"]["snapshot_id"] == "paper_901"
    assert (
        observed["observation"]["history"][-1]["snapshot_id"]
        == observed["observation"]["snapshot_id"]
    )
    assert adapter.calls[-1:] == ["paper_snapshot"]
    assert "paper_pause" not in adapter.calls


def test_paper_observation_marks_data_gaps_degraded_without_lifecycle_write() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    adapter = PaperFixtureAdapter()
    service = PaperPromotionService(db, bitpro_adapter=adapter)
    pending = service.request(evidence_id=_passing_evidence(db), reason="paper review")
    service.approve(
        promotion_id=pending["id"],
        reason="approved",
        idempotency_key="paper-key-0003",
        approved_by="admin",
    )
    adapter.missing_metrics = True

    observed = service.observe(pending["id"])

    assert observed["status"] == "paper_degraded"
    assert observed["observation"]["recommended_next_action"] == "operator_review"
    assert "missing equity sample coverage" in observed["observation"]["drift"]["data_gaps"]
    assert adapter.calls == [
        "paper_configure",
        "paper_start",
        "paper_snapshot",
    ]
