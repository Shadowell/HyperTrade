from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from evolution_fixtures import NOW, evolution_request, seeded_evolution_db
from hypertrade.db import (
    AgentToolCall,
    BitProStrategyEvidenceRecord,
    ExperimentManifest,
    StrategyEvolutionCandidate,
)
from hypertrade.research.evolution import StrategyEvolutionService
from hypertrade.research.evolution_schemas import CandidateProposalV1
from sqlalchemy import func, select


def test_engine_accepts_bounded_candidate_and_ledgers_rejections_without_dispatch() -> None:
    db, refs = seeded_evolution_db()
    proposals = [
        CandidateProposalV1(
            proposal_kind="parameter",
            parameter_changes={"fast": Decimal("8")},
            proposal_reason="Reduce lag after settled performance decay.",
        ),
        CandidateProposalV1(
            proposal_kind="parameter",
            parameter_changes={"fast": Decimal("99")},
            proposal_reason="Intentionally invalid range probe.",
        ),
    ]
    result = StrategyEvolutionService(db).evolve(
        evolution_request(refs, proposals=proposals), actor="evolution-test", now=NOW
    )

    assert result["status"] == "candidates_registered"
    assert [item["status"] for item in result["candidates"]] == ["accepted", "rejected"]
    assert result["candidates"][1]["rejection_reasons"] == ["parameter_out_of_bounds:fast"]
    assert result["usage"]["accepted"] == 1
    assert result["execution_authorized"] is False
    assert not any(result["mutation_boundary"].values())
    with db.session() as session:
        assert session.scalar(select(func.count(StrategyEvolutionCandidate.id))) == 2
        assert session.scalar(select(func.count(ExperimentManifest.id))) == 2
        assert session.scalar(select(func.count(AgentToolCall.id))) == 0


def test_budget_exhaustion_stops_generation_and_is_auditable() -> None:
    db, refs = seeded_evolution_db()
    proposals = [
        CandidateProposalV1(
            proposal_kind="parameter",
            parameter_changes={"fast": Decimal("8")},
            proposal_reason="Consumes the only allowed model call.",
            model_calls=1,
        ),
        CandidateProposalV1(
            proposal_kind="parameter",
            parameter_changes={"fast": Decimal("9")},
            proposal_reason="Must stop at the model-call budget.",
            model_calls=1,
        ),
    ]
    result = StrategyEvolutionService(db).evolve(
        evolution_request(refs, proposals=proposals, max_model_calls=1),
        actor="evolution-test",
        now=NOW,
    )

    assert result["usage"]["accepted"] == 1
    assert result["usage"]["trials"] == 1
    assert result["candidates"][-1]["status"] == "budget_exhausted"
    assert result["candidates"][-1]["rejection_reasons"] == ["max_model_calls_exhausted"]


def test_stale_evidence_and_scope_expansion_fail_before_candidate_generation() -> None:
    db, refs = seeded_evolution_db()
    with db.session() as session:
        evidence = session.get(BitProStrategyEvidenceRecord, refs["evidence_record_id"])
        assert evidence is not None
        evidence.created_at = NOW - timedelta(days=2)
    with pytest.raises(ValueError, match="stale"):
        StrategyEvolutionService(db).evolve(
            evolution_request(refs), actor="evolution-test", now=NOW
        )

    db, refs = seeded_evolution_db()
    with pytest.raises(ValueError, match="expand strategy symbols"):
        StrategyEvolutionService(db).evolve(
            evolution_request(refs, symbols=["BTC-USDT-SWAP", "ETH-USDT-SWAP"]),
            actor="evolution-test",
            now=NOW,
        )


def test_evolution_module_has_no_execution_adapter_imports() -> None:
    source = (
        Path(__file__).parents[1] / "backend" / "src" / "hypertrade" / "research" / "evolution.py"
    ).read_text(encoding="utf-8")
    assert "hypertrade.bitpro" not in source
    assert "hypertrade.paper" not in source
    assert "hypertrade.live" not in source
    assert "live_order" not in source
    assert "capital_allocation" not in source
