"""Candidate actions emitted by the read-only world-model snapshot."""

from __future__ import annotations

from typing import Any


def candidate_actions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return bounded L0/L1 actions; Sprint 71 never emits direct write actions."""
    status = str(snapshot.get("status", "partial"))
    missing_data = snapshot.get("missing_data")
    missing_count = len(missing_data) if isinstance(missing_data, list) else 0
    alerts = _list_value(snapshot.get("tool_health", {}).get("recent_alerts"))
    actions = [
        {
            "action_id": "observe_more",
            "level": "L0",
            "label": "Observe more cross-asset evidence",
            "reason": f"WorldState status is {status}; missing_data_count={missing_count}.",
            "requires_human_confirmation": False,
        },
        {
            "action_id": "run_monitor",
            "level": "L1",
            "label": "Run read-only monitor checks",
            "reason": "Refresh paper, connector, and strategy-library health before acting.",
            "requires_human_confirmation": False,
        },
        {
            "action_id": "inspect_trace",
            "level": "L1",
            "label": "Inspect latest Agent trace",
            "reason": "Use trace evidence to explain tool failures or stale state.",
            "requires_human_confirmation": False,
        },
        {
            "action_id": "request_human_confirmation",
            "level": "L1",
            "label": "Ask operator for confirmation",
            "reason": "Human confirmation is required before any execution-affecting action.",
            "requires_human_confirmation": True,
        },
    ]
    if alerts:
        actions.append(
            {
                "action_id": "pause_strategy_request",
                "level": "L1",
                "label": "Request strategy pause review",
                "reason": "Open monitor alerts exist; propose review only, do not pause.",
                "requires_human_confirmation": True,
            }
        )
    if snapshot.get("global_market", {}).get("risk_regime") in {"risk_off", "stress"}:
        actions.append(
            {
                "action_id": "reduce_risk_request",
                "level": "L1",
                "label": "Request risk-reduction review",
                "reason": "Risk regime is defensive; request review before any sizing change.",
                "requires_human_confirmation": True,
            }
        )
    return actions


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
