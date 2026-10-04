"""Selection-bias receipts derived from persisted ARC trial history.

The research family is all candidate searches on the same target, symbol basket,
timeframes and frozen windows. Restarting a mission or changing a model-supplied
family name cannot reset its counter. Baselines and exact retries are not new trials.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace
from statistics import variance
from typing import Any

from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.self_test import SelfTestResult
from hypertrade.arc.store import get_controller, list_mission_ids
from hypertrade.research.sharpe import calculate_deflated_sharpe_ratio

MIN_DSR_PROBABILITY = 0.95


def _family(goal: ARCGoalV1) -> str:
    value = [
        goal.platform,
        sorted(goal.symbols),
        sorted(goal.timeframes),
        goal.research_windows.model_dump(mode="json") if goal.research_windows else None,
    ]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _trial(attempt: ARCCandidateAttemptV1) -> str:
    # Source variants share code, but their actual parameter/config mutations differ.
    spec = attempt.strategy_spec
    value = [
        attempt.strategy_code,
        {
            key: spec.get(key)
            for key in (
                "parameter_changes",
                "structural_changes",
                "tunable_parameters",
                "timeframe",
                "symbols",
                "symbol",
                "parent_manifest_sha256",
                "parent_execution_identity_sha256",
            )
        },
    ]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _statistics(metrics: dict[str, Any]) -> dict[str, Any] | None:
    stats = metrics.get("return_statistics")
    if not isinstance(stats, dict) or stats.get("status") != "observed":
        return None
    try:
        if (
            stats.get("schema_version") != "return_statistics.v1"
            or len(stats.get("series_sha256", "")) != 64
            or isinstance(stats["sample_length"], bool)
            or int(stats["sample_length"]) != stats["sample_length"]
            or stats["sample_length"] < 4
            or float(stats["period_seconds"]) <= 0
            or not all(
                math.isfinite(float(stats[k]))
                for k in ("period_seconds", "period_sharpe", "skewness", "kurtosis")
            )
        ):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return stats


def selection_evidence(
    controller: ARCController, candidate: ARCCandidateAttemptV1, metrics: dict[str, Any]
) -> dict[str, Any]:
    goal = controller.projection.goal
    assert goal is not None
    family = _family(goal)
    trials: dict[str, dict[str, Any] | None] = {}
    refs: dict[str, str] = {}
    controllers = {controller.mission_id: controller}
    for mission_id in list_mission_ids():
        if mission_id != controller.mission_id:
            other = get_controller(mission_id)
            if (
                other is not None
                and other.projection.goal is not None
                and _family(other.projection.goal) == family
            ):
                controllers[mission_id] = other
    for owner in controllers.values():
        attempts = {item.attempt_id: item for item in owner.projection.attempts}
        for event in owner.projection.events:
            payload = event.payload
            attempt = attempts.get(str(payload.get("attempt_id")))
            if attempt is None or attempt.attempt_id.startswith("baseline_"):
                continue
            key = _trial(attempt)
            if event.event_type in {
                "avo_development_requested",
                "avo_final_requested",
                "red_team_tested",
            }:
                trials.setdefault(key, None)
            if event.event_type == "red_team_tested":
                replay_metrics = payload.get("metrics") or {}
                observed = _statistics(replay_metrics)
                if (
                    observed is not None
                    and replay_metrics.get("evidence_available") is True
                    and replay_metrics.get("ranking_basis") == "out_of_sample"
                    and payload.get("code_sha256")
                    == hashlib.sha256(attempt.strategy_code.encode()).hexdigest()
                ):
                    trials[key] = observed
                    refs[key] = "arc-event:" + event.event_id
            if event.event_type not in {"avo_development_result", "bitpro_self_tested"}:
                continue
            trials.setdefault(key, None)
            receipt = payload.get("result", payload)
            code_hash = hashlib.sha256(attempt.strategy_code.encode()).hexdigest()
            if not receipt.get("backtest_id") or receipt.get("code_sha256") != code_hash:
                continue
            # The search distribution uses development returns, never other candidates'
            # final holdout results. That would turn the holdout into another search set.
            if event.event_type == "avo_development_result":
                observed = _statistics(receipt.get("metrics") or {})
                if observed is not None:
                    trials[key] = observed
                    refs[key] = str(receipt["backtest_id"])
    current = _trial(candidate)
    trials.setdefault(current, None)
    evidence: dict[str, Any] = {
        "schema_version": "selection_bias.v1",
        "status": "unknown",
        "family_id": family,
        "num_trials": len(trials),
        "count_source": "arc_persisted_trial_events",
        "trial_refs": [refs[key] for key in sorted(refs)],
        "minimum_probability": MIN_DSR_PROBABILITY,
    }
    selected = _statistics(metrics)
    if selected is None:
        return {**evidence, "reason": "return_statistics_missing"}
    # A genuinely single immutable trial needs no cross-trial variance. Multi-trial
    # searches must disclose every development result, including negative results.
    if len(trials) == 1 and trials[current] is None:
        trials[current] = selected
    if any(value is None for value in trials.values()):
        return {**evidence, "reason": "trial_statistics_incomplete"}
    observations = [value for value in trials.values() if value is not None]
    if any(value["period_seconds"] != selected["period_seconds"] for value in observations):
        return {**evidence, "reason": "return_frequency_mismatch"}
    dispersion = (
        variance(float(value["period_sharpe"]) for value in observations)
        if len(trials) > 1
        else 0.0
    )
    try:
        probability = calculate_deflated_sharpe_ratio(
            float(selected["period_sharpe"]),
            len(trials),
            sample_length=int(selected["sample_length"]),
            skewness=float(selected["skewness"]),
            kurtosis=float(selected["kurtosis"]),
            trial_sharpe_variance=dispersion,
        )
    except ValueError:
        return {**evidence, "reason": "invalid_return_statistics"}
    return {
        **evidence,
        "status": "observed",
        "probability": probability,
        "trial_sharpe_variance": dispersion,
        "selected_series_sha256": selected["series_sha256"],
    }


def enforce_selection_gate(
    controller: ARCController, candidate: ARCCandidateAttemptV1, result: SelfTestResult
) -> SelfTestResult:
    """Run in orchestration so injected experiment clients cannot bypass the referee."""
    evidence = selection_evidence(controller, candidate, result.metrics)
    reason = None
    if evidence["status"] != "observed":
        reason = "deflated_sharpe_unknown:" + evidence["reason"]
    elif evidence["probability"] < MIN_DSR_PROBABILITY:
        reason = "deflated_sharpe_probability_below_0.95"
    return replace(
        result,
        passed=result.passed and reason is None,
        validation_id=result.validation_id if reason is None else None,
        metrics={**result.metrics, "selection_bias": evidence},
        reasons=list(result.reasons) + ([reason] if reason else []),
        message="; ".join(list(result.reasons) + [reason]) if reason else result.message,
    )
