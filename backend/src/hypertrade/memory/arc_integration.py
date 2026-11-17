"""Idempotent projection adapter from the canonical ARC journal to cognitive memory."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import Lock
from typing import Any, cast

from sqlalchemy import String, select
from sqlalchemy import cast as sql_cast

from hypertrade.arc.store import (
    MISSIONS,
    committed_revisions,
    get_configured_database,
    is_parked,
    list_mission_ids,
    park,
    peek_controller_events,
)
from hypertrade.db import (
    ArcEpisodicMemory,
    ArcHypothesisNode,
    ArcSemanticAssertion,
    Database,
    MemoryItem,
)
from hypertrade.memory.distillation import (
    deterministic_causal_summarizer,
    distill_pending_regimes,
)
from hypertrade.memory.layered_service import (
    EpisodicMemoryItemV1,
    HypothesisNodeV1,
    HypothesisStatus,
    LayeredMemoryService,
    MutationType,
    WorkingMemoryStateV1,
    stable_memory_key,
)
from hypertrade.memory.service import MemoryService

logger = logging.getLogger(__name__)
_REPLAY_CURSOR = 0
_REPLAY_CURSOR_LOCK = Lock()
_EPISODE_EVENT_TYPES = (
    "red_team_tested",
    "avo_development_result",
    "bitpro_self_tested",
)
_MAX_UNRESIDENT_REPLAYS_PER_ROUND = 10


@dataclass(frozen=True)
class CognitiveSyncResult:
    status: str
    prompt_context: str = ""
    hypotheses_recorded: int = 0
    episodes_recorded: int = 0


def sync_arc_cognitive_memory(
    controller: Any,
    *,
    max_prompt_tokens: int = 600,
) -> CognitiveSyncResult:
    """Sync one controller through the configured ARC database.

    Unit tests that intentionally use the in-memory ARC store can run without a
    configured database. A configured-but-unmigrated production database is an
    error and is deliberately not converted into an empty memory result.
    """
    database = get_configured_database()
    if database is None:
        return CognitiveSyncResult(status="unavailable")
    try:
        return ingest_projection(
            database,
            str(controller.mission_id),
            controller.projection,
            max_prompt_tokens=max_prompt_tokens,
        )
    except Exception:
        logger.exception(
            "ARC cognitive-memory sync failed mission_id=%s", controller.mission_id
        )
        raise


def ingest_projection(
    db: Database,
    mission_id: str,
    projection: Any,
    *,
    max_prompt_tokens: int = 600,
) -> CognitiveSyncResult:
    """Replay durable ARC facts into HET/episodes and return bounded task recall."""
    memory = LayeredMemoryService(db)
    goal = getattr(projection, "goal", None)
    if goal is None:
        return CognitiveSyncResult(status="no_goal")
    symbols = [str(value) for value in (getattr(goal, "symbols", None) or []) if value]
    timeframes = [
        str(value) for value in (getattr(goal, "timeframes", None) or []) if value
    ]
    symbol = symbols[0] if symbols else ""
    timeframe = timeframes[0] if timeframes else ""
    regime = _market_regime(goal)
    tree_id = f"arc:{mission_id}"
    lineage_key = _lineage_key(goal)

    attempts = list(getattr(projection, "attempts", None) or [])
    hypothesis_ids: dict[str, str] = {}
    hypotheses_recorded = 0
    for attempt in attempts:
        candidate_id = str(getattr(attempt, "candidate_id", "") or "")
        attempt_id = str(getattr(attempt, "attempt_id", "") or "")
        if not candidate_id or not attempt_id:
            continue
        claim = str(getattr(attempt, "hypothesis", "") or "").strip()
        if not claim:
            continue
        strategy_code = str(getattr(attempt, "strategy_code", "") or "")
        strategy_spec = getattr(attempt, "strategy_spec", None)
        strategy_spec = strategy_spec if isinstance(strategy_spec, dict) else {}
        parent_attempt_id = str(strategy_spec.get("parent_attempt_id") or "")
        parent_id = hypothesis_ids.get(parent_attempt_id)
        parent = memory.get_hypothesis(parent_id) if parent_id else None
        node_metadata: dict[str, Any] = {
            "mission_id": mission_id,
            "candidate_id": candidate_id,
            "attempt_id": attempt_id,
        }
        if lineage_key is not None:
            node_metadata["lineage_key"] = lineage_key
        node = HypothesisNodeV1(
            idempotency_key=stable_memory_key(
                mission_id, candidate_id, prefix="arc-hypothesis"
            ),
            tree_id=tree_id,
            parent_id=parent_id,
            depth=0 if parent is None else parent.depth + 1,
            claim=claim,
            rationale="ARC candidate proposal recorded from the canonical mission journal.",
            target_regimes=[] if regime == "unknown" else [regime],
            mutation_type=_mutation_type(attempt, parent_attempt_id=parent_attempt_id),
            strategy_digest=(
                stable_memory_key(strategy_code, prefix="strategy").split(":", 1)[1]
                if strategy_code
                else None
            ),
            metadata=node_metadata,
        )
        hypothesis_ids[attempt_id] = memory.record_hypothesis(node)
        hypotheses_recorded += 1

    episodes_recorded = 0
    saw_observation_ended = False
    for event in list(getattr(projection, "events", None) or []):
        payload = dict(getattr(event, "payload", None) or {})
        event_type = str(getattr(event, "event_type", "") or "")
        event_id = str(getattr(event, "event_id", "") or "")
        if event_type == "paper_observation_ended":
            saw_observation_ended = True
        episode = _episode_from_event(
            mission_id=mission_id,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            symbols=symbols,
            timeframe=timeframe,
            market_regime=regime,
            lineage_key=lineage_key,
        )
        if episode is None:
            continue
        memory.record_episode(episode)
        episodes_recorded += 1
        attempt_id = str(payload.get("attempt_id") or "")
        hypothesis_id = hypothesis_ids.get(attempt_id)
        if hypothesis_id and episode.metadata.get("recall_eligible") is not False:
            _apply_outcome(memory, hypothesis_id, episode)

    if not saw_observation_ended:
        paper_outcome = getattr(projection, "paper_outcome", None)
        if isinstance(paper_outcome, dict) and paper_outcome:
            outcome_event_id = str(
                paper_outcome.get("outcome_id") or f"paper_outcome:{mission_id}"
            )
            episode = _episode_from_event(
                mission_id=mission_id,
                event_id=outcome_event_id,
                event_type="paper_observation_ended",
                payload=dict(paper_outcome),
                symbols=symbols,
                timeframe=timeframe,
                market_regime=regime,
                lineage_key=lineage_key,
            )
            if episode is not None:
                memory.record_episode(episode)
                episodes_recorded += 1
                attempt_id = str(paper_outcome.get("attempt_id") or "")
                hypothesis_id = hypothesis_ids.get(attempt_id)
                if hypothesis_id and episode.metadata.get("recall_eligible") is not False:
                    _apply_outcome(memory, hypothesis_id, episode)

    working = memory.populate_working_memory_for_task(
        session_id=f"arc-memory:{mission_id}",
        turn_id=f"projection:{len(getattr(projection, 'events', None) or [])}",
        goal=str(getattr(goal, "objective", "") or ""),
        symbol=symbol,
        timeframe=timeframe,
        current_regime=regime,
        budget_tokens=max(64, min(max_prompt_tokens, 2_000)),
        tree_id=tree_id,
    )
    if lineage_key is not None:
        _append_lineage_hypotheses(
            db,
            memory,
            working,
            tree_id=tree_id,
            lineage_key=lineage_key,
        )
    return CognitiveSyncResult(
        status="ok",
        prompt_context=working.format_prompt_context(max_tokens=max_prompt_tokens),
        hypotheses_recorded=hypotheses_recorded,
        episodes_recorded=episodes_recorded,
    )


def replay_arc_cognitive_memory_once(*, limit: int = 100) -> dict[str, int | str]:
    """Backfill bounded persisted ARC journals after restarts or missed inline hooks.

    Ingesting is idempotent but not cheap: it makes a database round trip per hypothesis and
    per episode. A mission already ingested at its current revision is parked and skipped; on a
    cold restart, each unresident mission loads only episode-producing event types and at most
    ``_MAX_UNRESIDENT_REPLAYS_PER_ROUND`` unresident missions are replayed per sweep so memory
    and DB load stay bounded.
    """
    database = get_configured_database()
    if database is None:
        return {"status": "unavailable", "missions": 0}
    mission_ids = sorted(list_mission_ids())
    bounded_limit = max(1, min(limit, 500))
    global _REPLAY_CURSOR
    with _REPLAY_CURSOR_LOCK:
        if mission_ids:
            start = _REPLAY_CURSOR % len(mission_ids)
            selected = (mission_ids[start:] + mission_ids[:start])[:bounded_limit]
        else:
            start = 0
            selected = []
    committed = committed_revisions(selected)
    synced = unchanged = unresident_synced = processed = 0
    for mission_id in selected:
        is_resident = mission_id in MISSIONS
        if not is_resident and unresident_synced >= _MAX_UNRESIDENT_REPLAYS_PER_ROUND:
            break
        processed += 1
        if is_parked("cognitive_replay", mission_id, committed.get(mission_id)):
            unchanged += 1
            continue
        controller = peek_controller_events(mission_id, _EPISODE_EVENT_TYPES)
        if controller is None:
            continue
        ingest_projection(database, mission_id, controller.projection)
        park("cognitive_replay", mission_id, controller.revision)  # only once it succeeded
        synced += 1
        if not is_resident:
            unresident_synced += 1
    if mission_ids:
        with _REPLAY_CURSOR_LOCK:
            _REPLAY_CURSOR = (start + processed) % len(mission_ids)
    sync_cognitive_to_memory_items(database)
    return {"status": "ok", "missions": synced, "unchanged": unchanged}


def sync_cognitive_to_memory_items(db: Database) -> int:
    """Distill pending cognitive episodes and project active rules/outcomes into MemoryItem."""
    distill_pending_regimes(
        db,
        causal_summarizer=deterministic_causal_summarizer,
        summarizer_version="deterministic-v1",
    )
    with db.session() as session:
        disabled_pairs = {
            (str(kind), str(content))
            for kind, content in session.execute(
                select(MemoryItem.kind, MemoryItem.content).where(
                    MemoryItem.disabled.is_(True),
                    MemoryItem.kind.in_(("arc_semantic_rule", "arc_race_outcome")),
                )
            ).all()
        }
        assertions = session.scalars(
            select(ArcSemanticAssertion)
            .where(ArcSemanticAssertion.status == "active")
            .order_by(
                ArcSemanticAssertion.updated_at.desc(),
                ArcSemanticAssertion.created_at.desc(),
            )
            .limit(100)
        ).all()
        race_episodes = session.scalars(
            select(ArcEpisodicMemory)
            .where(ArcEpisodicMemory.event_type.in_(("paper_race_won", "paper_race_lost")))
            .order_by(ArcEpisodicMemory.created_at.desc())
            .limit(100)
        ).all()

    memory_service = MemoryService(db)
    created = 0

    for assertion in assertions:
        meta = dict(assertion.metadata_json or {})
        symbols = [str(value) for value in (meta.get("symbols") or []) if value]
        timeframe = str(meta.get("timeframe") or "").strip()
        regimes = [str(value) for value in (assertion.applicable_regimes_json or []) if value]
        scope_parts = [*symbols, *([timeframe] if timeframe else []), *regimes]
        content = (
            f"[{', '.join(scope_parts)}] {assertion.claim}"
            if scope_parts
            else assertion.claim
        ).strip()
        if not content or ("arc_semantic_rule", content) in disabled_pairs:
            continue
        tags = [*scope_parts, assertion.assertion_type, "cognitive_memory"]
        item = memory_service.write(
            content=content,
            kind="arc_semantic_rule",
            source_run_id="cognitive-replay",
            source_tool="cognitive_memory.sync",
            tags=tags,
            importance=Decimal("0.7500"),
            confidence=assertion.confidence,
        )
        if item.usage_count == 1:
            created += 1

    for ep in race_episodes:
        meta = dict(ep.metadata_json or {})
        if meta.get("recall_eligible") is False:
            continue
        symbols = [str(value) for value in (ep.symbols_json or []) if value]
        timeframe = str(ep.timeframe or "").strip()
        regime = str(ep.market_regime or "").strip()
        verdict = str(
            meta.get("verdict") or ("won" if ep.event_type == "paper_race_won" else "lost")
        ).strip()
        scope_parts = [
            *symbols,
            *([timeframe] if timeframe else []),
            *([regime] if regime else []),
        ]
        content = (
            f"[{', '.join(scope_parts)}] {ep.reflection_summary}"
            if scope_parts
            else ep.reflection_summary
        ).strip()
        if not content or ("arc_race_outcome", content) in disabled_pairs:
            continue
        tags = [*scope_parts, verdict, ep.event_type, "cognitive_memory"]
        item = memory_service.write(
            content=content,
            kind="arc_race_outcome",
            source_run_id="cognitive-replay",
            source_tool="cognitive_memory.sync",
            tags=tags,
            importance=(
                Decimal("0.8000") if ep.event_type == "paper_race_won" else Decimal("0.7000")
            ),
            confidence=Decimal("0.7500"),
        )
        if item.usage_count == 1:
            created += 1

    return created


def _episode_from_event(
    *,
    mission_id: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    symbols: list[str],
    timeframe: str,
    market_regime: str,
    lineage_key: str | None = None,
) -> EpisodicMemoryItemV1 | None:
    source = event_type
    data = payload
    recall_eligible = True
    verdict = ""
    outcome_ref = ""
    if event_type == "red_team_tested":
        if payload.get("passed") is not False:
            return None
        memory_type = "redteam_falsified"
        evidence_ref = f"arc-event:{event_id}"
        experiment_id: str | None = None
    elif event_type == "avo_development_result":
        data = dict(payload.get("result") or {})
        evidence_ref = str(data.get("backtest_id") or "").strip()
        if not evidence_ref or _unknown_verdict(data):
            return None
        memory_type = "backtest_success" if data.get("passed") is True else "backtest_rejected"
        experiment_id = evidence_ref
    elif event_type == "bitpro_self_tested":
        evidence_ref = str(payload.get("backtest_id") or "").strip()
        if not evidence_ref or _unknown_verdict(payload):
            return None
        memory_type = "backtest_success" if payload.get("passed") is True else "backtest_rejected"
        experiment_id = evidence_ref
        # Final/holdout evidence is audit history, never research prompt feedback.
        recall_eligible = payload.get("purpose") == "development"
    elif event_type == "paper_observation_ended":
        verdict = str(payload.get("verdict") or "").strip()
        if (
            payload.get("reason") != "race_finished"
            and verdict not in {"won", "lost_futility", "lost_exam"}
        ):
            return None
        if verdict not in {"won", "lost_futility", "lost_exam"}:
            return None
        memory_type = "paper_race_won" if verdict == "won" else "paper_race_lost"
        outcome_ref = str(payload.get("outcome_id") or "").strip()
        evidence_ref = f"outcome:{outcome_ref or event_id}"
        experiment_id = outcome_ref or (
            str(payload.get("paper_instance_id") or "").strip() or None
        )
        recall_eligible = True
    else:
        return None
    attempt_id = str(data.get("attempt_id") or payload.get("attempt_id") or "")
    metrics = _json_mapping(data.get("metrics") or payload.get("metrics") or {})
    if event_type == "paper_observation_ended":
        metric_parts = [
            f"{key}={metrics[key]}"
            for key in (
                "excess_return_pct",
                "challenger_net_return_pct",
                "parent_net_return_pct",
                "challenger_max_drawdown_pct",
                "observed_hours",
                "sign_test_p",
            )
            if metrics.get(key) is not None
        ]
        metrics_note = f" ({', '.join(metric_parts)})" if metric_parts else ""
        summary = (
            f"{source} recorded forward race verdict={verdict} for "
            f"candidate {attempt_id or 'unknown'}{metrics_note}."
        )
        dedupe_token = outcome_ref or (
            f"attempt:{attempt_id}:{verdict}" if attempt_id else event_id
        )
        idempotency_key = stable_memory_key(
            mission_id,
            "paper_observation_ended",
            dedupe_token,
            prefix="arc-episode",
        )
    else:
        passed = data.get("passed", payload.get("passed"))
        summary = (
            f"{source} recorded candidate {attempt_id or 'unknown'} with "
            f"outcome={'passed' if passed is True else 'rejected'}."
        )
        idempotency_key = stable_memory_key(mission_id, event_id, prefix="arc-episode")
    metadata: dict[str, Any] = {
        "arc_event_id": event_id,
        "arc_event_type": source,
        "attempt_id": attempt_id,
        "recall_eligible": recall_eligible,
    }
    if event_type == "paper_observation_ended":
        metadata["verdict"] = verdict
        if outcome_ref:
            metadata["outcome_id"] = outcome_ref
    if lineage_key is not None:
        metadata["lineage_key"] = lineage_key
    return EpisodicMemoryItemV1(
        idempotency_key=idempotency_key,
        mission_id=mission_id,
        experiment_id=experiment_id,
        symbols=symbols,
        timeframe=timeframe,
        market_regime=market_regime,
        event_type=memory_type,
        metrics_delta=metrics,
        raw_evidence_ref=evidence_ref,
        reflection_summary=summary,
        metadata=metadata,
    )


def _apply_outcome(
    memory: LayeredMemoryService,
    hypothesis_id: str,
    episode: EpisodicMemoryItemV1,
) -> None:
    metrics = episode.metrics_delta
    relative_pnl = _decimal(metrics.get("benchmark_relative_pnl") or metrics.get("relative_pnl"))
    sharpe = _decimal(metrics.get("sharpe") or metrics.get("sharpe_ratio"))
    if episode.event_type == "redteam_falsified":
        status = HypothesisStatus.PRUNED
        prune_reason: str | None = "redteam_falsified"
    elif episode.event_type == "paper_race_won":
        status = HypothesisStatus.PROMOTED
        prune_reason = None
    elif episode.event_type == "paper_race_lost":
        status = HypothesisStatus.PRUNED
        prune_reason = str((episode.metadata or {}).get("verdict") or "paper_race_lost")
    elif episode.event_type == "backtest_success":
        status = HypothesisStatus.PROMOTED
        prune_reason = None
    else:
        status = HypothesisStatus.TESTED
        prune_reason = None
    memory.update_hypothesis_status(
        hypothesis_id,
        status=status,
        prune_reason=prune_reason,
        relative_pnl=relative_pnl,
        sharpe=sharpe,
        experiment_id=episode.experiment_id,
    )


def _lineage_key(goal: Any) -> str | None:
    context = getattr(goal, "evolution_context", None)
    if not isinstance(context, dict):
        return None
    source_strategy_id = context.get("source_strategy_id")
    if source_strategy_id is None or isinstance(source_strategy_id, bool):
        return None
    strategy_text = str(source_strategy_id).strip()
    if not strategy_text:
        return None
    target_id = str(context.get("target_id") or "bitpro").strip() or "bitpro"
    return f"{target_id}:{strategy_text}"


def _append_lineage_hypotheses(
    db: Database,
    memory: LayeredMemoryService,
    working: WorkingMemoryStateV1,
    *,
    tree_id: str,
    lineage_key: str,
    limit: int = 10,
) -> None:
    seen_ids = {node.id for node in working.active_hypotheses if node.id}
    seen_signatures = {
        (node.claim, node.status, node.experiment_id)
        for node in working.active_hypotheses
    }
    with db.session() as session:
        rows = session.scalars(
            select(ArcHypothesisNode)
            .where(
                ArcHypothesisNode.tree_id != tree_id,
                sql_cast(
                    ArcHypothesisNode.metadata_json["lineage_key"].as_string(),
                    String,
                )
                == lineage_key,
            )
            .order_by(ArcHypothesisNode.created_at.desc())
            .limit(25)
        ).all()
    added = 0
    for row in rows:
        node = memory._db_to_hypothesis(row)
        sig = (node.claim, node.status, node.experiment_id)
        if node.id in seen_ids or sig in seen_signatures:
            continue
        if node.id:
            seen_ids.add(node.id)
        seen_signatures.add(sig)
        working.active_hypotheses.append(node)
        added += 1
        if added >= limit:
            break


def _market_regime(goal: Any) -> str:
    for context_name in ("evolution_context", "feedback_parent"):
        context = getattr(goal, context_name, None)
        if not isinstance(context, dict):
            continue
        for key in ("market_regime", "regime"):
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        snapshot = context.get("regime_snapshot")
        if isinstance(snapshot, dict):
            value = snapshot.get("regime") or snapshot.get("label")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "unknown"


def _mutation_type(attempt: Any, *, parent_attempt_id: str = "") -> MutationType:
    spec = getattr(attempt, "strategy_spec", None)
    raw = spec.get("mutation_type") if isinstance(spec, dict) else None
    try:
        if raw:
            return MutationType(str(raw))
        return MutationType.PARAM_REFINE if parent_attempt_id else MutationType.INIT
    except ValueError:
        return MutationType.INIT


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _json_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return cast(dict[str, Any], json.loads(json.dumps(value, default=str)))


def _unknown_verdict(payload: dict[str, Any]) -> bool:
    if not isinstance(payload.get("passed"), bool):
        return True
    for key in ("status", "verdict", "result_status"):
        value = str(payload.get(key) or "").lower()
        if any(marker in value for marker in ("unknown", "unavailable", "missing", "timeout")):
            return True
    reasons = payload.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    markers = ("unknown", "unavailable", "missing", "timeout")
    return any(
        any(marker in str(reason).lower() for marker in markers)
        for reason in reasons
    )
