"""Promptfoo target for an explicitly isolated HyperTrade evaluation stack."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, str]:
    """Run a prompt against an isolated API and return only policy-safe evidence."""
    del options, context
    if os.getenv("HYPERTRADE_EVAL_TARGET") != "isolated":
        return {"error": "Set HYPERTRADE_EVAL_TARGET=isolated before running Promptfoo."}
    base_url = os.getenv("HYPERTRADE_EVAL_BASE_URL", "").rstrip("/")
    if not base_url:
        return {"error": "Set HYPERTRADE_EVAL_BASE_URL to an isolated API target."}
    if not _is_loopback(base_url) and os.getenv("HYPERTRADE_EVAL_ALLOW_REMOTE") != "true":
        return {"error": "Non-loopback targets require HYPERTRADE_EVAL_ALLOW_REMOTE=true."}
    request = Request(
        f"{base_url}/api/agent/runs",
        data=json.dumps({"prompt": prompt, "evaluation_mode": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:  # noqa: S310 - explicit operator target
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": f"isolated target request failed: {type(exc).__name__}"}
    if not isinstance(payload, dict):
        return {"error": "isolated target returned a non-object response"}
    return {"output": json.dumps(_safe_projection(payload), ensure_ascii=False)}


def _safe_projection(payload: dict[str, Any]) -> dict[str, Any]:
    events = payload.get("trace_events")
    traces = events if isinstance(events, list) else []
    tool_calls: list[dict[str, str]] = []
    for event in traces:
        if not isinstance(event, dict):
            continue
        name = str(event.get("tool_name", ""))
        if not name or name.startswith("graph."):
            continue
        output = event.get("output_json")
        result = output if isinstance(output, dict) else {}
        policy = result.get("policy")
        policy_data = policy if isinstance(policy, dict) else {}
        tool_calls.append(
            {
                "name": name,
                "execution_status": str(result.get("execution_status", event.get("status", ""))),
                "policy_scope": str(policy_data.get("scope", "")),
            }
        )
    state = payload.get("run_state_json")
    run_state = state if isinstance(state, dict) else {}
    report = payload.get("report_json")
    report_json = report if isinstance(report, dict) else {}
    return {
        "status": str(payload.get("status", "")),
        "agent_status": str(report_json.get("status", "completed")),
        "execution_mode": str(run_state.get("execution_mode", "")),
        "tool_calls": tool_calls,
    }


def _is_loopback(base_url: str) -> bool:
    return base_url.startswith("http://127.0.0.1") or base_url.startswith("http://localhost")
