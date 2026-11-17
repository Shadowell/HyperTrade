"""Evidence-versioned episodic-to-semantic memory distillation."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from decimal import Decimal
from threading import Lock
from typing import Any

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
DEFAULT_DISTILLABLE_EVENT_TYPES = (
    "paper_decay",
    "backtest_overfit",
    "backtest_rejected",
    "redteam_falsified",
    "backtest_success",
    "paper_race_won",
    "paper_race_lost",
)
_METRIC_SUMMARY_KEYS = (
    "sharpe",
    "sharpe_ratio",
    "relative_pnl",
    "benchmark_relative_pnl",
    "excess_return_pct",
    "challenger_net_return_pct",
    "parent_net_return_pct",
    "total_return_pct",
    "net_return_pct",
    "max_drawdown",
    "max_drawdown_pct",
    "challenger_max_drawdown_pct",
    "observed_hours",
    "sign_test_p",
)


def _finite_metric_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float, Decimal)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def deterministic_causal_summarizer(
    episodes: list[EpisodicMemoryItemV1],
) -> tuple[str, str, Decimal] | None:
    """Summarize >= 2 audited episodes into a conservative descriptive causal heuristic."""
    audited = [
        ep
        for ep in episodes
        if (ep.metadata or {}).get("recall_eligible") is not False
    ]
    if len(audited) < 2:
        return None

    symbols = sorted({sym.strip() for ep in audited for sym in ep.symbols if sym and sym.strip()})
    timeframes = sorted(
        {ep.timeframe.strip() for ep in audited if ep.timeframe and ep.timeframe.strip()}
    )
    regimes = sorted(
        {
            ep.market_regime.strip()
            for ep in audited
            if ep.market_regime and ep.market_regime.strip()
        }
    )
    counts = Counter(ep.event_type for ep in audited if ep.event_type)

    ordered_count_keys = [
        "backtest_success",
        "backtest_rejected",
        "paper_race_won",
        "paper_race_lost",
    ]
    extra_count_keys = sorted(k for k in counts if k not in ordered_count_keys)
    count_parts = [
        f"{key}={counts[key]}"
        for key in (*ordered_count_keys, *extra_count_keys)
        if counts.get(key, 0) > 0
    ]

    metric_values: dict[str, list[float]] = {key: [] for key in _METRIC_SUMMARY_KEYS}
    for ep in audited:
        metrics = ep.metrics_delta or {}
        for key in _METRIC_SUMMARY_KEYS:
            val = _finite_metric_number(metrics.get(key))
            if val is not None:
                metric_values[key].append(val)
        if (
            _finite_metric_number(metrics.get("sharpe")) is None
            and _finite_metric_number(metrics.get("sharpe_ratio")) is None
        ):
            ret_stats = metrics.get("return_statistics")
            if isinstance(ret_stats, dict):
                period_sharpe = _finite_metric_number(ret_stats.get("period_sharpe"))
                if period_sharpe is not None:
                    metric_values["sharpe"].append(period_sharpe)

    metric_parts: list[str] = []
    for key in _METRIC_SUMMARY_KEYS:
        vals = metric_values[key]
        if not vals:
            continue
        med = statistics.median(vals)
        avg = statistics.fmean(vals)
        metric_parts.append(f"{key} median={med:.4g} mean={avg:.4g} (n={len(vals)})")
        if len(metric_parts) >= 5:
            break

    sym_text = ", ".join(symbols) if symbols else "unspecified"
    tf_text = ", ".join(timeframes) if timeframes else "unspecified"
    regime_text = ", ".join(regimes) if regimes else "unknown"
    outcome_text = ", ".join(count_parts) if count_parts else f"episodes={len(audited)}"
    metrics_text = f"; metrics: {', '.join(metric_parts)}" if metric_parts else ""
    claim = (
        f"Observed {len(audited)} audited episodes for {sym_text} "
        f"({tf_text}, regime={regime_text}): {outcome_text}{metrics_text}. "
        "Descriptive historical aggregate only; revalidate out-of-sample."
    )
    confidence = min(
        Decimal("0.8000"),
        Decimal("0.5500") + Decimal("0.0300") * (len(audited) - 2),
    )
    return claim, "causal_heuristic", confidence


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
        target_events = set(event_types or DEFAULT_DISTILLABLE_EVENT_TYPES)
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
    min_episode_count: int = 2,
    event_types: list[str] | None = None,
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
            if (row.metadata_json or {}).get("recall_eligible") is not False
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
                event_types=event_types,
                min_episode_count=min_episode_count,
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
