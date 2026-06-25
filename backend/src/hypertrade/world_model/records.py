"""Decision record helpers for WorldState scenario recommendations."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from hypertrade.db import utc_now


def build_decision_record(
    world_state: dict[str, Any],
    action_scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    state_hash = world_state_hash(world_state)
    selected = action_scenarios[0] if action_scenarios else {}
    selected_action_id = str(selected.get("action_id", "observe_more"))
    return {
        "decision_id": f"wmdec_{state_hash[:16]}",
        "created_at": utc_now().isoformat(),
        "world_state_id": str(world_state.get("source_id", "world_model:latest")),
        "world_state_hash": state_hash,
        "selected_action_id": selected_action_id,
        "selected_action_level": str(selected.get("action_level", "L0")),
        "selected_score": selected.get("score", 0),
        "policy_status": str(selected.get("policy_status", "allowed_read_only")),
        "policy_result": selected.get("policy_result", {}),
        "human_confirmation_required": bool(
            selected.get("requires_human_confirmation", False)
        ),
        "review_after": str(selected.get("review_after", "PT30M")),
        "expected_follow_up_evidence": _list_value(
            selected.get("expected_follow_up_evidence")
        ),
        "alternatives_count": max(0, len(action_scenarios) - 1),
        "action_scenario_count": len(action_scenarios),
        "decision_basis": "deterministic_action_scenario_score",
        "rationale": _rationale(selected),
        "source_refs": _list_value(world_state.get("source_refs")),
    }


def world_state_hash(world_state: dict[str, Any]) -> str:
    payload = {
        key: value
        for key, value in world_state.items()
        if key not in {"action_scenarios", "decision"}
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _rationale(selected: dict[str, Any]) -> str:
    action_id = str(selected.get("action_id", "observe_more"))
    score = selected.get("score", "n/a")
    policy_status = selected.get("policy_status", "unknown")
    return (
        f"Selected {action_id} because it has the highest deterministic "
        f"scenario score ({score}) with policy_status={policy_status}."
    )


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []
