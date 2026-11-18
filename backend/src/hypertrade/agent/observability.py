"""Trace-safe projections for the Agent Flight Recorder.

The runtime already stores append-only graph and tool evidence. This service
projects those records into an operator-facing timeline without copying prompts,
credentials, raw reasoning, or large tool payloads into another data store.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select

from hypertrade.db import (
    AgentMission,
    AgentMissionEvent,
    AgentRun,
    AgentStepAttempt,
    AgentToolCall,
    Database,
    MemoryItem,
    TraceEvent,
)

_MISSION_TERMINAL_STATUSES = frozenset({"completed", "failed", "canceled", "budget_exhausted"})


class AgentObservabilityService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, run_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                if run_id.startswith("mis_"):
                    mission = session.get(AgentMission, run_id)
                    if mission is None:
                        raise KeyError(run_id)
                    return _mission_observability(session, mission)
                raise KeyError(run_id)
            events = list(
                session.scalars(
                    select(TraceEvent)
                    .where(TraceEvent.run_id == run_id)
                    .order_by(TraceEvent.created_at, TraceEvent.id)
                ).all()
            )
            observability = _run_observability(run)
            state = _dict(run.run_state_json)
            memory_ids = _memory_ids(observability, events)
            memories = (
                list(
                    session.scalars(
                        select(MemoryItem)
                        .where(MemoryItem.id.in_(memory_ids))
                        .order_by(MemoryItem.created_at)
                    ).all()
                )
                if memory_ids
                else []
            )
            timeline = [
                _timeline_event(event, sequence=index, run_started_at=run.created_at)
                for index, event in enumerate(events, start=1)
            ]
            return {
                "schema_version": "agent-observability-v1",
                "run": {
                    "id": run.id,
                    "status": run.status,
                    "provider": str(observability.get("provider", "")),
                    "model": str(observability.get("model", "")),
                    "duration_ms": _safe_float(observability.get("duration_ms")),
                    "started_at": _iso(run.created_at),
                    "completed_at": str(observability.get("completed_at", "")),
                    "execution_mode": str(state.get("execution_mode", "standard")),
                },
                "usage": _dict(observability.get("usage")),
                "models": {
                    "request_count": len(_list(observability.get("model_calls"))),
                    "calls": _list(observability.get("model_calls")),
                },
                "tools": _dict(observability.get("tools")),
                "memory": {
                    **_dict(observability.get("memory")),
                    "items": [_memory_item(item) for item in memories],
                },
                "timeline": timeline,
                "categories": _category_counts(timeline),
                "external_observability": _dict(state.get("external_observability")),
                "safety": {
                    "private_reasoning_stored": False,
                    "secrets_redacted": True,
                    "payload_mode": "summary",
                    "evaluation_mode": state.get("execution_mode") == "evaluation",
                },
            }

    def recent_summary(self, *, limit: int = 25) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 100))
        with self.db.session() as session:
            runs = list(
                session.scalars(
                    select(AgentRun).order_by(desc(AgentRun.created_at)).limit(safe_limit)
                ).all()
            )
            items: list[dict[str, Any]] = []
            durations: list[float] = []
            total_tokens = 0
            reported_runs = 0
            model_requests = 0
            completed_runs = 0
            for run in runs:
                observability = _run_observability(run)
                usage = _dict(observability.get("usage"))
                duration_ms = _safe_float(observability.get("duration_ms"))
                if duration_ms:
                    durations.append(duration_ms)
                run_tokens = _safe_int(usage.get("total_tokens"))
                total_tokens += run_tokens
                model_requests += _safe_int(usage.get("request_count"))
                if bool(usage.get("reported")):
                    reported_runs += 1
                if run.status == "completed":
                    completed_runs += 1
                items.append(
                    {
                        "run_id": run.id,
                        "status": run.status,
                        "provider": str(observability.get("provider", "")),
                        "model": str(observability.get("model", "")),
                        "duration_ms": duration_ms,
                        "total_tokens": run_tokens,
                        "usage_reported": bool(usage.get("reported")),
                        "created_at": _iso(run.created_at),
                    }
                )
            return {
                "window_size": len(runs),
                "completed_runs": completed_runs,
                "success_rate": round(completed_runs / len(runs), 4) if runs else 0.0,
                "model_requests": model_requests,
                "total_tokens": total_tokens,
                "usage_reported_runs": reported_runs,
                "p50_duration_ms": _percentile(durations, 0.50),
                "p95_duration_ms": _percentile(durations, 0.95),
                "recent": items[:6],
                "private_reasoning_stored": False,
            }


def _mission_observability(session: Any, mission: AgentMission) -> dict[str, Any]:
    events = list(
        session.scalars(
            select(AgentMissionEvent)
            .where(AgentMissionEvent.mission_id == mission.id)
            .order_by(
                AgentMissionEvent.sequence,
                AgentMissionEvent.created_at,
                AgentMissionEvent.id,
            )
        ).all()
    )
    attempts = list(
        session.scalars(
            select(AgentStepAttempt)
            .where(AgentStepAttempt.mission_id == mission.id)
            .order_by(AgentStepAttempt.started_at, AgentStepAttempt.id)
        ).all()
    )
    tool_calls = list(
        session.scalars(
            select(AgentToolCall)
            .where(AgentToolCall.mission_id == mission.id)
            .order_by(AgentToolCall.created_at, AgentToolCall.id)
        ).all()
    )
    attempt_by_id = {attempt.id: attempt for attempt in attempts}
    usage_json = _dict(mission.usage_json)

    read_ids, write_ids, attempt_memory_ids = _mission_memory_refs(
        session, mission=mission, attempts=attempts, events=events
    )
    all_memory_ids = list(dict.fromkeys([*read_ids, *write_ids]))
    memories = (
        list(
            session.scalars(
                select(MemoryItem)
                .where(MemoryItem.id.in_(all_memory_ids))
                .order_by(MemoryItem.created_at)
            ).all()
        )
        if all_memory_ids
        else []
    )

    tools, total_execution_ms = _mission_tools_summary(
        attempts=attempts,
        tool_calls=tool_calls,
        usage_json=usage_json,
    )
    usage = _mission_usage_summary(usage_json)
    started_at = _aware(mission.created_at)
    completed_dt = (
        _aware(mission.updated_at) if mission.status in _MISSION_TERMINAL_STATUSES else None
    )
    usage_duration = _safe_float(usage_json.get("duration_ms"))
    if usage_duration > 0:
        duration_ms = usage_duration
    elif total_execution_ms > 0:
        duration_ms = total_execution_ms
    elif completed_dt is not None:
        duration_ms = round(max(0.0, (completed_dt - started_at).total_seconds() * 1000), 3)
    else:
        duration_ms = 0.0

    timeline = _mission_timeline(
        mission_started_at=started_at,
        events=events,
        attempts=attempts,
        attempt_by_id=attempt_by_id,
        attempt_memory_ids=attempt_memory_ids,
        tool_calls=tool_calls,
    )
    return {
        "schema_version": "agent-observability-v1",
        "run": {
            "id": mission.id,
            "status": mission.status,
            "provider": "mission_runtime",
            "model": mission.permission_profile_ref,
            "duration_ms": duration_ms,
            "started_at": _iso(started_at),
            "completed_at": _iso(completed_dt) if completed_dt is not None else "",
            "execution_mode": "governed_mission",
        },
        "usage": usage,
        "models": {
            "request_count": _safe_int(usage.get("request_count")),
            "calls": [],
        },
        "tools": tools,
        "memory": {
            "read_count": len(read_ids),
            "write_count": len(write_ids),
            "read_ids": read_ids,
            "write_ids": write_ids,
            "items": [_memory_item(item) for item in memories],
        },
        "timeline": timeline,
        "categories": _category_counts(timeline),
        "external_observability": {},
        "safety": {
            "private_reasoning_stored": False,
            "secrets_redacted": True,
            "payload_mode": "summary",
            "evaluation_mode": False,
        },
    }


def _mission_usage_summary(usage_json: dict[str, Any]) -> dict[str, int | bool]:
    input_tokens = _safe_int(usage_json.get("input_tokens"))
    output_tokens = _safe_int(usage_json.get("output_tokens"))
    cached_input_tokens = _safe_int(usage_json.get("cached_input_tokens"))
    reasoning_tokens = _safe_int(usage_json.get("reasoning_tokens"))
    total_tokens = _safe_int(usage_json.get("total_tokens", usage_json.get("tokens")))
    request_count = _safe_int(usage_json.get("request_count", usage_json.get("model_calls")))
    reported = (
        bool(usage_json["reported"])
        if "reported" in usage_json
        else (total_tokens > 0 or input_tokens > 0 or output_tokens > 0)
    )
    reported_requests = (
        _safe_int(usage_json.get("reported_requests"))
        if "reported_requests" in usage_json
        else (request_count if reported else 0)
    )
    unreported_requests = (
        _safe_int(usage_json.get("unreported_requests"))
        if "unreported_requests" in usage_json
        else max(0, request_count - reported_requests)
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cached_input_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "request_count": request_count,
        "reported_requests": reported_requests,
        "unreported_requests": unreported_requests,
        "reported": reported,
    }


def _attempt_duration_ms(attempt: AgentStepAttempt) -> float:
    obs = _dict(attempt.observation_json)
    obs_usage = _dict(obs.get("usage"))
    duration_ms = _safe_float(obs_usage.get("duration_ms"))
    if duration_ms > 0:
        return round(duration_ms, 3)
    if attempt.completed_at is not None:
        elapsed_ms = (
            _aware(attempt.completed_at) - _aware(attempt.started_at)
        ).total_seconds() * 1000
        return round(max(0.0, elapsed_ms), 3)
    return 0.0


def _tool_call_duration_ms(call: AgentToolCall) -> float:
    call_json = _dict(call.call_json)
    duration_ms = _safe_float(call_json.get("duration_ms", call_json.get("execution_ms")))
    if duration_ms > 0:
        return round(duration_ms, 3)
    if call.updated_at and call.created_at:
        return round(
            max(0.0, (_aware(call.updated_at) - _aware(call.created_at)).total_seconds() * 1000),
            3,
        )
    return 0.0


def _mission_tools_summary(
    *,
    attempts: list[AgentStepAttempt],
    tool_calls: list[AgentToolCall],
    usage_json: dict[str, Any],
) -> tuple[dict[str, Any], float]:
    entries: list[dict[str, Any]] = []
    error_count = 0
    for attempt in attempts:
        obs = _dict(attempt.observation_json)
        exec_status = str(obs.get("status") or attempt.status)
        exec_ms = _attempt_duration_ms(attempt)
        is_error = attempt.status in {"failed", "unknown"} or exec_status in {
            "failed",
            "error",
            "timeout",
            "denied",
            "unavailable",
        }
        if is_error:
            error_count += 1
        entries.append(
            {
                "tool_name": attempt.capability_id,
                "execution_status": exec_status,
                "execution_ms": exec_ms,
            }
        )
    for call in tool_calls:
        call_json = _dict(call.call_json)
        exec_ms = _tool_call_duration_ms(call)
        is_error = call.status in {"failed", "denied", "effect_unknown"} or bool(
            call_json.get("error_category")
        )
        if is_error:
            error_count += 1
        entries.append(
            {
                "tool_name": call.capability_id,
                "execution_status": call.status,
                "execution_ms": exec_ms,
            }
        )
    total_execution_ms = round(sum(float(item["execution_ms"]) for item in entries), 3)
    slowest = (
        max(entries, key=lambda item: float(item["execution_ms"]))
        if entries
        else None
    )
    call_count = len(entries) if entries else _safe_int(usage_json.get("tool_calls"))
    return (
        {
            "call_count": call_count,
            "error_count": error_count,
            "total_execution_ms": total_execution_ms,
            "slowest": slowest,
            "calls": entries,
        },
        total_execution_ms,
    )


def _extract_observation_memory_ids(
    capability_id: str, observation: dict[str, Any]
) -> tuple[list[str], str]:
    ids: list[str] = []
    result = _dict(observation.get("result"))
    mem_id = result.get("memory_id")
    if isinstance(mem_id, str) and mem_id:
        ids.append(mem_id)
    if capability_id in {"memory.search", "memory_search"}:
        for row in _list(result.get("items")):
            if isinstance(row, dict):
                item_id = row.get("memory_id") or row.get("id")
                if isinstance(item_id, str) and item_id:
                    ids.append(item_id)
    for ref in _list(observation.get("source_refs")):
        if isinstance(ref, str) and ref.startswith("memory:") and ref != "memory:no_matches":
            ids.append(ref.removeprefix("memory:"))
    deduped = list(dict.fromkeys(ids))
    if capability_id in {"memory.write", "memory_write"}:
        return deduped, "write"
    if capability_id in {"memory.search", "memory_search"} or deduped:
        return deduped, "read"
    return [], ""


def _mission_memory_refs(
    session: Any,
    *,
    mission: AgentMission,
    attempts: list[AgentStepAttempt],
    events: list[AgentMissionEvent],
) -> tuple[list[str], list[str], dict[str, list[str]]]:
    read_ids: list[str] = []
    write_ids: list[str] = []
    attempt_memory_ids: dict[str, list[str]] = {}
    for attempt in attempts:
        ids, role = _extract_observation_memory_ids(
            attempt.capability_id, _dict(attempt.observation_json)
        )
        if ids:
            attempt_memory_ids[attempt.id] = ids
        if role == "write":
            write_ids.extend(ids)
        elif role == "read":
            read_ids.extend(ids)
    for event in events:
        payload = _dict(event.payload_json)
        obs = _dict(payload.get("observation"))
        if obs:
            cap_id = str(payload.get("capability_id") or "")
            ids, role = _extract_observation_memory_ids(cap_id, obs)
            if role == "write":
                write_ids.extend(ids)
            elif role == "read":
                read_ids.extend(ids)
        direct_id = payload.get("memory_id")
        if isinstance(direct_id, str) and direct_id:
            if "write" in event.event_type:
                write_ids.append(direct_id)
            else:
                read_ids.append(direct_id)
    mission_written = list(
        session.scalars(
            select(MemoryItem.id)
            .where(MemoryItem.source_run_id == mission.id[:32])
            .order_by(MemoryItem.created_at)
        ).all()
    )
    write_ids.extend(str(mem_id) for mem_id in mission_written if mem_id)
    return list(dict.fromkeys(read_ids)), list(dict.fromkeys(write_ids)), attempt_memory_ids


def _mission_timeline(
    *,
    mission_started_at: datetime,
    events: list[AgentMissionEvent],
    attempts: list[AgentStepAttempt],
    attempt_by_id: dict[str, AgentStepAttempt],
    attempt_memory_ids: dict[str, list[str]],
    tool_calls: list[AgentToolCall],
) -> list[dict[str, Any]]:
    raw_items: list[tuple[datetime, int, dict[str, Any]]] = []
    represented_attempts: set[str] = set()
    completed_attempts: set[str] = set()
    order = 0

    for event in events:
        order += 1
        ts = _aware(event.occurred_at or event.created_at)
        payload = _dict(event.payload_json)
        item = _mission_event_timeline_item(
            event=event,
            payload=payload,
            attempt_by_id=attempt_by_id,
            attempt_memory_ids=attempt_memory_ids,
        )
        attempt_payload = _dict(payload.get("attempt"))
        attempt_id = str(payload.get("attempt_id") or attempt_payload.get("attempt_id") or "")
        if attempt_id:
            represented_attempts.add(attempt_id)
            if event.event_type in {"attempt.completed", "step_observed"}:
                completed_attempts.add(attempt_id)
        raw_items.append((ts, order, item))

    for attempt in attempts:
        if attempt.id in completed_attempts:
            continue
        if attempt.id in represented_attempts and attempt.status == "running":
            continue
        order += 1
        ts = _aware(attempt.completed_at or attempt.started_at)
        obs = _dict(attempt.observation_json)
        is_memory = attempt.capability_id.startswith(("memory.", "memory_"))
        raw_items.append(
            (
                ts,
                order,
                {
                    "id": attempt.id,
                    "category": "memory" if is_memory else "tool",
                    "name": attempt.capability_id.replace("_", ".")
                    if is_memory
                    else attempt.capability_id,
                    "status": str(obs.get("status") or attempt.status),
                    "created_at": _iso(ts),
                    "duration_ms": _attempt_duration_ms(attempt),
                    "summary": str(
                        obs.get("summary") or f"step {attempt.step_id} · {attempt.status}"
                    ),
                    "usage": {},
                    "memory_ids": attempt_memory_ids.get(attempt.id, []),
                },
            )
        )

    for call in tool_calls:
        order += 1
        ts = _aware(call.updated_at or call.created_at)
        call_json = _dict(call.call_json)
        is_memory = call.capability_id.startswith(("memory.", "memory_"))
        err_cat = str(call_json.get("error_category") or "")
        outcome = str(call_json.get("reconciliation_outcome") or "")
        detail_parts = [part for part in (call.status, err_cat, outcome) if part]
        raw_items.append(
            (
                ts,
                order,
                {
                    "id": call.id,
                    "category": "memory" if is_memory else "tool",
                    "name": call.capability_id,
                    "status": call.status,
                    "created_at": _iso(ts),
                    "duration_ms": _tool_call_duration_ms(call),
                    "summary": " · ".join(detail_parts) or call.capability_id,
                    "usage": {},
                    "memory_ids": [],
                },
            )
        )

    raw_items.sort(key=lambda pair: (pair[0], pair[1]))
    timeline: list[dict[str, Any]] = []
    for sequence, (ts, _, entry) in enumerate(raw_items, start=1):
        offset_ms = max(0.0, (ts - mission_started_at).total_seconds() * 1000)
        timeline.append(
            {
                **entry,
                "sequence": sequence,
                "offset_ms": round(offset_ms, 3),
            }
        )
    return timeline


def _mission_event_timeline_item(
    *,
    event: AgentMissionEvent,
    payload: dict[str, Any],
    attempt_by_id: dict[str, AgentStepAttempt],
    attempt_memory_ids: dict[str, list[str]],
) -> dict[str, Any]:
    event_type = event.event_type
    ts = _aware(event.occurred_at or event.created_at)
    category = "graph"
    name = event_type
    status = "completed"
    duration_ms = 0.0
    summary = event_type
    usage: dict[str, Any] = {}
    memory_ids: list[str] = []

    if event_type in {"attempt.completed", "step_observed"}:
        attempt_id = str(payload.get("attempt_id") or "")
        attempt = attempt_by_id.get(attempt_id)
        obs = _dict(payload.get("observation"))
        capability_id = (
            attempt.capability_id
            if attempt is not None
            else str(payload.get("capability_id") or "")
        )
        is_memory = capability_id.startswith(("memory.", "memory_"))
        category = "memory" if is_memory else "tool"
        name = (
            capability_id.replace("_", ".")
            if is_memory
            else (capability_id or "step_attempt")
        )
        status = str(obs.get("status") or (attempt.status if attempt else "completed"))
        if attempt is not None:
            duration_ms = _attempt_duration_ms(attempt)
            memory_ids = attempt_memory_ids.get(attempt.id, [])
        else:
            duration_ms = _safe_float(_dict(obs.get("usage")).get("duration_ms"))
            memory_ids = _extract_observation_memory_ids(capability_id, obs)[0]
        summary = str(obs.get("summary") or f"{name} · {status}")
    elif event_type in {"attempt.started", "step_started"}:
        att_payload = _dict(payload.get("attempt"))
        cap_id = str(att_payload.get("capability_id") or "")
        step_id = str(att_payload.get("step_id") or "")
        status = str(att_payload.get("status") or "running")
        summary = f"{step_id} · {cap_id}" if step_id and cap_id else (cap_id or event_type)
    elif event_type == "mission.completion_proof_recorded":
        proof = _dict(payload.get("proof"))
        passed = bool(proof.get("passed"))
        category = "policy"
        name = "completion_proof"
        status = "passed" if passed else "failed"
        gaps = _list(proof.get("gaps"))
        summary = "completion proof passed" if passed else f"completion gaps: {len(gaps)}"
    elif event_type in {"mission.transitioned", "mission_transitioned"}:
        src = str(payload.get("from") or "")
        dst = str(payload.get("to") or "")
        reason = str(payload.get("reason") or "")
        status = dst or "transitioned"
        if event.actor == "mission_safety" or dst == "waiting_approval":
            category = "policy"
        summary = f"{src} -> {dst}" if src and dst else (dst or event_type)
        if reason:
            summary = f"{summary} ({reason})"
    elif event_type in {"plan.activated", "plan_activated"}:
        plan = _dict(payload.get("plan"))
        steps = _list(plan.get("steps"))
        version = plan.get("version", "")
        summary = f"plan v{version} · {len(steps)} steps" if version else f"{len(steps)} steps"
    elif event_type == "context.compiled":
        used = _safe_int(payload.get("used_tokens"))
        budget = _safe_int(payload.get("budget_tokens"))
        summary = f"compiled {used}/{budget} tokens"
    elif event_type == "mission.usage_updated":
        delta = _dict(payload.get("delta"))
        summary = (
            f"tokens +{delta.get('tokens', 0)} · tools +{delta.get('tool_calls', 0)}"
        )
    elif "model" in event_type:
        category = "model"
        usage = _dict(payload.get("usage"))
        status = str(payload.get("status") or "completed")
        summary = str(payload.get("summary") or event_type)
    elif any(key in event_type for key in ("policy", "approval", "safety", "quarantine")):
        category = "policy"
        status = str(payload.get("status") or payload.get("decision") or "checked")
        summary = str(payload.get("reason") or payload.get("summary") or event_type)
    elif "memory" in event_type:
        category = "memory"
        mem_id = payload.get("memory_id")
        if isinstance(mem_id, str) and mem_id:
            memory_ids = [mem_id]
        summary = str(payload.get("summary") or event_type)
    elif event_type.startswith("tool."):
        category = "tool"
        status = str(payload.get("status") or "completed")
        summary = str(payload.get("summary") or event_type)

    return {
        "id": event.id,
        "category": category,
        "name": name,
        "status": status,
        "created_at": _iso(ts),
        "duration_ms": round(duration_ms, 3),
        "summary": summary,
        "usage": usage,
        "memory_ids": memory_ids,
    }


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _run_observability(run: AgentRun) -> dict[str, Any]:
    state = run.run_state_json if isinstance(run.run_state_json, dict) else {}
    value = state.get("observability")
    if isinstance(value, dict):
        return dict(value)
    report = run.report_json if isinstance(run.report_json, dict) else {}
    value = report.get("observability")
    return dict(value) if isinstance(value, dict) else {}


def _timeline_event(
    event: TraceEvent,
    *,
    sequence: int,
    run_started_at: datetime,
) -> dict[str, Any]:
    input_json = _dict(event.input_json)
    output_json = _dict(event.output_json)
    category, name = _event_category(event.tool_name)
    created_at = event.created_at
    offset_ms = max(0.0, (created_at - run_started_at).total_seconds() * 1000)
    usage = _dict(output_json.get("usage")) if category == "model" else {}
    memory_ids = _event_memory_ids(event.tool_name, output_json)
    status = str(output_json.get("execution_status") or event.status)
    return {
        "id": event.id,
        "sequence": sequence,
        "category": category,
        "name": name,
        "status": status,
        "created_at": _iso(created_at),
        "offset_ms": round(offset_ms, 3),
        "duration_ms": _safe_float(
            output_json.get("duration_ms", output_json.get("execution_ms"))
        ),
        "summary": _event_summary(category, name, input_json, output_json),
        "usage": usage,
        "memory_ids": memory_ids,
    }


def _event_category(tool_name: str) -> tuple[str, str]:
    if tool_name == "graph.model_call":
        return ("model", "model_call")
    if tool_name == "graph.approval_check":
        return ("policy", "approval_check")
    if tool_name.startswith("graph."):
        return ("graph", tool_name.removeprefix("graph."))
    if tool_name in {"memory_write", "memory_search", "memory.write", "memory.search"}:
        return ("memory", tool_name.replace("_", "."))
    return ("tool", tool_name)


def _event_summary(
    category: str,
    name: str,
    input_json: dict[str, Any],
    output_json: dict[str, Any],
) -> str:
    if category == "model":
        usage = _dict(output_json.get("usage"))
        usage_label = (
            f"{_safe_int(usage.get('total_tokens'))} tokens"
            if usage.get("reported")
            else "usage unavailable"
        )
        return (
            f"iteration {_safe_int(input_json.get('iteration'))} · "
            f"{_safe_int(output_json.get('tool_call_count'))} tool calls · {usage_label}"
        )
    if category == "memory":
        ids = _event_memory_ids(name, output_json)
        action = "write" if "write" in name else "read"
        return f"{action} {len(ids)} audited item{'s' if len(ids) != 1 else ''}"
    if category == "policy":
        return str(output_json.get("status") or output_json.get("policy_outcome") or "checked")
    if category == "tool":
        policy = _dict(output_json.get("policy"))
        source = str(policy.get("source_of_truth") or output_json.get("data_source") or "")
        status = str(output_json.get("execution_status") or "completed")
        return f"{status}{f' · source {source}' if source else ''}"
    if name == "plan_tools":
        planner = str(output_json.get("planner") or "provider_unavailable")
        model = str(output_json.get("model") or "")
        return f"{planner}{f' / {model}' if model else ''}"
    if name == "execute_tool":
        return str(output_json.get("status") or "completed")
    return "completed"


def _event_memory_ids(tool_name: str, output_json: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    memory_id = output_json.get("memory_id")
    if isinstance(memory_id, str) and memory_id:
        ids.append(memory_id)
    if "memory" in tool_name:
        items = output_json.get("items")
        if isinstance(items, list):
            ids.extend(
                str(item.get("id"))
                for item in items
                if isinstance(item, dict) and item.get("id")
            )
    return list(dict.fromkeys(ids))


def _memory_ids(observability: dict[str, Any], events: list[TraceEvent]) -> list[str]:
    memory = _dict(observability.get("memory"))
    ids = [str(value) for value in _list(memory.get("read_ids")) if value]
    ids.extend(str(value) for value in _list(memory.get("write_ids")) if value)
    for event in events:
        ids.extend(_event_memory_ids(event.tool_name, _dict(event.output_json)))
    return list(dict.fromkeys(ids))


def _memory_item(item: MemoryItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "content_preview": item.content[:240],
        "source_run_id": item.source_run_id,
        "source_tool": item.source_tool,
        "importance": str(item.importance),
        "confidence": str(item.confidence),
        "usage_count": item.usage_count,
        "created_at": _iso(item.created_at),
    }


def _category_counts(timeline: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"graph": 0, "model": 0, "tool": 0, "memory": 0, "policy": 0}
    for event in timeline:
        category = str(event.get("category", ""))
        if category in counts:
            counts[category] += 1
    return counts


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 3)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _iso(value: datetime) -> str:
    return value.isoformat()
