"""Layered Cognitive Memory Service (FinMem & RD-Agent integration).

Implements:
1. Tier 1 Working Memory (WM): task-bounded turn context and token budgeting.
2. Tier 2 Episodic Memory (EM): concrete backtests, decays, and execution events with pgvector.
3. Tier 3 Semantic Memory (SM): distilled domain rules, causal invariants, and factor affinities.
4. Regime-aware retrieval ranking with cross-regime penalty and confidence-weighted scoring.
5. Hypothesis node recording and lifecycle status tracking for RD-Agent hypothesis trees.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError

from hypertrade.db import (
    ArcEpisodicMemory,
    ArcHypothesisNode,
    ArcSemanticAssertion,
    Database,
    new_id,
    utc_now,
)


class MutationType(StrEnum):
    INIT = "init"
    FEATURE_ADD = "feature_add"
    REGIME_ADAPT = "regime_adapt"
    LOGIC_INVERT = "logic_invert"
    PARAM_REFINE = "param_refine"
    DEFENSIVE_ADD = "defensive_add"


class HypothesisStatus(StrEnum):
    PROPOSED = "proposed"
    IMPLEMENTING = "implementing"
    TESTED = "tested"
    PRUNED = "pruned"
    PROMOTED = "promoted"


class HypothesisNodeV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    idempotency_key: str = ""
    tree_id: str
    parent_id: str | None = None
    depth: int = 0
    claim: str
    rationale: str = ""
    target_regimes: list[str] = Field(default_factory=list)
    mutation_type: MutationType = MutationType.INIT
    strategy_digest: str | None = None
    experiment_id: str | None = None
    benchmark_relative_pnl: Decimal | None = None
    sharpe_ratio: Decimal | None = None
    max_drawdown: Decimal | None = None
    ic_mean: Decimal | None = None
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    prune_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class EpisodicMemoryItemV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    idempotency_key: str = ""
    mission_id: str
    experiment_id: str | None = None
    symbols: list[str] = Field(default_factory=list)
    timeframe: str = ""
    market_regime: str = "unknown"
    event_type: str = "backtest_success"
    metrics_delta: dict[str, Any] = Field(default_factory=dict)
    raw_evidence_ref: str = ""
    reflection_summary: str
    embedding: list[float] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class SemanticMemoryAssertionV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    idempotency_key: str = ""
    assertion_type: str = "causal_heuristic"
    claim: str
    applicable_regimes: list[str] = Field(default_factory=list)
    confidence: Decimal = Field(default=Decimal("0.5000"), ge=0, le=1)
    derived_from_episodes: list[str] = Field(default_factory=list)
    counter_evidence_count: int = 0
    status: str = "active"
    replaced_by: str | None = None
    embedding: list[float] = Field(default_factory=list)
    version: int = 1
    evidence_set_hash: str | None = None
    distillation_version: str = "manual"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorkingMemoryStateV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str
    turn_id: str
    goal: str
    symbol: str
    timeframe: str
    current_regime: str = "unknown"
    budget_tokens: int = 4000
    recent_market_snapshot: dict[str, Any] = Field(default_factory=dict)
    active_hypotheses: list[HypothesisNodeV1] = Field(default_factory=list)
    retrieved_semantic_assertions: list[SemanticMemoryAssertionV1] = Field(default_factory=list)
    retrieved_episodic_memories: list[EpisodicMemoryItemV1] = Field(default_factory=list)
    chain_of_thought_buffer: list[str] = Field(default_factory=list)

    def format_prompt_context(self, max_tokens: int | None = None) -> str:
        """Format an information-dense prompt block adhering to token budget."""
        effective_budget = max_tokens or self.budget_tokens
        max_chars = effective_budget * 4  # heuristic approximation

        sections: list[str] = [
            f"=== WORKING MEMORY (Session: {self.session_id} | Turn: {self.turn_id}) ===",
            f"Target: {self.symbol} ({self.timeframe}) | Regime: {self.current_regime}",
            f"Research Goal: {self.goal}",
        ]

        if self.recent_market_snapshot:
            snapshot_repr = json.dumps(self.recent_market_snapshot, ensure_ascii=False)
            sections.append(f"Market Snapshot: {snapshot_repr}")

        if self.retrieved_semantic_assertions:
            sections.append("--- Semantic Knowledge & Invariants (Tier 3) ---")
            for sem_idx, sem_item in enumerate(self.retrieved_semantic_assertions, start=1):
                regimes = (
                    ",".join(sem_item.applicable_regimes)
                    if sem_item.applicable_regimes
                    else "All"
                )
                sections.append(
                    f"{sem_idx}. [{sem_item.assertion_type}] ({regimes}) "
                    f"Conf:{float(sem_item.confidence):.2f} - {sem_item.claim}"
                )

        if self.retrieved_episodic_memories:
            sections.append("--- Relevant Historical Episodic Precedents (Tier 2) ---")
            for ep_idx, ep_item in enumerate(self.retrieved_episodic_memories, start=1):
                summary = ep_item.reflection_summary
                prefix = f"{ep_idx}. [{ep_item.event_type} | {ep_item.market_regime}]"
                metrics = json.dumps(ep_item.metrics_delta, ensure_ascii=False, default=str)
                sections.append(
                    f"{prefix} id={ep_item.id} evidence={ep_item.raw_evidence_ref} "
                    f"metrics={metrics} {summary}"
                )

        if self.active_hypotheses:
            sections.append("--- Active Hypothesis Lineage ---")
            for idx, hyp in enumerate(self.active_hypotheses, start=1):
                sections.append(
                    f"{idx}. [{hyp.mutation_type}] Status:{hyp.status} - {hyp.claim}"
                )

        if self.chain_of_thought_buffer:
            sections.append("--- Reasoning Trace ---")
            for step in self.chain_of_thought_buffer:
                sections.append(f"- {step}")

        text = "\n".join(sections)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n... [Context truncated to token budget]"
        return text


def deterministic_embedding(content: str, *, dimensions: int = 64) -> list[float]:
    """Deterministic lexical feature hash for keyless bounded retrieval."""
    if not content:
        return [0.0] * dimensions
    raw = [0.0] * dimensions
    tokens = re.findall(r"[\w-]+", content.lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        raw[index] += sign
    norm = sum(val * val for val in raw) ** 0.5
    if norm == 0:
        return raw
    return [round(val / norm, 6) for val in raw]


def stable_memory_key(*parts: object, prefix: str = "mem") -> str:
    """Build a bounded deterministic idempotency key from canonical JSON values."""
    encoded = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()}"


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Calculate cosine similarity between two vector embeddings."""
    if not left or not right:
        return 0.0
    length = min(len(left), len(right))
    dot = sum(left[i] * right[i] for i in range(length))
    left_norm = sum(left[i] * left[i] for i in range(length)) ** 0.5
    right_norm = sum(right[i] * right[i] for i in range(length)) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return float(dot / (left_norm * right_norm))


