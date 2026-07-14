"""Sanitized Agent trajectories for offline evaluation tools.

Trajectory artifacts are generated only from explicitly labelled isolated eval
runs. Their schema deliberately keeps only stable tool names and a small
allowlist of non-sensitive routing arguments.
"""

from __future__ import annotations

from typing import Any

from hypertrade.tools.registry import ToolRegistry

SAFE_ARGUMENT_KEYS = frozenset(
    {
        "bar",
        "exchange",
        "include_curated",
        "limit",
        "page",
        "per_page",
        "sample_limit",
        "strategy_id",
        "symbol",
        "symbols",
        "timeframe",
    }
)


def build_trajectory_from_api_payload(case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a Ragas-compatible, prompt-free trajectory projection."""
    state = _dict(payload.get("run_state_json"))
    trace_events = payload.get("trace_events")
    events = trace_events if isinstance(trace_events, list) else []
    return {
        "schema_version": "agent-evaluation-trajectory-v1",
        "case_id": case_id,
        "run_id": str(payload.get("id", "")),
        "status": str(payload.get("status", "")),
        "execution_mode": str(state.get("execution_mode", "standard")),
        "tool_calls": [
            tool_call
            for event in events
            if isinstance(event, dict)
            if (tool_call := _tool_call_from_event(event)) is not None
        ],
    }


def _tool_call_from_event(event: dict[str, Any]) -> dict[str, Any] | None:
    name = str(event.get("tool_name", ""))
    try:
        ToolRegistry.default().get_for_runtime_name(name)
    except KeyError:
        return None
    output = _dict(event.get("output_json"))
    return {
        "name": name,
        "args": _safe_args(_dict(event.get("input_json"))),
        "execution_status": str(output.get("execution_status") or event.get("status", "")),
        "policy_outcome": str(output.get("policy_outcome", "")),
    }


def _safe_args(args: dict[str, Any]) -> dict[str, str | int | float | bool | list[str]]:
    sanitized: dict[str, str | int | float | bool | list[str]] = {}
    for key in SAFE_ARGUMENT_KEYS:
        if key not in args:
            continue
        value = args[key]
        if isinstance(value, bool | int | float):
            sanitized[key] = value
        elif isinstance(value, str):
            sanitized[key] = value[:80]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            sanitized[key] = [item[:80] for item in value[:10]]
    return sanitized


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
