"""Rule-based portfolio scheduler view built from WorldState evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

PORTFOLIO_SCHEMA_VERSION = "portfolio_state.v1"


class PortfolioScheduler:
    """Build portfolio-level recommendations without allocation mutation."""

    def build(self, world_state: dict[str, Any]) -> dict[str, Any]:
        source_refs = _list_value(world_state.get("source_refs"))
        missing_evidence: list[str] = []
        strategies = _strategy_rows(world_state, missing_evidence)
        portfolio_state = _portfolio_state(
            world_state,
            strategies=strategies,
            missing_evidence=missing_evidence,
        )
        recommendations = _recommendations(
            portfolio_state=portfolio_state,
            missing_evidence=missing_evidence,
        )
        decision = recommendations[0] if recommendations else {}
        return {
            "schema_version": PORTFOLIO_SCHEMA_VERSION,
            "status": "completed",
            "portfolio_state": portfolio_state,
            "recommendations": recommendations,
            "decision": {
                "recommendation_type": decision.get(
                    "recommendation_type",
                    "increase_observation_frequency",
                ),
                "recommendation_id": decision.get("recommendation_id", "portfolio_rec_observe"),
                "score": decision.get("score", 0),
                "policy_status": decision.get("policy_status", "allowed_read_only"),
                "allocation_change_allowed": bool(
                    decision.get("allocation_change_allowed", False)
                ),
                "review_after": decision.get("review_after", "PT30M"),
                "expected_follow_up_evidence": decision.get(
                    "expected_follow_up_evidence",
                    [],
                ),
                "rationale": decision.get("rationale", ""),
            },
            "missing_evidence": _dedupe(missing_evidence),
            "source_refs": source_refs,
        }


def _portfolio_state(
    world_state: dict[str, Any],
    *,
    strategies: list[dict[str, Any]],
    missing_evidence: list[str],
) -> dict[str, Any]:
    global_market = _dict_value(world_state.get("global_market"))
    execution = _dict_value(world_state.get("execution"))
    open_positions = int(execution.get("open_position_count", 0) or 0)
    concentration_warnings: list[str] = []
    if open_positions >= 8:
        concentration_warnings.append("execution.open_position_count_high")
    if not strategies:
        missing_evidence.append("portfolio.strategy_evidence_unavailable")
    if global_market.get("cross_asset_signal") == "unknown":
        missing_evidence.append("portfolio.cross_asset_correlation_unavailable")
    return {
        "strategy_count": len(strategies),
        "strategies": strategies,
        "global_risk_regime": global_market.get("risk_regime", "unknown"),
        "execution_status": execution.get("status", "unknown"),
        "active_paper_status": _dict_value(execution.get("paper_session")).get(
            "status",
            "unknown",
        ),
        "open_position_count": open_positions,
        "correlation_proxy": _correlation_proxy(strategies),
        "concentration_warnings": concentration_warnings,
        "operator_limits": {
            "allocation_change_allowed": False,
            "live_write_allowed": False,
            "note": "Sprint 74 recommends review actions only; no live allocation mutation.",
        },
        "missing_evidence": _dedupe(missing_evidence),
    }


def _strategy_rows(
    world_state: dict[str, Any],
    missing_evidence: list[str],
) -> list[dict[str, Any]]:
    strategy_state = _dict_value(world_state.get("strategy"))
    recent_items = [
        item
        for item in _list_value(strategy_state.get("recent_items"))
        if isinstance(item, dict)
    ]
    rows: list[dict[str, Any]] = []
    for item in recent_items:
        tags = [str(tag) for tag in _list_value(item.get("tags"))]
        strategy_group = _strategy_group(tags) or str(item.get("memory_id", "unknown"))
        freshness = _freshness(str(item.get("created_at", "")))
        if freshness != "fresh":
            missing_evidence.append(f"portfolio.{strategy_group}.fresh_evidence_unavailable")
        rows.append(
            {
                "strategy_group": strategy_group,
                "allocation_or_risk_budget": "unknown",
                "evidence_freshness": freshness,
                "recent_performance": "strategy_memory_available",
                "drawdown": "unknown",
                "regime_fit": _regime_fit(world_state),
                "correlation_or_shared_exposure_proxy": "crypto_beta",
                "active_status_label": str(
                    world_state.get("execution", {}).get("status", "unknown")
                ),
                "source_memory_id": item.get("memory_id", "unknown"),
                "source_tool": item.get("source_tool", "unknown"),
            }
        )
    return rows


def _recommendations(
    *,
    portfolio_state: dict[str, Any],
    missing_evidence: list[str],
) -> list[dict[str, Any]]:
    risk_regime = str(portfolio_state.get("global_risk_regime", "unknown"))
    warnings = _list_value(portfolio_state.get("concentration_warnings"))
    missing_count = len(_dedupe(missing_evidence))
    recommendations = [
        _recommendation(
            "increase_observation_frequency",
            score=76 if missing_count else 54,
            rationale=(
                "Increase review cadence while cross-asset or strategy evidence "
                "is incomplete."
            ),
            missing_count=missing_count,
        ),
        _recommendation(
            "run_targeted_backtest_or_experiment",
            score=68 if missing_count else 48,
            rationale="Refresh strategy evidence before any allocation change.",
            missing_count=missing_count,
            review_after="PT4H",
        ),
        _recommendation(
            "request_human_review_before_allocation_change",
            score=64 if missing_count else 42,
            rationale="Ask the operator to confirm portfolio limits before allocation changes.",
            missing_count=missing_count,
            requires_confirmation=True,
            review_after="PT30M",
        ),
        _recommendation(
            "keep_allocation",
            score=58 if not missing_count and not warnings else 38,
            rationale="Keep allocation unchanged while no stronger source-bound signal exists.",
            missing_count=missing_count,
            review_after="PT30M",
        ),
    ]
    if risk_regime in {"risk_off", "stress"} or warnings:
        recommendations.extend(
            [
                _recommendation(
                    "reduce_strategy_risk_budget_request",
                    score=52,
                    rationale=(
                        "Request a defensive risk-budget review; do not execute "
                        "allocation changes."
                    ),
                    missing_count=missing_count,
                    requires_confirmation=True,
                    policy_status="requires_human_confirmation",
                    review_after="PT15M",
                ),
                _recommendation(
                    "pause_strategy_request",
                    score=48,
                    rationale="Request a pause review only if operator confirms degraded evidence.",
                    missing_count=missing_count,
                    requires_confirmation=True,
                    policy_status="requires_human_confirmation",
                    review_after="PT15M",
                ),
            ]
        )
    recommendations.sort(key=lambda row: (-float(row["score"]), str(row["recommendation_type"])))
    for rank, recommendation in enumerate(recommendations, start=1):
        recommendation["rank"] = rank
    return recommendations


def _recommendation(
    recommendation_type: str,
    *,
    score: float,
    rationale: str,
    missing_count: int,
    requires_confirmation: bool = False,
    policy_status: str = "allowed_read_only",
    review_after: str = "PT1H",
) -> dict[str, Any]:
    return {
        "recommendation_id": f"portfolio_rec_{recommendation_type}",
        "recommendation_type": recommendation_type,
        "score": round(score - min(10, missing_count * 1.5), 3),
        "expected_benefit": round(0.7 if missing_count else 0.52, 3),
        "downside": round(0.06 if recommendation_type != "keep_allocation" else 0.18, 3),
        "confidence": round(max(0.35, 0.72 - missing_count * 0.04), 3),
        "data_gap_penalty": round(min(1.0, missing_count / 8), 3),
        "policy_status": policy_status,
        "requires_human_confirmation": requires_confirmation,
        "allocation_change_allowed": False,
        "review_after": review_after,
        "expected_follow_up_evidence": [
            "fresh strategy evidence",
            "paper execution status",
            "cross-asset regime evidence",
        ],
        "rationale": rationale,
    }


def _strategy_group(tags: list[str]) -> str:
    for tag in tags:
        if tag.startswith("strategy:"):
            return tag.removeprefix("strategy:") or "unknown"
    return ""


def _freshness(created_at: str) -> str:
    if not created_at:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(created_at)
    except ValueError:
        return "unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - parsed).days
    return "fresh" if age_days <= 7 else "stale"


def _regime_fit(world_state: dict[str, Any]) -> str:
    risk_regime = str(world_state.get("global_market", {}).get("risk_regime", "unknown"))
    if risk_regime == "risk_on":
        return "favorable"
    if risk_regime in {"risk_off", "stress"}:
        return "defensive"
    if risk_regime == "mixed":
        return "neutral"
    return "unknown"


def _correlation_proxy(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    if not strategies:
        return {"status": "insufficient_data", "proxy": "none"}
    if len(strategies) == 1:
        return {"status": "single_strategy", "proxy": "crypto_beta"}
    return {
        "status": "shared_exposure_warning",
        "proxy": "all strategies currently share crypto beta exposure",
    }


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
