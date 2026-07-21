from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypertrade.db import AgentMission, AgentToolCall, ResearchEvidence, StrategyOutcome
from hypertrade.research.outcome_ledger import StrategyOutcomeLedgerService
from outcome_fixtures import outcome_payload, seeded_db
from sqlalchemy import func, select


def test_settled_outcome_is_immutable_idempotent_and_replayable() -> None:
    db, refs = seeded_db()
    service = StrategyOutcomeLedgerService(db)

    first = service.append(outcome_payload(refs), actor="validator")
    replay = service.append(outcome_payload(refs), actor="validator")
    digest = service.replay_hash()

    assert first["schema_version"] == "strategy_outcome.v1"
    assert first["strategy_version_id"] == refs["version_id"]
    assert first["artifact_refs"] == ["bitpro:backtest:seed"]
    assert replay["id"] == first["id"] and replay["idempotent"] is True
    assert digest == service.replay_hash()
    with db.session() as session:
        assert session.scalar(select(func.count(StrategyOutcome.id))) == 1

    with pytest.raises(ValueError, match="bound to another payload"):
        service.append(outcome_payload(refs, metrics={"return_pct": "99"}), actor="validator")


def test_source_correction_appends_without_rewriting_prior_outcome() -> None:
    db, refs = seeded_db()
    service = StrategyOutcomeLedgerService(db)
    first = service.append(outcome_payload(refs), actor="validator")
    corrected = service.append(
        outcome_payload(
            refs,
            key="strategy-outcome-correction-001",
            corrects_id=first["id"],
            metrics={"return_pct": "4.1", "max_drawdown_pct": "2.2"},
        ),
        actor="source_reconciler",
    )

    assert corrected["id"] != first["id"]
    assert corrected["corrects_id"] == first["id"]
    assert service.get(first["id"])["content_hash"] == first["content_hash"]
    assert len(service.list(strategy_lineage_id=refs["lineage_id"])) == 2


def test_unsettled_or_invalid_sources_fail_closed() -> None:
    db, refs = seeded_db()
    service = StrategyOutcomeLedgerService(db)

    with db.session() as session:
        mission = session.get(AgentMission, refs["mission_id"])
        assert mission is not None
        mission.completion_proof_json = {
            **mission.completion_proof_json,
            "passed": False,
            "effect_unknown": True,
        }
    with pytest.raises(ValueError, match="CompletionProof"):
        service.append(outcome_payload(refs), actor="validator")

    db, refs = seeded_db()
    with db.session() as session:
        evidence = session.get(ResearchEvidence, refs["evidence_id"])
        assert evidence is not None
        evidence.valid_until = datetime(2026, 7, 15, tzinfo=UTC)
    with pytest.raises(ValueError, match="evidence"):
        StrategyOutcomeLedgerService(db).append(outcome_payload(refs), actor="validator")


def test_paper_outcome_requires_matching_settled_observation_window() -> None:
    db, refs = seeded_db()
    service = StrategyOutcomeLedgerService(db)
    paper = outcome_payload(
        refs,
        key="strategy-paper-outcome-001",
        outcome_type="paper_window_settled",
        experiment_execution_id="",
        observation_window_id=refs["window_id"],
        artifact_refs=["mission:artifact:seed"],
    )

    result = service.append(paper, actor="paper_observer")
    assert result["outcome_type"] == "paper_window_settled"
    assert result["observation_window_id"] == refs["window_id"]


def test_effect_unknown_tool_call_blocks_outcome_until_reconciled() -> None:
    db, refs = seeded_db()
    with db.session() as session:
        call = AgentToolCall(
            id="tcall_outcome_unknown",
            intent_id="dint_outcome_unknown",
            mission_id=refs["mission_id"],
            capability_id="isolated.outcome.fixture",
            status="effect_unknown",
            call_json={"reconciliation_outcome": "unknown"},
        )
        session.add(call)

    service = StrategyOutcomeLedgerService(db)
    with pytest.raises(ValueError, match="unknown or unfinished effect"):
        service.append(
            outcome_payload(refs, tool_call_ids=["tcall_outcome_unknown"]),
            actor="validator",
        )

    with db.session() as session:
        call = session.get(AgentToolCall, "tcall_outcome_unknown")
        assert call is not None
        call.status = "reconciled"
        call.call_json = {"reconciliation_outcome": "committed"}
    result = service.append(
        outcome_payload(
            refs,
            key="strategy-outcome-reconciled-001",
            tool_call_ids=["tcall_outcome_unknown"],
        ),
        actor="validator",
    )
    assert result["tool_call_ids"] == ["tcall_outcome_unknown"]


def test_raw_or_live_outcomes_are_rejected_by_contract() -> None:
    _, refs = seeded_db()
    with pytest.raises(ValueError, match="reserved"):
        outcome_payload(refs, outcome_type="live_window_settled")
    with pytest.raises(ValueError, match="sensitive or raw"):
        outcome_payload(refs, metrics={"orders": "raw"})
