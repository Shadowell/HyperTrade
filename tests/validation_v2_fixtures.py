from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from discovery_fixtures import (
    NOW as DISCOVERY_NOW,
)
from discovery_fixtures import (
    FakeDiscoveryAdapter,
    discovery_request,
    seeded_discovery_db,
)
from evolution_fixtures import NOW as EVOLUTION_NOW
from evolution_fixtures import evolution_request, seeded_evolution_db
from hypertrade.db import Database, StrategyDiscoveryCandidate, StrategyEvolutionCandidate
from hypertrade.research.discovery import StrategyDiscoveryService
from hypertrade.research.evolution import StrategyEvolutionService
from hypertrade.research.validation_v2_schemas import (
    TrialAttemptV1,
    TrialFamilyV1,
    UnifiedValidationEvidenceV2,
    UnifiedValidationRequestV2,
    ValidationPolicyV2,
)


def seeded_validation_candidate(kind: str) -> tuple[Database, dict[str, str]]:
    if kind == "evolution":
        db, refs = seeded_evolution_db()
        result = StrategyEvolutionService(db).evolve(
            evolution_request(refs), actor="test", now=EVOLUTION_NOW
        )
        candidate = result["candidates"][0]
        with db.session() as session:
            row = session.get(StrategyEvolutionCandidate, candidate["id"])
            assert row is not None
            frozen_at = row.created_at
    else:
        db, refs = seeded_discovery_db()
        result = StrategyDiscoveryService(db, adapter=FakeDiscoveryAdapter()).discover(
            discovery_request(refs), actor="test", now=DISCOVERY_NOW
        )
        candidate = result["candidates"][0]
        with db.session() as session:
            row = session.get(StrategyDiscoveryCandidate, candidate["id"])
            assert row is not None
            frozen_at = datetime.fromisoformat(
                str(row.hypothesis_json["frozen_at"]).replace("Z", "+00:00")
            )
    if frozen_at.tzinfo is None:
        frozen_at = frozen_at.replace(tzinfo=UTC)
    return db, {
        "kind": kind,
        "candidate_id": str(candidate["id"]),
        "manifest_id": str(candidate["manifest_id"]),
        "execution_id": str(candidate["experiment_execution_id"]),
        "frozen_at": frozen_at.isoformat(),
    }


def validation_request(
    refs: dict[str, str],
    *,
    key: str = "unified-validation-request-001",
    evidence_changes: dict[str, object] | None = None,
    family_changes: dict[str, object] | None = None,
    policy_changes: dict[str, object] | None = None,
) -> UnifiedValidationRequestV2:
    frozen = datetime.fromisoformat(refs["frozen_at"])
    family: dict[str, object] = {
        "family_id": f"trial-family-{refs['kind']}-001",
        "candidate_kind": refs["kind"],
        "candidate_id": refs["candidate_id"],
        "manifest_id": refs["manifest_id"],
        "experiment_execution_id": refs["execution_id"],
        "candidate_frozen_at": frozen,
        "locked_oos_first_accessed_at": frozen + timedelta(seconds=1),
        "attempts": [
            TrialAttemptV1(
                trial_id="trial_failed_001",
                status="failed",
                result_ref="bitpro:result:failed:1",
            ),
            TrialAttemptV1(
                trial_id="trial_selected_002",
                status="completed",
                selected=True,
                result_ref="bitpro:result:completed:2",
            ),
        ],
        "declared_attempt_count": 2,
    }
    family.update(family_changes or {})
    evidence: dict[str, object] = {
        "source_hash": "sha256:" + "c" * 64,
        "result_refs": ["bitpro:result:completed:2"],
        "artifact_refs": ["bitpro:artifact:validation:2"],
        "real_data": True,
        "chronological_split": True,
        "locked_oos_complete": True,
        "purge_embargo_applied": True,
        "costs_complete": True,
        "funding_included": True,
        "capacity_assessed": True,
        "locked_oos_return": Decimal("1.0"),
        "trade_count": 100,
        "max_drawdown_pct": Decimal("10"),
        "tail_loss_pct": Decimal("5"),
        "probabilistic_sharpe": Decimal("0.9"),
        "deflated_sharpe": Decimal("0.8"),
        "overfit_probability": Decimal("0.1"),
        "walk_forward_returns": [Decimal("1"), Decimal("0.5"), Decimal("1.5")],
        "parameter_neighbor_returns": [Decimal("0.7"), Decimal("0.8")],
        "cost_stress_multiplier": Decimal("1.5"),
        "cost_stress_return": Decimal("0.2"),
        "regime_results": {"trend": Decimal("0.5"), "range": Decimal("0.2")},
        "regime_label_mode": "point_in_time",
        "novelty_falsification_passed": True,
    }
    evidence.update(evidence_changes or {})
    policy = ValidationPolicyV2.model_validate(policy_changes or {})
    return UnifiedValidationRequestV2(
        policy=policy,
        trial_family=TrialFamilyV1.model_validate(family),
        evidence=UnifiedValidationEvidenceV2.model_validate(evidence),
        idempotency_key=key,
    )