def compute_regime_match_score(task_regime: str, memory_regimes: list[str]) -> float:
    """Calculate match score between current market regime and memory regime applicability.

    Returns:
        1.0 for exact regime match,
        0.8 for universal/all-weather rules,
        0.4 for compatible adjacent regime,
        -0.8 for conflicting regime (e.g. applying bull surge heuristics during bear crashes),
        0.0 otherwise.
    """
    clean_task = task_regime.strip().lower()
    if not memory_regimes or "all" in [r.lower() for r in memory_regimes]:
        return 0.8

    clean_memories = [r.strip().lower() for r in memory_regimes]
    if clean_task in clean_memories:
        return 1.0

    bull_group = {"bull_trend", "momentum_expansion", "bull_surge"}
    bear_group = {"bear_trend", "bear_crash", "capitulation", "extreme_down"}
    range_group = {"sideways_range", "low_volatility", "mean_reverting"}

    task_in_bull = clean_task in bull_group
    task_in_bear = clean_task in bear_group
    task_in_range = clean_task in range_group

    mem_in_bull = any(m in bull_group for m in clean_memories)
    mem_in_bear = any(m in bear_group for m in clean_memories)
    mem_in_range = any(m in range_group for m in clean_memories)

    # Contradictory polarities
    if (task_in_bull and mem_in_bear) or (task_in_bear and mem_in_bull):
        return -0.8
    if (
        (task_in_range and (mem_in_bull or mem_in_bear))
        or ((task_in_bull or task_in_bear) and mem_in_range)
    ):
        return -0.3

    # Compatible / same side
    if (
        (task_in_bull and mem_in_bull)
        or (task_in_bear and mem_in_bear)
        or (task_in_range and mem_in_range)
    ):
        return 0.4

    return 0.0


