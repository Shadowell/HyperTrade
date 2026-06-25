"""Deterministic action scoring for WorldState scenario comparisons."""

from __future__ import annotations

from typing import Any


class ActionScorer:
    """Score bounded candidate actions without LLM reasoning or side effects."""

    def score(self, world_state: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
        action_id = str(action.get("action_id", "unknown"))
        profile = _ACTION_PROFILES.get(action_id, _ACTION_PROFILES["observe_more"])
        missing_count = len(_list_value(world_state.get("missing_data")))
        risk_regime = str(world_state.get("global_market", {}).get("risk_regime", "unknown"))
        tool_health = str(world_state.get("tool_health", {}).get("status", "unknown"))
        alert_count = int(world_state.get("tool_health", {}).get("recent_alert_count", 0) or 0)

        expected_benefit = _expected_benefit(
            action_id=action_id,
            base=_profile_float(profile, "expected_benefit"),
            missing_count=missing_count,
            risk_regime=risk_regime,
            tool_health=tool_health,
            alert_count=alert_count,
        )
        downside = _downside(
            action_id=action_id,
            base=_profile_float(profile, "downside"),
            risk_regime=risk_regime,
            missing_count=missing_count,
        )
        confidence = _confidence(
            action_id=action_id,
            base=_profile_float(profile, "confidence"),
            missing_count=missing_count,
            alert_count=alert_count,
        )
        data_gap_penalty = _data_gap_penalty(action_id=action_id, missing_count=missing_count)
        reversibility = _profile_float(profile, "reversibility")
        execution_complexity = _profile_float(profile, "execution_complexity")
        requires_confirmation = bool(action.get("requires_human_confirmation"))
        policy_status = _policy_status(
            action_id=action_id,
            requires_confirmation=requires_confirmation,
            missing_count=missing_count,
        )
        policy_score = {
            "allowed_read_only": 1.0,
            "requires_human_confirmation": 0.72,
            "blocked_risk_increasing_until_confirmed": 0.22,
        }[policy_status]
        raw_score = (
            expected_benefit * 28
            + confidence * 18
            + reversibility * 14
            + policy_score * 12
            - downside * 18
            - data_gap_penalty * 8
            - execution_complexity * 8
            - (4 if requires_confirmation else 0)
        )
        return {
            "expected_benefit": {
                "score": round(expected_benefit, 3),
                "rationale": str(profile["benefit_rationale"]),
            },
            "downside": {
                "score": round(downside, 3),
                "rationale": str(profile["downside_rationale"]),
            },
            "confidence": round(confidence, 3),
            "data_gap_penalty": round(data_gap_penalty, 3),
            "reversibility": round(reversibility, 3),
            "execution_complexity": round(execution_complexity, 3),
            "policy_status": policy_status,
            "policy_result": {
                "status": policy_status,
                "reason": _policy_reason(policy_status),
            },
            "score": round(raw_score, 3),
        }


_ACTION_PROFILES: dict[str, dict[str, object]] = {
    "observe_more": {
        "expected_benefit": 0.62,
        "downside": 0.04,
        "confidence": 0.7,
        "reversibility": 1.0,
        "execution_complexity": 0.04,
        "benefit_rationale": "Improves evidence quality before any execution-affecting decision.",
        "downside_rationale": "No trading side effect; opportunity cost is the main downside.",
    },
    "hold": {
        "expected_benefit": 0.42,
        "downside": 0.2,
        "confidence": 0.58,
        "reversibility": 0.84,
        "execution_complexity": 0.02,
        "benefit_rationale": "Keeps current state unchanged while preserving optionality.",
        "downside_rationale": "Can leave risk unchanged when regime evidence worsens.",
    },
    "run_monitor": {
        "expected_benefit": 0.58,
        "downside": 0.06,
        "confidence": 0.68,
        "reversibility": 0.96,
        "execution_complexity": 0.18,
        "benefit_rationale": "Refreshes read-only monitor evidence and alert state.",
        "downside_rationale": "No trading side effect; costs time and tool budget.",
    },
    "inspect_trace": {
        "expected_benefit": 0.48,
        "downside": 0.03,
        "confidence": 0.72,
        "reversibility": 1.0,
        "execution_complexity": 0.1,
        "benefit_rationale": "Explains recent Agent/tool behavior from persisted trace evidence.",
        "downside_rationale": "No execution side effect; may not refresh stale market evidence.",
    },
    "request_human_confirmation": {
        "expected_benefit": 0.66,
        "downside": 0.03,
        "confidence": 0.74,
        "reversibility": 0.9,
        "execution_complexity": 0.24,
        "benefit_rationale": "Escalates uncertainty to the operator before any sensitive action.",
        "downside_rationale": "Adds operator latency but preserves risk boundaries.",
    },
    "pause_strategy_request": {
        "expected_benefit": 0.38,
        "downside": 0.32,
        "confidence": 0.56,
        "reversibility": 0.7,
        "execution_complexity": 0.46,
        "benefit_rationale": "May reduce simulated strategy drift after alerts are reviewed.",
        "downside_rationale": "Could interrupt validation if evidence is incomplete.",
    },
    "reduce_risk_request": {
        "expected_benefit": 0.34,
        "downside": 0.42,
        "confidence": 0.52,
        "reversibility": 0.62,
        "execution_complexity": 0.58,
        "benefit_rationale": "May lower exposure if confirmed during a defensive regime.",
        "downside_rationale": "Can reduce upside or alter risk without enough global evidence.",
    },
}


def _expected_benefit(
    *,
    action_id: str,
    base: float,
    missing_count: int,
    risk_regime: str,
    tool_health: str,
    alert_count: int,
) -> float:
    value = base
    if action_id in {"observe_more", "request_human_confirmation"} and missing_count >= 4:
        value += 0.16
    if action_id == "run_monitor" and (tool_health != "healthy" or alert_count > 0):
        value += 0.14
    if action_id in {"pause_strategy_request", "reduce_risk_request"}:
        if risk_regime in {"risk_off", "stress"} or alert_count > 0:
            value += 0.22
        if missing_count >= 4:
            value -= 0.1
    return _clamp(value)


def _downside(
    *,
    action_id: str,
    base: float,
    risk_regime: str,
    missing_count: int,
) -> float:
    value = base
    if action_id == "hold" and risk_regime in {"risk_off", "stress"}:
        value += 0.16
    if action_id in {"pause_strategy_request", "reduce_risk_request"} and missing_count >= 4:
        value += 0.18
    return _clamp(value)


def _confidence(
    *,
    action_id: str,
    base: float,
    missing_count: int,
    alert_count: int,
) -> float:
    value = base - min(0.22, missing_count * 0.025)
    if action_id in {"observe_more", "inspect_trace", "request_human_confirmation"}:
        value += 0.08
    if action_id == "run_monitor" and alert_count > 0:
        value += 0.06
    return _clamp(value)


def _data_gap_penalty(*, action_id: str, missing_count: int) -> float:
    base = min(1.0, missing_count / 10)
    if action_id in {"observe_more", "request_human_confirmation"}:
        return round(base * 0.2, 3)
    if action_id in {"run_monitor", "inspect_trace"}:
        return round(base * 0.35, 3)
    if action_id == "hold":
        return round(base * 0.55, 3)
    return round(base * 0.9, 3)


def _policy_status(
    *,
    action_id: str,
    requires_confirmation: bool,
    missing_count: int,
) -> str:
    if action_id in {"pause_strategy_request", "reduce_risk_request"} and missing_count >= 4:
        return "blocked_risk_increasing_until_confirmed"
    if requires_confirmation:
        return "requires_human_confirmation"
    return "allowed_read_only"


def _policy_reason(policy_status: str) -> str:
    if policy_status == "allowed_read_only":
        return "Scenario evaluation is read-only and does not call mutation tools."
    if policy_status == "requires_human_confirmation":
        return "Recommendation requires explicit operator confirmation before action."
    return "Data gaps block any risk-changing recommendation until operator review."


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _profile_float(profile: dict[str, object], key: str) -> float:
    value = profile.get(key, 0.0)
    return float(value) if isinstance(value, int | float | str) else 0.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
