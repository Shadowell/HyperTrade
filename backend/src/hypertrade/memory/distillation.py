"""Episodic-to-Semantic Memory Distillation Service (FinMem integration).

Implements:
1. Clustering recurrent episodic failure / decay precedents into generalized rules.
2. Causal attribution extraction from recurring episodes.
3. Contradiction detection and automated deprecation of outdated assertions.
4. Promotion to Tier 3 Semantic Memory assertions.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from hypertrade.memory.layered_service import (
    EpisodicMemoryItemV1,
    LayeredMemoryService,
    SemanticMemoryAssertionV1,
    cosine_similarity,
    deterministic_embedding,
)


class MemoryDistillationService:
    """Distills recurring episodic experiences into persistent semantic assertions."""

    def __init__(self, memory_service: LayeredMemoryService) -> None:
        self.memory_service = memory_service

    def distill_episodes_for_regime(
        self,
        *,
        market_regime: str,
        event_types: list[str] | None = None,
        min_episode_count: int = 3,
        similarity_threshold: float = 0.70,
        causal_summarizer: (
            Callable[[list[EpisodicMemoryItemV1]], tuple[str, str, Decimal]] | None
        ) = None,
    ) -> SemanticMemoryAssertionV1 | None:
        """Scan episodic memories for recurrent patterns and distill into semantic assertions."""
        target_events = set(event_types or ["paper_decay", "backtest_overfit", "redteam_falsified"])
        episodes = self.memory_service.list_episodes(market_regime=market_regime, limit=100)

        qualifying = [ep for ep in episodes if ep.event_type in target_events]
        if len(qualifying) < min_episode_count:
            return None

        # 1. Summarize episodes into a general causal claim
        if causal_summarizer is not None:
            claim, assertion_type, confidence = causal_summarizer(qualifying)
        else:
            claim = (
                f"Recurrent {target_events} observed across {len(qualifying)} episodes in "
                f"{market_regime}: requires stricter trailing stop and defensive position sizing."
            )
            assertion_type = "structural_constraint"
            confidence = Decimal("0.8500")

        new_emb = deterministic_embedding(claim)
        episode_ids = [ep.id for ep in qualifying if ep.id]

        # 2. Contradiction & conflict resolution against existing active semantic assertions
        active_semantics = self.memory_service.list_semantic_assertions(status="active")
        superseded_ids: list[str] = []

        for existing in active_semantics:
            if existing.id is None:
                continue
            sim = cosine_similarity(new_emb, existing.embedding)
            # If high semantic relevance and applies to same regime
            if sim >= similarity_threshold and (
                not existing.applicable_regimes or market_regime in existing.applicable_regimes
            ):
                superseded_ids.append(existing.id)

        # 3. Create and record new semantic assertion
        new_assertion = SemanticMemoryAssertionV1(
            assertion_type=assertion_type,
            claim=claim,
            applicable_regimes=[market_regime],
            confidence=confidence,
            derived_from_episodes=episode_ids,
            counter_evidence_count=0,
            status="active",
        )
        new_id = self.memory_service.record_semantic_assertion(new_assertion)
        new_assertion.id = new_id

        # 4. Deprecate superseded older assertions
        for old_id in superseded_ids:
            self.memory_service.deprecate_semantic_assertion(
                old_id,
                replaced_by=new_id,
                reason=f"Superseded by distilled rule {new_id} based on {len(qualifying)} episodes",
            )

        return new_assertion