class LayeredMemoryService:
    """Orchestrates FinMem layered memory (WM, EM, SM) and RD-Agent hypotheses."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._working_memories: dict[str, WorkingMemoryStateV1] = {}

    # -------------------------------------------------------------------------
    # Tier 1: Working Memory (WM)
    # -------------------------------------------------------------------------
    def init_working_memory(
        self,
        *,
        session_id: str,
        turn_id: str,
        goal: str,
        symbol: str,
        timeframe: str,
        current_regime: str = "unknown",
        budget_tokens: int = 4000,
        recent_market_snapshot: dict[str, Any] | None = None,
    ) -> WorkingMemoryStateV1:
        wm = WorkingMemoryStateV1(
            session_id=session_id,
            turn_id=turn_id,
            goal=goal,
            symbol=symbol,
            timeframe=timeframe,
            current_regime=current_regime,
            budget_tokens=budget_tokens,
            recent_market_snapshot=recent_market_snapshot or {},
        )
        self._working_memories[session_id] = wm
        return wm

    def get_working_memory(self, session_id: str) -> WorkingMemoryStateV1 | None:
        return self._working_memories.get(session_id)

    def append_cot_step(self, session_id: str, step: str) -> None:
        wm = self._working_memories.get(session_id)
        if wm is not None:
            wm.chain_of_thought_buffer.append(step)

    def clear_working_memory(self, session_id: str) -> None:
        self._working_memories.pop(session_id, None)

    # -------------------------------------------------------------------------
    # Tier 2: Episodic Memory (EM)
    # -------------------------------------------------------------------------
    def record_episode(self, item: EpisodicMemoryItemV1) -> str:
        embedding = item.embedding or deterministic_embedding(item.reflection_summary)
        record_id = item.id or new_id("aepm")
        idempotency_key = item.idempotency_key or stable_memory_key(
            item.mission_id,
            item.experiment_id,
            item.event_type,
            item.raw_evidence_ref,
            prefix="episode",
        )

        try:
            with self.db.session() as session:
                existing = session.scalar(
                    select(ArcEpisodicMemory).where(
                        ArcEpisodicMemory.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    return existing.id
                db_item = ArcEpisodicMemory(
                    id=record_id,
                    mission_id=item.mission_id,
                    experiment_id=item.experiment_id,
                    idempotency_key=idempotency_key,
                    symbols_json=item.symbols,
                    timeframe=item.timeframe,
                    market_regime=item.market_regime,
                    event_type=item.event_type,
                    metrics_delta_json=item.metrics_delta,
                    raw_evidence_ref=item.raw_evidence_ref,
                    reflection_summary=item.reflection_summary,
                    embedding_json=embedding,
                    metadata_json=item.metadata,
                )
                session.add(db_item)
                session.flush()
        except IntegrityError:
            with self.db.session() as session:
                existing = session.scalar(
                    select(ArcEpisodicMemory).where(
                        ArcEpisodicMemory.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                return existing.id

        return record_id

    def get_episode(self, episode_id: str) -> EpisodicMemoryItemV1 | None:
        with self.db.session() as session:
            db_item = session.get(ArcEpisodicMemory, episode_id)
            if db_item is None:
                return None
            return self._db_to_episodic(db_item)

    def list_episodes(
        self,
        *,
        symbols: list[str] | None = None,
        timeframe: str | None = None,
        market_regime: str | None = None,
        limit: int = 50,
    ) -> list[EpisodicMemoryItemV1]:
        with self.db.session() as session:
            bounded_limit = max(1, min(limit, 200))
            scan_limit = min(1_000, bounded_limit * 10)
            stmt = (
                select(ArcEpisodicMemory)
                .order_by(desc(ArcEpisodicMemory.created_at))
                .limit(scan_limit)
            )
            if timeframe:
                stmt = stmt.where(ArcEpisodicMemory.timeframe == timeframe)
            if market_regime:
                stmt = stmt.where(ArcEpisodicMemory.market_regime == market_regime)

            records = session.scalars(stmt).all()
            results: list[EpisodicMemoryItemV1] = []
            for r in records:
                if symbols:
                    sym_set = set(symbols)
                    if not sym_set.intersection(set(r.symbols_json or [])):
                        continue
                if r.metadata_json and r.metadata_json.get("recall_eligible") is False:
                    continue
                results.append(self._db_to_episodic(r))
                if len(results) >= bounded_limit:
                    break
            return results

    # -------------------------------------------------------------------------
    # Tier 3: Semantic Memory (SM)
    # -------------------------------------------------------------------------
    def record_semantic_assertion(self, assertion: SemanticMemoryAssertionV1) -> str:
        embedding = assertion.embedding or deterministic_embedding(assertion.claim)
        record_id = assertion.id or new_id("asmt")
        idempotency_key = assertion.idempotency_key or stable_memory_key(
            assertion.claim,
            assertion.applicable_regimes,
            assertion.version,
            assertion.derived_from_episodes,
            prefix="semantic",
        )

        with self.db.session() as session:
            existing = session.scalar(
                select(ArcSemanticAssertion).where(
                    ArcSemanticAssertion.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                return existing.id
            db_item = ArcSemanticAssertion(
                id=record_id,
                idempotency_key=idempotency_key,
                assertion_type=assertion.assertion_type,
                claim=assertion.claim,
                applicable_regimes_json=assertion.applicable_regimes,
                confidence=assertion.confidence,
                derived_from_episodes_json=assertion.derived_from_episodes,
                counter_evidence_count=assertion.counter_evidence_count,
                status=assertion.status,
                replaced_by=assertion.replaced_by,
                embedding_json=embedding,
                version=assertion.version,
                evidence_set_hash=assertion.evidence_set_hash,
                distillation_version=assertion.distillation_version,
                metadata_json=assertion.metadata,
            )
            session.add(db_item)
            session.flush()

        return record_id

    def record_distilled_assertion(
        self,
        assertion: SemanticMemoryAssertionV1,
        *,
        evidence_set_hash: str,
        distillation_version: str,
        validated_contradiction_ids: list[str] | None = None,
    ) -> tuple[str, bool]:
        """Atomically record one evidence-version result and explicit contradictions.

        Similarity is retrieval evidence only. Existing rules are deprecated here
        solely when the summarizer supplied a separately validated contradiction id.
        """
        episode_ids = sorted(set(assertion.derived_from_episodes))
        idempotency_key = stable_memory_key(
            distillation_version,
            evidence_set_hash,
            prefix="distill",
        )
        embedding = assertion.embedding or deterministic_embedding(assertion.claim)
        try:
            with self.db.session() as session:
                existing = session.scalar(
                    select(ArcSemanticAssertion).where(
                        ArcSemanticAssertion.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    return existing.id, False
                record_id = assertion.id or new_id("asmt")
                session.add(
                    ArcSemanticAssertion(
                        id=record_id,
                        idempotency_key=idempotency_key,
                        assertion_type=assertion.assertion_type,
                        claim=assertion.claim,
                        applicable_regimes_json=assertion.applicable_regimes,
                        confidence=assertion.confidence,
                        derived_from_episodes_json=episode_ids,
                        counter_evidence_count=assertion.counter_evidence_count,
                        status=assertion.status,
                        replaced_by=assertion.replaced_by,
                        embedding_json=embedding,
                        version=assertion.version,
                        evidence_set_hash=evidence_set_hash,
                        distillation_version=distillation_version,
                        metadata_json=assertion.metadata,
                    )
                )
                session.flush()
                contradiction_ids = sorted(set(validated_contradiction_ids or []))
                if contradiction_ids:
                    rows = session.scalars(
                        select(ArcSemanticAssertion).where(
                            ArcSemanticAssertion.id.in_(contradiction_ids),
                            ArcSemanticAssertion.status == "active",
                        )
                    ).all()
                    for row in rows:
                        row.status = "deprecated"
                        row.replaced_by = record_id
                        metadata = dict(row.metadata_json or {})
                        metadata["deprecation_reason"] = (
                            f"validated_contradiction:{record_id}"
                        )
                        metadata["deprecated_at"] = utc_now().isoformat()
                        row.metadata_json = metadata
                session.flush()
                return record_id, True
        except IntegrityError:
            with self.db.session() as session:
                existing = session.scalar(
                    select(ArcSemanticAssertion).where(
                        ArcSemanticAssertion.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                return existing.id, False

    def get_distilled_assertion(
        self,
        *,
        evidence_set_hash: str,
        distillation_version: str,
    ) -> SemanticMemoryAssertionV1 | None:
        with self.db.session() as session:
            existing = session.scalar(
                select(ArcSemanticAssertion).where(
                    ArcSemanticAssertion.evidence_set_hash == evidence_set_hash,
                    ArcSemanticAssertion.distillation_version == distillation_version,
                )
            )
            return None if existing is None else self._db_to_semantic(existing)

    def get_semantic_assertion(self, assertion_id: str) -> SemanticMemoryAssertionV1 | None:
        with self.db.session() as session:
            db_item = session.get(ArcSemanticAssertion, assertion_id)
            if db_item is None:
                return None
            return self._db_to_semantic(db_item)

    def list_semantic_assertions(
        self, *, status: str = "active", limit: int = 50
    ) -> list[SemanticMemoryAssertionV1]:
        with self.db.session() as session:
            stmt = (
                select(ArcSemanticAssertion)
                .where(ArcSemanticAssertion.status == status)
                .order_by(desc(ArcSemanticAssertion.confidence))
                .limit(limit)
            )
            records = session.scalars(stmt).all()
            return [self._db_to_semantic(r) for r in records]

    def deprecate_semantic_assertion(
        self, assertion_id: str, *, replaced_by: str | None = None, reason: str = ""
    ) -> bool:
        with self.db.session() as session:
            db_item = session.get(ArcSemanticAssertion, assertion_id)
            if db_item is None:
                return False
            db_item.status = "deprecated"
            db_item.replaced_by = replaced_by
            meta = dict(db_item.metadata_json or {})
            meta["deprecation_reason"] = reason
            meta["deprecated_at"] = utc_now().isoformat()
            db_item.metadata_json = meta
            session.flush()
            return True

    def record_counter_evidence(
        self, assertion_id: str, *, penalty: Decimal = Decimal("0.05")
    ) -> bool:
        with self.db.session() as session:
            db_item = session.get(ArcSemanticAssertion, assertion_id)
            if db_item is None:
                return False
            db_item.counter_evidence_count += 1
            new_conf = max(Decimal("0.0500"), db_item.confidence - penalty)
            db_item.confidence = new_conf
            if db_item.counter_evidence_count >= 5 and new_conf <= Decimal("0.3000"):
                db_item.status = "disputed"
            session.flush()
            return True

    # -------------------------------------------------------------------------
    # RD-Agent: Hypothesis Node Operations
    # -------------------------------------------------------------------------
    def record_hypothesis(self, node: HypothesisNodeV1) -> str:
        record_id = node.id or new_id("hypo")
        idempotency_key = node.idempotency_key or stable_memory_key(
            node.tree_id,
            node.parent_id,
            node.claim,
            node.metadata.get("candidate_id"),
            prefix="hypothesis",
        )
        try:
            with self.db.session() as session:
                existing = session.scalar(
                    select(ArcHypothesisNode).where(
                        ArcHypothesisNode.idempotency_key == idempotency_key
                    )
                )
                if existing is not None:
                    return existing.id
                db_item = ArcHypothesisNode(
                    id=record_id,
                    tree_id=node.tree_id,
                    parent_id=node.parent_id,
                    idempotency_key=idempotency_key,
                    depth=node.depth,
                    claim=node.claim,
                    rationale=node.rationale,
                    target_regimes_json=node.target_regimes,
                    mutation_type=str(node.mutation_type),
                    strategy_digest=node.strategy_digest,
                    experiment_id=node.experiment_id,
                    benchmark_relative_pnl=node.benchmark_relative_pnl,
                    sharpe_ratio=node.sharpe_ratio,
                    max_drawdown=node.max_drawdown,
                    ic_mean=node.ic_mean,
                    status=str(node.status),
                    prune_reason=node.prune_reason,
                    metadata_json=node.metadata,
                )
                session.add(db_item)
                session.flush()
        except IntegrityError:
            with self.db.session() as session:
                existing = session.scalar(
                    select(ArcHypothesisNode).where(
                        ArcHypothesisNode.idempotency_key == idempotency_key
                    )
                )
                if existing is None:
                    raise
                return existing.id
        return record_id

    def get_hypothesis(self, node_id: str) -> HypothesisNodeV1 | None:
        with self.db.session() as session:
            db_item = session.get(ArcHypothesisNode, node_id)
            if db_item is None:
                return None
            return self._db_to_hypothesis(db_item)

    def list_hypotheses_for_tree(self, tree_id: str) -> list[HypothesisNodeV1]:
        with self.db.session() as session:
            stmt = (
                select(ArcHypothesisNode)
                .where(ArcHypothesisNode.tree_id == tree_id)
                .order_by(ArcHypothesisNode.depth, ArcHypothesisNode.created_at)
            )
            records = session.scalars(stmt).all()
            return [self._db_to_hypothesis(r) for r in records]

    def update_hypothesis_status(
        self,
        node_id: str,
        *,
        status: HypothesisStatus,
        prune_reason: str | None = None,
        relative_pnl: Decimal | None = None,
        sharpe: Decimal | None = None,
        strategy_digest: str | None = None,
        experiment_id: str | None = None,
    ) -> bool:
        with self.db.session() as session:
            db_item = session.get(ArcHypothesisNode, node_id)
            if db_item is None:
                return False
            db_item.status = str(status)
            if prune_reason is not None:
                db_item.prune_reason = prune_reason
            if relative_pnl is not None:
                db_item.benchmark_relative_pnl = relative_pnl
            if sharpe is not None:
                db_item.sharpe_ratio = sharpe
            if strategy_digest is not None:
                db_item.strategy_digest = strategy_digest
            if experiment_id is not None:
                db_item.experiment_id = experiment_id
            session.flush()
            return True

    # -------------------------------------------------------------------------
    # Regime-Aware Multi-Tier Unified Retrieval
    # -------------------------------------------------------------------------
    def retrieve_context_for_task(
        self,
        *,
        goal: str,
        symbol: str,
        timeframe: str,
        current_regime: str,
        query_embedding: list[float] | None = None,
        alpha: float = 0.4,
        beta: float = 0.4,
        gamma: float = 0.2,
        top_k_semantic: int = 5,
        top_k_episodic: int = 3,
    ) -> tuple[list[SemanticMemoryAssertionV1], list[EpisodicMemoryItemV1]]:
        """Retrieve relevant semantic assertions and episodic memories with regime scoring.

        Filters out items whose combined score is negative (e.g. cross-regime toxic heuristics).
        """
        task_emb = query_embedding or deterministic_embedding(f"{symbol} {timeframe} {goal}")

        # 1. Score Semantic Assertions
        active_semantics = self.list_semantic_assertions(status="active", limit=1_000)
        scored_semantics: list[tuple[float, SemanticMemoryAssertionV1]] = []
        for sem in active_semantics:
            scoped_symbols = sem.metadata.get("symbols") or []
            scoped_timeframe = str(sem.metadata.get("timeframe") or "")
            if scoped_symbols and symbol not in scoped_symbols:
                continue
            if scoped_timeframe and timeframe != scoped_timeframe:
                continue
            regime_score = compute_regime_match_score(current_regime, sem.applicable_regimes)
            if regime_score < 0:
                # Filter out polar opposite regime rules to prevent catastrophic misapplication
                continue
            sim = cosine_similarity(task_emb, sem.embedding)
            conf = float(sem.confidence)
            total_score = alpha * sim + beta * regime_score + gamma * conf
            if total_score > 0.0:
                scored_semantics.append((total_score, sem))

        scored_semantics.sort(key=lambda x: x[0], reverse=True)
        selected_semantics = [item for _, item in scored_semantics[:top_k_semantic]]

        # 2. Score Episodic Memories
        episodes = self.list_episodes(
            symbols=[symbol] if symbol else None,
            timeframe=timeframe or None,
            limit=100,
        )
        scored_episodes: list[tuple[float, EpisodicMemoryItemV1]] = []
        for ep in episodes:
            regime_score = compute_regime_match_score(current_regime, [ep.market_regime])
            if regime_score < 0:
                continue
            sim = cosine_similarity(task_emb, ep.embedding)
            total_score = alpha * sim + beta * regime_score + gamma * 0.5
            if total_score > 0.0:
                scored_episodes.append((total_score, ep))

        scored_episodes.sort(key=lambda x: x[0], reverse=True)
        selected_episodes = [item for _, item in scored_episodes[:top_k_episodic]]

        return selected_semantics, selected_episodes

    def populate_working_memory_for_task(
        self,
        *,
        session_id: str,
        turn_id: str,
        goal: str,
        symbol: str,
        timeframe: str,
        current_regime: str,
        budget_tokens: int = 4000,
        recent_market_snapshot: dict[str, Any] | None = None,
        tree_id: str | None = None,
    ) -> WorkingMemoryStateV1:
        """Populate working memory state with top-scored memories and active hypotheses."""
        wm = self.init_working_memory(
            session_id=session_id,
            turn_id=turn_id,
            goal=goal,
            symbol=symbol,
            timeframe=timeframe,
            current_regime=current_regime,
            budget_tokens=budget_tokens,
            recent_market_snapshot=recent_market_snapshot,
        )

        semantics, episodes = self.retrieve_context_for_task(
            goal=goal,
            symbol=symbol,
            timeframe=timeframe,
            current_regime=current_regime,
        )
        wm.retrieved_semantic_assertions = semantics
        wm.retrieved_episodic_memories = episodes

        if tree_id:
            wm.active_hypotheses = self.list_hypotheses_for_tree(tree_id)

        return wm

    # -------------------------------------------------------------------------
    # Internal DB Mappers
    # -------------------------------------------------------------------------
    @staticmethod
    def _db_to_episodic(item: ArcEpisodicMemory) -> EpisodicMemoryItemV1:
        return EpisodicMemoryItemV1(
            id=item.id,
            idempotency_key=item.idempotency_key,
            mission_id=item.mission_id,
            experiment_id=item.experiment_id,
            symbols=list(item.symbols_json or []),
            timeframe=item.timeframe,
            market_regime=item.market_regime,
            event_type=item.event_type,
            metrics_delta=dict(item.metrics_delta_json or {}),
            raw_evidence_ref=item.raw_evidence_ref,
            reflection_summary=item.reflection_summary,
            embedding=list(item.embedding_json or []),
            metadata=dict(item.metadata_json or {}),
            created_at=item.created_at,
        )

    @staticmethod
    def _db_to_semantic(item: ArcSemanticAssertion) -> SemanticMemoryAssertionV1:
        return SemanticMemoryAssertionV1(
            id=item.id,
            idempotency_key=item.idempotency_key,
            assertion_type=item.assertion_type,
            claim=item.claim,
            applicable_regimes=list(item.applicable_regimes_json or []),
            confidence=item.confidence,
            derived_from_episodes=list(item.derived_from_episodes_json or []),
            counter_evidence_count=item.counter_evidence_count,
            status=item.status,
            replaced_by=item.replaced_by,
            embedding=list(item.embedding_json or []),
            version=item.version,
            evidence_set_hash=item.evidence_set_hash,
            distillation_version=item.distillation_version,
            metadata=dict(item.metadata_json or {}),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    @staticmethod
    def _db_to_hypothesis(item: ArcHypothesisNode) -> HypothesisNodeV1:
        return HypothesisNodeV1(
            id=item.id,
            idempotency_key=item.idempotency_key,
            tree_id=item.tree_id,
            parent_id=item.parent_id,
            depth=item.depth,
            claim=item.claim,
            rationale=item.rationale,
            target_regimes=list(item.target_regimes_json or []),
            mutation_type=MutationType(item.mutation_type),
            strategy_digest=item.strategy_digest,
            experiment_id=item.experiment_id,
            benchmark_relative_pnl=item.benchmark_relative_pnl,
            sharpe_ratio=item.sharpe_ratio,
            max_drawdown=item.max_drawdown,
            ic_mean=item.ic_mean,
            status=HypothesisStatus(item.status),
            prune_reason=item.prune_reason,
            metadata=dict(item.metadata_json or {}),
            created_at=item.created_at,
        )
