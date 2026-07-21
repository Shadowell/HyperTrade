from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypertrade.db import StrategyLessonCandidate
from hypertrade.research.outcome_ledger import (
    LessonCandidateService,
    StrategyOutcomeLedgerService,
)
from hypertrade.research.outcome_schemas import LessonCandidateV1, LessonReviewV1
from outcome_fixtures import outcome_payload, seeded_db


def _lesson(
    outcome_ids: list[str],
    *,
    key: str,
    claim: str,
    stance: str = "supporting",
    opposition: list[str] | None = None,
) -> LessonCandidateV1:
    opposing = opposition or []
    supporting = [item for item in outcome_ids if item not in opposing]
    return LessonCandidateV1.model_validate(
        {
            "claim": claim,
            "outcome_ids": outcome_ids,
            "support_outcome_ids": supporting,
            "opposition_outcome_ids": opposing,
            "stance": stance,
            "scope": {"symbols": ["BTC-USDT-SWAP"], "timeframes": ["1h"]},
            "regimes": ["trend"],
            "confidence": Decimal("0.7"),
            "confidence_method": "reviewed_frequency",
            "valid_until": datetime.now(UTC) + timedelta(days=30),
            "producer_lineage": {"service": "lesson_generator", "version": "1"},
            "target_type": "memory",
            "idempotency_key": key,
        }
    )


def test_lesson_requires_outcomes_and_review_before_context_use() -> None:
    db, refs = seeded_db()
    outcome = StrategyOutcomeLedgerService(db).append(outcome_payload(refs), actor="validator")
    service = LessonCandidateService(db)
    proposed = service.propose(
        _lesson(
            [outcome["id"]],
            key="lesson-candidate-key-001",
            claim="Trend regimes supported the tested configuration.",
        ),
        actor="lesson_generator",
    )

    assert proposed["status"] == "proposed" and proposed["usable"] is False
    assert service.active_for_context() == []
    with pytest.raises(PermissionError, match="cannot approve"):
        service.review(
            proposed["id"],
            LessonReviewV1(
                decision="approve",
                reason="model self approval",
                idempotency_key="lesson-review-model-001",
            ),
            actor="model",
        )

    active = service.review(
        proposed["id"],
        LessonReviewV1(
            decision="approve",
            reason="sources and scope independently reviewed",
            idempotency_key="lesson-review-human-001",
        ),
        actor="research_reviewer",
    )
    assert active["status"] == "active" and active["usable"] is True
    assert service.active_for_context()[0]["id"] == proposed["id"]


def test_conflicting_lessons_coexist_with_explicit_stance() -> None:
    db, refs = seeded_db()
    ledger = StrategyOutcomeLedgerService(db)
    first = ledger.append(outcome_payload(refs), actor="validator")
    second = ledger.append(
        outcome_payload(
            refs,
            key="strategy-outcome-key-002",
            corrects_id=first["id"],
            outcome_type="research_rejected",
            metrics={"return_pct": "-3"},
            unknowns=["regime attribution remains uncertain"],
            failure_class="robustness_gate_failed",
        ),
        actor="validator",
    )
    service = LessonCandidateService(db)
    mixed = service.propose(
        _lesson(
            [first["id"], second["id"]],
            key="lesson-conflict-key-001",
            claim="The configuration is regime-sensitive and needs more observations.",
            stance="mixed",
            opposition=[second["id"]],
        ),
        actor="lesson_generator",
    )

    assert mixed["support_outcome_ids"] == [first["id"]]
    assert mixed["opposition_outcome_ids"] == [second["id"]]
    assert mixed["stance"] == "mixed"


def test_single_profit_never_auto_activates_memory_or_policy() -> None:
    db, refs = seeded_db()
    outcome = StrategyOutcomeLedgerService(db).append(outcome_payload(refs), actor="validator")
    service = LessonCandidateService(db)
    proposed = service.propose(
        _lesson(
            [outcome["id"]],
            key="lesson-profit-key-001",
            claim="One profitable result is only a candidate.",
        ),
        actor="agent",
    )

    assert proposed["status"] == "proposed"
    assert proposed["target_type"] == "memory"
    assert service.active_for_context() == []
    assert service.replay_hash() == service.replay_hash()


def test_missing_outcome_and_idempotency_conflict_are_rejected() -> None:
    db, refs = seeded_db()
    service = LessonCandidateService(db)
    with pytest.raises(ValueError, match="canonical outcomes"):
        service.propose(
            _lesson(
                ["sout_missing"],
                key="lesson-missing-key-001",
                claim="Missing sources cannot teach.",
            ),
            actor="agent",
        )
    outcome = StrategyOutcomeLedgerService(db).append(outcome_payload(refs), actor="validator")
    service.propose(
        _lesson([outcome["id"]], key="lesson-idempotency-key-001", claim="Original claim."),
        actor="agent",
    )
    with pytest.raises(ValueError, match="bound to another payload"):
        service.propose(
            _lesson([outcome["id"]], key="lesson-idempotency-key-001", claim="Changed claim."),
            actor="agent",
        )


def test_expired_lesson_is_removed_from_context_without_rewriting_outcome() -> None:
    db, refs = seeded_db()
    outcome = StrategyOutcomeLedgerService(db).append(outcome_payload(refs), actor="validator")
    service = LessonCandidateService(db)
    proposed = service.propose(
        _lesson(
            [outcome["id"]],
            key="lesson-expiry-key-001",
            claim="Time-bounded lessons must expire from context.",
        ),
        actor="agent",
    )
    service.review(
        proposed["id"],
        LessonReviewV1(
            decision="approve",
            reason="bounded source was independently reviewed",
            idempotency_key="lesson-expiry-review-001",
        ),
        actor="research_reviewer",
    )
    with db.session() as session:
        row = session.get(StrategyLessonCandidate, proposed["id"])
        assert row is not None
        row.valid_until = datetime.now(UTC) - timedelta(seconds=1)

    assert service.active_for_context() == []
    assert service.list(status="expired")[0]["id"] == proposed["id"]
    assert (
        StrategyOutcomeLedgerService(db).get(outcome["id"])["content_hash"]
        == outcome["content_hash"]
    )
