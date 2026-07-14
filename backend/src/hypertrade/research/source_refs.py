"""Bounded adapters from existing artifacts to Evidence V2 source references."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from hypertrade.db import MemoryItem, ResearchExperimentEvidence, TraceEvent
from hypertrade.rag.service import RagHit
from hypertrade.research.evidence_schemas import EvidenceSourceRef


def source_ref_from_trace(event: TraceEvent) -> EvidenceSourceRef:
    return EvidenceSourceRef(
        source_type="tool",
        source_id=event.id,
        tool_name=event.tool_name,
        observed_at=_aware(event.created_at),
        content_hash=_digest(
            {
                "run_id": event.run_id,
                "tool_name": event.tool_name,
                "status": event.status,
                "input": event.input_json,
                "output": event.output_json,
            }
        ),
        availability="available" if event.status == "completed" else "unavailable",
    )


def source_ref_from_rag_hit(hit: RagHit, *, observed_at: datetime) -> EvidenceSourceRef:
    return EvidenceSourceRef(
        source_type="rag",
        source_id=f"{hit.source_path}#{hit.chunk_index}",
        observed_at=_aware(observed_at),
        content_hash=_digest({"source_path": hit.source_path, "content": hit.content}),
    )


def source_ref_from_memory(memory: MemoryItem) -> EvidenceSourceRef:
    return EvidenceSourceRef(
        source_type="memory",
        source_id=memory.id,
        tool_name=memory.source_tool,
        observed_at=_aware(memory.created_at),
        content_hash=_digest({"kind": memory.kind, "content": memory.content}),
        availability="unavailable" if memory.disabled else "available",
    )


def source_ref_from_bitpro_result(
    *, result_id: str, result_projection: dict[str, Any], observed_at: datetime
) -> EvidenceSourceRef:
    return EvidenceSourceRef(
        source_type="bitpro_result",
        source_id=result_id,
        observed_at=_aware(observed_at),
        content_hash=_digest(result_projection),
    )


def source_ref_from_paper_snapshot(
    *, snapshot_id: str, snapshot_projection: dict[str, Any], observed_at: datetime
) -> EvidenceSourceRef:
    return source_ref_from_snapshot(
        snapshot_id=snapshot_id,
        snapshot_projection=snapshot_projection,
        observed_at=observed_at,
    )


def source_ref_from_snapshot(
    *, snapshot_id: str, snapshot_projection: dict[str, Any], observed_at: datetime
) -> EvidenceSourceRef:
    return EvidenceSourceRef(
        source_type="snapshot",
        source_id=snapshot_id,
        observed_at=_aware(observed_at),
        content_hash=_digest(snapshot_projection),
    )


def source_refs_from_experiment(
    evidence: ResearchExperimentEvidence,
) -> list[EvidenceSourceRef]:
    refs: list[EvidenceSourceRef] = []
    for window, raw_ref in sorted(dict(evidence.result_refs_json).items()):
        ref = dict(raw_ref) if isinstance(raw_ref, dict) else {}
        result_id = str(ref.get("result_id", "")).strip()
        if not result_id:
            continue
        refs.append(
            source_ref_from_bitpro_result(
                result_id=result_id,
                result_projection={
                    "window": window,
                    "job_id": str(ref.get("job_id", "")),
                    "metrics": dict(evidence.metrics_json).get(window, {}),
                },
                observed_at=evidence.created_at,
            )
        )
    return refs


def _digest(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
