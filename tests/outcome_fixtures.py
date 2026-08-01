from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypertrade.db import (
    AgentMission,
    Database,
    ExperimentExecution,
    ExperimentManifest,
    PortfolioObservationWindow,
    ResearchEvidence,
    StrategyCardSnapshot,
    StrategyLineage,
    StrategyVersion,
)
from hypertrade.research.outcome_schemas import OutcomeWindowV1, StrategyOutcomeV1

WINDOW_START = datetime(2026, 7, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 7, 15, tzinfo=UTC)
AS_OF = datetime(2026, 7, 16, tzinfo=UTC)
SETTLED_AT = datetime(2026, 7, 17, tzinfo=UTC)


def seeded_db() -> tuple[Database, dict[str, str]]:
    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as session:
        manifest = ExperimentManifest(
            schema_version="experiment_manifest.v1",
            fingerprint="a" * 64,
            strategy_key="btc_trend_v1",
            mandate_id="mandate_research",
            canonical_json={"strategy_code_sha256": "b" * 64},
            created_by="test",
        )
        session.add(manifest)
        session.flush()
        lineage = StrategyLineage(
            lineage_key="c" * 64,
            mandate_id="mandate_research",
            strategy_key="btc_trend_v1",
            created_by="test",
        )
        session.add(lineage)
        session.flush()
        version = StrategyVersion(
            lineage_id=lineage.id,
            version_number=1,
            manifest_id=manifest.id,
            manifest_fingerprint=manifest.fingerprint,
            strategy_spec_hash="d" * 64,
            created_by="test",
        )
        session.add(version)
        session.flush()
        card_id = "strategy_card_test"
        session.add(
            StrategyCardSnapshot(
                card_id=card_id,
                lineage_id=lineage.id,
                version_id=version.id,
                schema_version="strategy_card.v2",
                lifecycle_status="validated",
                completeness_score=Decimal("1"),
                content_hash="e" * 64,
                card_json={"card_id": card_id, "version": {"id": version.id}},
                created_by="test",
            )
        )
        execution = ExperimentExecution(
            manifest_id=manifest.id,
            attempt=1,
            status="completed",
            idempotency_key="seed-execution-key",
            artifact_manifest_json={
                "schema_version": "experiment_artifacts.v1",
                "items": [{"artifact_ref": "bitpro:backtest:seed"}],
            },
            completed_at=SETTLED_AT,
            created_by="test",
        )
        session.add(execution)
        mission = AgentMission(
            objective="Validate a bounded strategy outcome",
            original_objective="Validate a bounded strategy outcome",
            success_criteria_json=[],
            status="completed",
            permission_profile_ref="research-read-only.v1",
            context_policy_ref="context.v1",
            version=3,
            completion_proof_json={
                "schema_version": "completion_proof.v1",
                "proof_id": "cpf_seed",
                "mission_id": "pending",
                "mission_version": 3,
                "plan_version": 1,
                "passed": True,
                "criteria": [],
                "evidence_refs": [],
                "artifact_refs": ["mission:artifact:seed"],
                "gaps": [],
                "pending_attempt_ids": [],
                "effect_unknown": False,
                "budget_valid": True,
            },
            created_by="test",
            idempotency_key="seed-mission-key",
            request_hash="f" * 64,
        )
        session.add(mission)
        session.flush()
        mission.completion_proof_json = {
            **mission.completion_proof_json,
            "mission_id": mission.id,
        }
        evidence = ResearchEvidence(
            schema_version="evidence.v2",
            evidence_type="fact",
            status="active",
            claim="Backtest passed declared robustness gates.",
            confidence=Decimal("0.8"),
            as_of=WINDOW_END,
            valid_until=datetime.now(UTC) + timedelta(days=30),
            content_hash="1" * 64,
            created_by="test",
        )
        session.add(evidence)
        window = PortfolioObservationWindow(
            schema_version="portfolio_observation_window.v1",
            policy_version="portfolio_evidence_policy.v1",
            status="available",
            horizon_days=30,
            bucket_minutes=60,
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            request_hash="2" * 64,
            source_hash="3" * 64,
            content_hash="4" * 64,
            idempotency_key="seed-window-key",
            source_refs_json={"adapter": "fixture"},
            quality_json={"status": "available"},
            strategy_summaries_json=[{"card_id": card_id, "status": "available"}],
            pairwise_json=[],
            created_by="test",
        )
        session.add(window)
        session.flush()
        refs = {
            "manifest_id": manifest.id,
            "lineage_id": lineage.id,
            "version_id": version.id,
            "card_id": card_id,
            "execution_id": execution.id,
            "mission_id": mission.id,
            "evidence_id": evidence.id,
            "window_id": window.id,
        }
    return db, refs


def outcome_payload(
    refs: dict[str, str], *, key: str = "strategy-outcome-key-001", **changes: object
) -> StrategyOutcomeV1:
    values: dict[str, object] = {
        "outcome_type": "backtest_validated",
        "strategy_lineage_id": refs["lineage_id"],
        "strategy_version_id": refs["version_id"],
        "strategy_card_id": refs["card_id"],
        "manifest_id": refs["manifest_id"],
        "experiment_execution_id": refs["execution_id"],
        "mission_id": refs["mission_id"],
        "evidence_ids": [refs["evidence_id"]],
        "artifact_refs": ["bitpro:backtest:seed"],
        "parameters": {"lookback": Decimal("20")},
        "data_window": OutcomeWindowV1(start=WINDOW_START, end=WINDOW_END),
        "cost_model": {"fees": "included", "slippage": "5bps"},
        "regimes": ["trend"],
        "metrics": {"return_pct": Decimal("4.2"), "max_drawdown_pct": Decimal("2.1")},
        "decision_snapshot": {"decision": "validated"},
        "producer_lineage": {"service": "test", "version": "1"},
        "as_of": AS_OF,
        "settled_at": SETTLED_AT,
        "idempotency_key": key,
    }
    values.update(changes)
    return StrategyOutcomeV1.model_validate(values)
