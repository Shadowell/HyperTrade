"""Idempotent projection adapter from the canonical ARC journal to cognitive memory."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import Lock
from typing import Any, cast

from hypertrade.arc.store import (
    get_configured_database,
    get_controller,
    list_mission_ids,
)
from hypertrade.db import Database
from hypertrade.memory.layered_service import (
    EpisodicMemoryItemV1,
    HypothesisNodeV1,
    HypothesisStatus,
    LayeredMemoryService,
    MutationType,
    stable_memory_key,
)

logger = logging.getLogger(__name__)
_REPLAY_CURSOR = 0
_REPLAY_CURSOR_LOCK = Lock()


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
            metadata={
                "mission_id": mission_id,
                "candidate_id": candidate_id,
                "attempt_id": attempt_id,
            },
        )
        hypothesis_ids[attempt_id] = memory.record_hypothesis(node)
        hypotheses_recorded += 1

    episodes_recorded = 0
    for event in list(getattr(projection, "events", None) or []):
        payload = dict(getattr(event, "payload", None) or {})
        event_type = str(getattr(event, "event_type", "") or "")
        event_id = str(getattr(event, "event_id", "") or "")
        episode = _episode_from_event(
            mission_id=mission_id,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            symbols=symbols,
            timeframe=timeframe,
            market_regime=regime,
        )
        if episode is None:
            continue
        memory.record_episode(episode)
        episodes_recorded += 1
        attempt_id = str(payload.get("attempt_id") or "")
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
    return CognitiveSyncResult(
        status="ok",
        prompt_context=working.format_prompt_context(max_tokens=max_prompt_tokens),
        hypotheses_recorded=hypotheses_recorded,
        episodes_recorded=episodes_recorded,
    )


def replay_arc_cognitive_memory_once(*, limit: int = 100) -> dict[str, int | str]:
    """Backfill bounded persisted ARC journals after restarts or missed inline hooks."""
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
            _REPLAY_CURSOR = (start + len(selected)) % len(mission_ids)
        else:
            selected = []
    synced = 0
    for mission_id in selected:
        controller = get_controller(mission_id)
        if controller is None:
            continue
        ingest_projection(database, mission_id, controller.projection)
        synced += 1
    return {"status": "ok", "missions": synced}


def _episode_from_event(
    *,
    mission_id: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    symbols: list[str],
    timeframe: str,
    market_regime: str,
) -> EpisodicMemoryItemV1 | None:
    source = event_type
    data = payload
    recall_eligible = True
    if event_type == "red_team_tested":
        if payload.get("passed") is not False:
            return None
        memory_type = "redteam_falsified"
        evidence_ref = f"arc-event:{event_id}"
        experiment_id = None
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
    else:
        return None
    attempt_id = str(data.get("attempt_id") or payload.get("attempt_id") or "")
    metrics = _json_mapping(data.get("metrics") or payload.get("metrics") or {})
    passed = data.get("passed", payload.get("passed"))
    summary = (
        f"{source} recorded candidate {attempt_id or 'unknown'} with "
        f"outcome={'passed' if passed is True else 'rejected'}."
    )
    return EpisodicMemoryItemV1(
        idempotency_key=stable_memory_key(mission_id, event_id, prefix="arc-episode"),
        mission_id=mission_id,
        experiment_id=experiment_id,
        symbols=symbols,
        timeframe=timeframe,
        market_regime=market_regime,
        event_type=memory_type,
        metrics_delta=metrics,
        raw_evidence_ref=evidence_ref,
        reflection_summary=summary,
        metadata={
            "arc_event_id": event_id,
            "arc_event_type": source,
            "attempt_id": attempt_id,
            "recall_eligible": recall_eligible,
        },
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
        prune_reason = "redteam_falsified"
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
