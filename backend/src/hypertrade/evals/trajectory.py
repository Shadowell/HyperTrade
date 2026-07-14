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
    report = _dict(payload.get("report_json"))
    observability = _dict(state.get("observability"))
    usage = _dict(observability.get("usage"))
    planned_tool_names = _planned_tool_names(report.get("tool_calls"))
    trace_events = payload.get("trace_events")
    events = trace_events if isinstance(trace_events, list) else []
    raw_nodes = payload.get("node_runs") or payload.get("nodes") or report.get("nodes")
    nodes = raw_nodes if isinstance(raw_nodes, list) else []
    raw_evidence = payload.get("evidence") or report.get("evidence")
    evidence = raw_evidence if isinstance(raw_evidence, list) else []
    experiment = _dict(payload.get("experiment") or report.get("experiment"))
    validation = _dict(payload.get("validation") or report.get("validation"))
    return {
        "schema_version": "agent-evaluation-trajectory-v1",
        "case_id": case_id,
        "run_id": str(payload.get("id", "")),
        "status": str(payload.get("status", "")),
        "execution_mode": str(state.get("execution_mode", "standard")),
        # Baselines need aggregate quality/cost signals, never report content or
        # source text. Counts remain useful while preserving the eval boundary.
        "citation_count": _citation_count(report.get("citations")),
        "metrics": {
            "duration_ms": _number(observability.get("duration_ms")),
            "total_tokens": _integer(usage.get("total_tokens")),
        },
        "research_os": {
            "task_status": str(payload.get("task_status") or payload.get("status", "")),
            "nodes": [_safe_node(node) for node in nodes if isinstance(node, dict)],
            "evidence_types": sorted(
                {
                    str(item.get("evidence_type", item.get("type", "")))
                    for item in evidence
                    if isinstance(item, dict) and (item.get("evidence_type") or item.get("type"))
                }
            ),
            "experiment_fingerprint": str(experiment.get("fingerprint", ""))[:64],
            "validation_status": str(validation.get("final_status", validation.get("status", ""))),
        },
        "tool_calls": [
            tool_call
            for event in events
            if isinstance(event, dict)
            if (tool_call := _tool_call_from_event(event, planned_tool_names)) is not None
        ],
    }


def _safe_node(node: dict[str, Any]) -> dict[str, str | int]:
    attempt = node.get("attempt", 0)
    return {
        "node_key": str(node.get("node_key", ""))[:80],
        "role_key": str(node.get("role_key", ""))[:80],
        "status": str(node.get("status", ""))[:32],
        "attempt": max(0, int(attempt)) if isinstance(attempt, int) else 0,
    }


def _tool_call_from_event(
    event: dict[str, Any], planned_tool_names: set[str]
) -> dict[str, Any] | None:
    name = str(event.get("tool_name", ""))
    if planned_tool_names and name not in planned_tool_names:
        return None
    try:
        policy = ToolRegistry.default().get_for_runtime_name(name).policy
    except KeyError:
        return None
    output = _dict(event.get("output_json"))
    return {
        "name": name,
        "args": _safe_args(_dict(event.get("input_json"))),
        "execution_status": str(output.get("execution_status") or event.get("status", "")),
        "policy_outcome": str(output.get("policy_outcome", "")),
        "policy_scope": policy.scope,
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


def _planned_tool_names(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        str(item.get("tool", "")) for item in value if isinstance(item, dict) and item.get("tool")
    }


def _citation_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return max(0.0, round(float(value), 3))
    return None
