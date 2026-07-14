"""Read-only projections for pre-V2 research evidence and Memory records."""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, select

from hypertrade.db import Database, MemoryItem, ResearchExperimentEvidence
from hypertrade.strategy.evidence import parse_strategy_evidence


class LegacyEvidenceAdapter:
    """Expose legacy records without rewriting them as source-verified V2 facts."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, evidence_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            if evidence_id.startswith("rexp_"):
                row = session.get(ResearchExperimentEvidence, evidence_id)
                if row is not None:
                    return _experiment_to_dict(row)
            if evidence_id.startswith("mem_"):
                memory = session.get(MemoryItem, evidence_id)
                if memory is not None:
                    return _memory_to_dict(memory)
        raise KeyError(evidence_id)

    def query(self, *, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 200))
        with self.db.session() as session:
            experiments = session.scalars(
                select(ResearchExperimentEvidence)
                .order_by(desc(ResearchExperimentEvidence.created_at))
                .limit(bounded)
            ).all()
            memories = session.scalars(
                select(MemoryItem)
                .where(MemoryItem.disabled.is_(False))
                .order_by(desc(MemoryItem.created_at))
                .limit(bounded)
            ).all()
            rows = [_experiment_to_dict(row) for row in experiments]
            rows.extend(_memory_to_dict(row) for row in memories)
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)[:bounded]


def _experiment_to_dict(row: ResearchExperimentEvidence) -> dict[str, Any]:
    return {
        "id": row.id,
        "schema_version": "research_experiment_evidence.legacy.v1",
        "evidence_type": "legacy_experiment",
        "status": row.status,
        "claim": f"Legacy BitPro experiment evidence for {row.strategy_key}",
        "scope": {
            "mandate_id": row.mandate_id,
            "strategy_key": row.strategy_key,
            "symbols": [],
            "timeframes": [],
            "market_type": "",
        },
        "sources": [
            {
                "source_type": "bitpro_result",
                "source_id": row.bitpro_strategy_id or row.id,
                "availability": "unknown",
            }
        ],
        "confidence": None,
        "task_id": "",
        "node_run_id": "",
        "role_key": "legacy_research_orchestrator",
        "payload": {
            "job_id": row.job_id,
            "variant_id": row.variant_id,
            "result_refs": dict(row.result_refs_json),
            "windows": dict(row.windows_json),
            "parameters": dict(row.parameters_json),
            "metrics": dict(row.metrics_json),
            "gate_results": dict(row.gate_results_json),
            "rejection_reasons": list(row.rejection_reasons_json),
        },
        "legacy": True,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "warning": "Legacy evidence was not rewritten or promoted to a V2 fact.",
    }


def _memory_to_dict(row: MemoryItem) -> dict[str, Any]:
    strategy = parse_strategy_evidence(row.content)
    payload: dict[str, Any] = {
        "memory_kind": row.kind,
        "source_run_id": row.source_run_id,
        "source_tool": row.source_tool,
        "importance": str(row.importance),
        "usage_count": row.usage_count,
        "tags": list(row.tags),
    }
    if strategy is not None:
        payload["strategy_evidence"] = strategy.to_dict()
        claim = f"Legacy StrategyEvidence for {strategy.strategy_key}"
        schema_version = strategy.schema_version
        evidence_type = "legacy_strategy_evidence"
    else:
        claim = f"Legacy Memory reference {row.id} ({row.kind})"
        schema_version = "memory.legacy.v1"
        evidence_type = "legacy_memory"
    return {
        "id": row.id,
        "schema_version": schema_version,
        "evidence_type": evidence_type,
        "status": "disabled" if row.disabled else "active",
        "claim": claim,
        "scope": {"symbols": [], "timeframes": [], "market_type": ""},
        "sources": [
            {
                "source_type": "memory",
                "source_id": row.id,
                "availability": "unavailable" if row.disabled else "available",
            }
        ],
        "confidence": str(row.confidence),
        "task_id": "",
        "node_run_id": "",
        "role_key": "legacy_memory_adapter",
        "payload": payload,
        "legacy": True,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "warning": "Memory is context, not an independently verified market fact.",
    }
