"""Scenario templates for bounded WorldState candidate actions."""

from __future__ import annotations

from typing import Any

from hypertrade.world_model.scoring import ActionScorer


class ScenarioSimulator:
    """Compare safe operator actions against the current WorldState."""

    def __init__(self, scorer: ActionScorer | None = None) -> None:
        self.scorer = scorer or ActionScorer()

    def simulate(
        self,
        world_state: dict[str, Any],
        candidate_actions: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        source_refs = _list_value(world_state.get("source_refs"))
        actions = _normalized_actions(candidate_actions or [])
        scenarios: list[dict[str, Any]] = []
        for action in actions:
            action_id = str(action.get("action_id", "observe_more"))
            template = _ACTION_TEMPLATES.get(action_id, _ACTION_TEMPLATES["observe_more"])
            score = self.scorer.score(world_state, action)
            scenarios.append(
                {
                    "action_id": action_id,
                    "action_level": str(action.get("level", template["level"])),
                    "label": str(action.get("label", template["label"])),
                    "reason": str(action.get("reason", template["reason"])),
                    "affected_state_domains": _template_list(
                        template,
                        "affected_state_domains",
                    ),
                    "requires_human_confirmation": bool(
                        action.get(
                            "requires_human_confirmation",
                            template["requires_human_confirmation"],
                        )
                    ),
                    "review_after": str(template["review_after"]),
                    "expected_follow_up_evidence": _template_list(
                        template,
                        "expected_follow_up_evidence",
                    ),
                    "source_refs": source_refs,
                    **score,
                }
            )
        scenarios.sort(key=lambda item: (-float(item["score"]), str(item["action_id"])))
        for rank, scenario in enumerate(scenarios, start=1):
            scenario["rank"] = rank
        return scenarios


_ACTION_TEMPLATES: dict[str, dict[str, object]] = {
    "observe_more": {
        "level": "L0",
        "label": "Observe more evidence",
        "reason": "Collect missing cross-asset and freshness evidence.",
        "affected_state_domains": ["global_market", "missing_data"],
        "requires_human_confirmation": False,
        "review_after": "PT30M",
        "expected_follow_up_evidence": [
            "global_market cross-asset feed status",
            "latest OKX market breadth",
        ],
    },
    "hold": {
        "level": "L0",
        "label": "Hold current state",
        "reason": "Avoid changing risk until evidence changes.",
        "affected_state_domains": ["execution", "strategy"],
        "requires_human_confirmation": False,
        "review_after": "PT15M",
        "expected_follow_up_evidence": [
            "paper session health",
            "market breadth drift",
        ],
    },
    "run_monitor": {
        "level": "L1",
        "label": "Run read-only monitor checks",
        "reason": "Refresh monitor state and alert evidence.",
        "affected_state_domains": ["tool_health", "execution", "strategy"],
        "requires_human_confirmation": False,
        "review_after": "PT10M",
        "expected_follow_up_evidence": [
            "monitor alert list",
            "paper monitor snapshot",
            "connector health",
        ],
    },
    "inspect_trace": {
        "level": "L1",
        "label": "Inspect latest Agent trace",
        "reason": "Audit recent tool behavior before recommendation.",
        "affected_state_domains": ["deployment", "tool_health"],
        "requires_human_confirmation": False,
        "review_after": "PT10M",
        "expected_follow_up_evidence": [
            "latest AgentRun trace",
            "tool failure details",
        ],
    },
    "request_human_confirmation": {
        "level": "L1",
        "label": "Request operator confirmation",
        "reason": "Escalate uncertainty before any execution-affecting action.",
        "affected_state_domains": ["risk_boundary", "execution"],
        "requires_human_confirmation": True,
        "review_after": "PT5M",
        "expected_follow_up_evidence": [
            "operator approval or rejection",
            "confirmed action scope",
        ],
    },
    "pause_strategy_request": {
        "level": "L1",
        "label": "Request strategy pause review",
        "reason": "Ask the operator to review a defensive pause, without executing it.",
        "affected_state_domains": ["strategy", "execution", "risk_boundary"],
        "requires_human_confirmation": True,
        "review_after": "PT5M",
        "expected_follow_up_evidence": [
            "operator confirmation",
            "strategy health evidence",
            "paper/live boundary check",
        ],
    },
    "reduce_risk_request": {
        "level": "L1",
        "label": "Request risk-reduction review",
        "reason": "Ask the operator to review risk reduction, without changing exposure.",
        "affected_state_domains": ["global_market", "execution", "risk_boundary"],
        "requires_human_confirmation": True,
        "review_after": "PT5M",
        "expected_follow_up_evidence": [
            "operator confirmation",
            "cross-asset risk evidence",
            "current exposure evidence",
        ],
    },
}


def _normalized_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {
        action_id: {"action_id": action_id, **dict(template)}
        for action_id, template in _ACTION_TEMPLATES.items()
    }
    for action in actions:
        action_id = str(action.get("action_id", "")).strip()
        if not action_id:
            continue
        existing = merged.get(action_id, {"action_id": action_id})
        existing.update(action)
        merged[action_id] = existing
    return [merged[action_id] for action_id in _ACTION_TEMPLATES]


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _template_list(template: dict[str, object], key: str) -> list[Any]:
    value = template.get(key, [])
    return list(value) if isinstance(value, list) else []
