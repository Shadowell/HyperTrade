"""Evidence-versioned episodic-to-semantic memory distillation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from decimal import Decimal
from threading import Lock

from sqlalchemy import select, text

from hypertrade.db import ArcEpisodicMemory, Database
from hypertrade.memory.layered_service import (
    EpisodicMemoryItemV1,
    LayeredMemoryService,
    SemanticMemoryAssertionV1,
    deterministic_embedding,
)

CausalSummarizer = Callable[
    [list[EpisodicMemoryItemV1]],
    tuple[str, str, Decimal] | None,
]


class DistillationBudgetExhausted(RuntimeError):
    """The configured per-pass provider-call budget has been consumed."""


_DISTILL_LOCKS: dict[str, Lock] = {}
_DISTILL_LOCK_GUARD = Lock()
_SCOPE_CURSOR = 0


class MemoryDistillationService:
    """Distill audited episodes without inventing a fallback causal rule."""

    def __init__(self, memory_service: LayeredMemoryService) -> None:
        self.memory_service = memory_service

    def distill_episodes_for_regime(
        self,
        *,
        market_regime: str,
        symbols: list[str] | None = None,
        timeframe: str | None = None,
        event_types: list[str] | None = None,
        min_episode_count: int = 3,
        similarity_threshold: float = 0.70,
        summarizer_version: str = "causal-v1",
        validated_contradiction_ids: list[str] | None = None,
        causal_summarizer: CausalSummarizer | None = None,
    ) -> SemanticMemoryAssertionV1 | None:
        """Distill a stable evidence set once for one summarizer version.

        ``similarity_threshold`` remains accepted for caller compatibility, but
        similarity never proves contradiction and therefore cannot deprecate a rule.
        """
        del similarity_threshold
        target_events = set(
            event_types
            or ["paper_decay", "backtest_overfit", "backtest_rejected", "redteam_falsified"]
        )
        episodes = self.memory_service.list_episodes(
            symbols=symbols,
            timeframe=timeframe,
            market_regime=market_regime,
            limit=20,
        )
        qualifying = [ep for ep in episodes if ep.event_type in target_events]
        if len(qualifying) < min_episode_count or causal_summarizer is None:
            return None
        episode_ids = sorted(ep.id for ep in qualifying if ep.id)
        if len(episode_ids) < min_episode_count:
            return None
        evidence_set_hash = hashlib.sha256(
            json.dumps(episode_ids, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        lock_key = f"{summarizer_version}:{evidence_set_hash}"
        with _distillation_lock(self.memory_service.db, lock_key) as acquired:
            if not acquired:
                return None
            existing = self.memory_service.get_distilled_assertion(
                evidence_set_hash=evidence_set_hash,
                distillation_version=summarizer_version,
            )
            if existing is not None:
                return existing if existing.status == "active" else None
            summary = causal_summarizer(qualifying)
            if summary is None:
                tombstone = SemanticMemoryAssertionV1(
                    assertion_type="distillation_tombstone",
                    claim="No causal assertion was produced for this audited evidence set.",
                    applicable_regimes=[market_regime],
                    confidence=Decimal("0"),
                    derived_from_episodes=episode_ids,
                    status="unknown",
                    evidence_set_hash=evidence_set_hash,
                    distillation_version=summarizer_version,
                    metadata={
                        "symbols": sorted(set(symbols or [])),
                        "timeframe": timeframe or "",
                        "reason": "summarizer_unknown",
                    },
                )
                self.memory_service.record_distilled_assertion(
                    tombstone,
                    evidence_set_hash=evidence_set_hash,
                    distillation_version=summarizer_version,
                )
                return None
            claim, assertion_type, confidence = summary
            claim = claim.strip()
            assertion_type = assertion_type.strip()
            if not claim or not assertion_type:
                return None
            confidence = max(Decimal("0"), min(Decimal("1"), confidence))
            return self._record_summary(
                claim=claim,
                assertion_type=assertion_type,
                confidence=confidence,
                market_regime=market_regime,
                symbols=symbols,
                timeframe=timeframe,
                episode_ids=episode_ids,
                evidence_set_hash=evidence_set_hash,
                summarizer_version=summarizer_version,
                validated_contradiction_ids=validated_contradiction_ids,
            )

    def _record_summary(
        self,
        *,
        claim: str,
        assertion_type: str,
        confidence: Decimal,
        market_regime: str,
        symbols: list[str] | None,
        timeframe: str | None,
        episode_ids: list[str],
        evidence_set_hash: str,
        summarizer_version: str,
        validated_contradiction_ids: list[str] | None,
    ) -> SemanticMemoryAssertionV1:
        assertion = SemanticMemoryAssertionV1(
            assertion_type=assertion_type,
            claim=claim,
            applicable_regimes=[market_regime],
            confidence=confidence,
            derived_from_episodes=episode_ids,
            status="active",
            embedding=deterministic_embedding(claim),
            evidence_set_hash=evidence_set_hash,
            distillation_version=summarizer_version,
            metadata={
                "symbols": sorted(set(symbols or [])),
                "timeframe": timeframe or "",
            },
        )
        assertion_id, _created = self.memory_service.record_distilled_assertion(
            assertion,
            evidence_set_hash=evidence_set_hash,
            distillation_version=summarizer_version,
            validated_contradiction_ids=validated_contradiction_ids,
        )
        stored = self.memory_service.get_semantic_assertion(assertion_id)
        if stored is not None:
            return stored
        assertion.id = assertion_id
        return assertion


def distill_pending_regimes(
    db: Database,
    *,
    causal_summarizer: CausalSummarizer | None,
    summarizer_version: str,
) -> dict[str, object]:
    """Run one bounded, restart-safe worker pass across observed regimes."""
    if causal_summarizer is None:
        return {"status": "skipped", "reason": "causal_summarizer_unavailable", "ids": []}
    with db.session() as session:
        rows = session.scalars(
            select(ArcEpisodicMemory)
            .order_by(ArcEpisodicMemory.created_at.desc())
            .limit(1_000)
        ).all()
    all_scopes = sorted(
        {
            (str(row.market_regime), str(row.timeframe), str(symbol))
            for row in rows
            if row.metadata_json.get("recall_eligible") is not False
            for symbol in (row.symbols_json or [])
            if row.market_regime and row.timeframe and symbol
        }
    )
    global _SCOPE_CURSOR
    if all_scopes:
        start = _SCOPE_CURSOR % len(all_scopes)
        scopes = (all_scopes[start:] + all_scopes[:start])[:100]
        _SCOPE_CURSOR = (start + len(scopes)) % len(all_scopes)
    else:
        scopes = []
    service = MemoryDistillationService(LayeredMemoryService(db))
    assertion_ids: list[str] = []
    for regime, timeframe, symbol in scopes:
        try:
            assertion = service.distill_episodes_for_regime(
                market_regime=regime,
                symbols=[symbol],
                timeframe=timeframe,
                summarizer_version=summarizer_version,
                causal_summarizer=causal_summarizer,
            )
        except DistillationBudgetExhausted:
            break
        if assertion is not None and assertion.id is not None:
            assertion_ids.append(assertion.id)
    return {"status": "completed", "scopes": scopes, "ids": assertion_ids}


@contextmanager
def _distillation_lock(db: Database, key: str) -> Iterator[bool]:
    """Serialize one evidence/version model call across processes where supported."""
    if db.engine.dialect.name == "postgresql":
        advisory_key = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big", signed=True)
        with db.engine.connect() as connection:
            acquired = bool(
                connection.execute(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": advisory_key}
                ).scalar()
            )
            connection.commit()
            try:
                yield acquired
            finally:
                if acquired:
                    with suppress(Exception):
                        connection.execute(
                            text("SELECT pg_advisory_unlock(:key)"), {"key": advisory_key}
                        )
                        connection.commit()
        return
    with _DISTILL_LOCK_GUARD:
        lock = _DISTILL_LOCKS.setdefault(key, Lock())
    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
