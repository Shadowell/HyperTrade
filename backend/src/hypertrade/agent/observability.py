"""Trace-safe projections for the Agent Flight Recorder.

The runtime already stores append-only graph and tool evidence. This service
projects those records into an operator-facing timeline without copying prompts,
credentials, raw reasoning, or large tool payloads into another data store.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from sqlalchemy import desc, select

from hypertrade.db import AgentRun, Database, MemoryItem, TraceEvent


class AgentObservabilityService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, run_id: str) -> dict[str, Any]:
        with self.db.session() as session:
            run = session.get(AgentRun, run_id)
            if run is None:
                raise KeyError(run_id)
            events = list(
                session.scalars(
                    select(TraceEvent)
                    .where(TraceEvent.run_id == run_id)
                    .order_by(TraceEvent.created_at, TraceEvent.id)
                ).all()
            )
            observability = _run_observability(run)
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
                "safety": {
                    "private_reasoning_stored": False,
                    "secrets_redacted": True,
                    "payload_mode": "summary",
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
