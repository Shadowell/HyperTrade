"""Offline Ragas scoring for sanitized isolated-evaluation trajectories."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
from pathlib import Path
from typing import Any


async def score_trajectories(
    references: list[dict[str, Any]],
    trajectories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score expected and observed tool trajectories with Ragas' deterministic metrics."""
    try:
        messages_module: Any = importlib.import_module("ragas.messages")
        metrics_module: Any = importlib.import_module("ragas.metrics.collections")
        AIMessage: Any = messages_module.AIMessage
        HumanMessage: Any = messages_module.HumanMessage
        ToolCall: Any = messages_module.ToolCall
        ToolCallAccuracy: Any = metrics_module.ToolCallAccuracy
        ToolCallF1: Any = metrics_module.ToolCallF1
    except ImportError as exc:
        raise RuntimeError(
            "Ragas is optional. Install it with `uv sync --extra agent-evals`."
        ) from exc

    trajectory_by_case = {
        str(trajectory.get("case_id", "")): trajectory for trajectory in trajectories
    }
    results: list[dict[str, Any]] = []
    for reference in references:
        case_id = str(reference.get("case_id", ""))
        trajectory = trajectory_by_case.get(case_id)
        if trajectory is None:
            results.append({"case_id": case_id, "status": "missing_trajectory"})
            continue
        include_arguments = bool(reference.get("compare_arguments", False))
        observed = _tool_calls(
            trajectory.get("tool_calls"),
            ToolCall=ToolCall,
            include_arguments=include_arguments,
        )
        expected = _tool_calls(
            reference.get("reference_tool_calls"),
            ToolCall=ToolCall,
            include_arguments=include_arguments,
        )
        messages: list[Any] = [
            HumanMessage(content=str(reference.get("prompt", ""))),
            AIMessage(content="", tool_calls=observed),
        ]
        accuracy = await ToolCallAccuracy().ascore(
            user_input=messages,
            reference_tool_calls=expected,
        )
        f1 = await ToolCallF1().ascore(
            user_input=messages,
            reference_tool_calls=expected,
        )
        results.append(
            {
                "case_id": case_id,
                "status": "scored",
                "execution_mode": str(trajectory.get("execution_mode", "")),
                "tool_call_accuracy": round(float(accuracy.value), 4),
                "tool_call_f1": round(float(f1.value), 4),
                "compare_arguments": include_arguments,
            }
        )
    return results


def _tool_calls(
    raw_calls: object,
    *,
    ToolCall: Any,
    include_arguments: bool,
) -> list[Any]:
    records = raw_calls if isinstance(raw_calls, list) else []
    calls: list[Any] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        name = str(record.get("name", ""))
        if not name:
            continue
        args = record.get("args") if include_arguments else {}
        calls.append(ToolCall(name=name, args=dict(args) if isinstance(args, dict) else {}))
    return calls


def _load_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"Expected a JSON list of objects: {path}")
    return [dict(item) for item in payload]


def main() -> int:
    parser = argparse.ArgumentParser(description="Score isolated Agent trajectories with Ragas.")
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--trajectories", required=True, type=Path)
    args = parser.parse_args()
    results = asyncio.run(
        score_trajectories(
            _load_records(args.reference),
            _load_records(args.trajectories),
        )
    )
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
