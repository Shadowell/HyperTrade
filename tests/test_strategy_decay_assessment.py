from __future__ import annotations

from evolution_fixtures import NOW, seeded_evolution_db
from hypertrade.db import StrategyOutcome
from hypertrade.research.evolution import StrategyEvolutionService


def test_decay_assessment_requires_multiple_settled_outcomes() -> None:
    db, refs = seeded_evolution_db()
    service = StrategyEvolutionService(db)

    actionable = service.assess_decay(
        parent_version_id=str(refs["parent_version_id"]),
        outcome_ids=list(refs["outcome_ids"]),
        evidence_record_ids=[str(refs["evidence_record_id"])],
        now=NOW,
    )
    single = service.assess_decay(
        parent_version_id=str(refs["parent_version_id"]),
        outcome_ids=[list(refs["outcome_ids"])[-1]],
        evidence_record_ids=[str(refs["evidence_record_id"])],
        now=NOW,
    )

    assert actionable.classification == "performance_decay"
    assert actionable.status == "actionable"
    assert single.classification == "unknown"
    assert single.status == "needs_review"
    assert "single_outcome_cannot_trigger_evolution" in single.unknowns


def test_data_gap_and_execution_drift_are_distinguished() -> None:
    db, refs = seeded_evolution_db()
    outcome_ids = list(refs["outcome_ids"])
    with db.session() as session:
        outcome = session.get(StrategyOutcome, outcome_ids[-1])
        assert outcome is not None
        outcome.outcome_json = {**outcome.outcome_json, "data_gaps": ["fills_missing"]}

    quality = StrategyEvolutionService(db).assess_decay(
        parent_version_id=str(refs["parent_version_id"]),
        outcome_ids=outcome_ids,
        evidence_record_ids=[str(refs["evidence_record_id"])],
        now=NOW,
    )
    assert quality.classification == "data_quality"
    assert quality.status == "needs_review"

    with db.session() as session:
        outcome = session.get(StrategyOutcome, outcome_ids[-1])
        assert outcome is not None
        outcome.outcome_json = {
            **outcome.outcome_json,
            "data_gaps": [],
            "failure_class": "execution_slippage_drift",
        }
    execution = StrategyEvolutionService(db).assess_decay(
        parent_version_id=str(refs["parent_version_id"]),
        outcome_ids=outcome_ids,
        evidence_record_ids=[str(refs["evidence_record_id"])],
        now=NOW,
    )
    assert execution.classification == "execution_drift"
    assert execution.status == "actionable"
