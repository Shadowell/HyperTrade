"""Deterministic one-step parameter neighbours for rule_tweak missions.

A mission whose goal names `RULE_TWEAK_PROVIDER` is driven by this provider instead of a
model: it proposes single-parameter neighbours of the running source, develops them and
finishes the best one. It returns tool calls only, so every effect still runs through the
audited AVO loop and stays budgeted, journalled and reviewed like model research.
"""

from __future__ import annotations

import hashlib
import math
from typing import TYPE_CHECKING, Any

from hypertrade.arc.contracts import RULE_TWEAK_PROVIDER
from hypertrade.arc.relay_seats import tried_variant
from hypertrade.arc.self_test import _fraction, _number
from hypertrade.providers.chat import ChatResponse, ToolCallRequest

if TYPE_CHECKING:
    from hypertrade.arc.controller import ARCController

RULE_TWEAK_MODEL = "parameter-neighbours-v1"
STEP_FRACTION = 0.2
ZERO_STEP_FRACTION = 0.1
FINAL_RESERVE = 2

_NESTED_PREFIX = "research_parameters."
# Mirrors BitPro's `validate_parameter_changes` (contract strategy_research_variant_policy.v1).
# BitPro validates the *effective* value of every pair, so a neighbour that would break one of
# these rules is rejected at variant-creation time; the AVO loop would then record an unknown
# effect and stall the mission, so such a neighbour must never be proposed.
_ORDERING_PAIRS = (
    ("fast_window", "slow_window"),
    ("fast_window", "mid_window"),
    ("mid_window", "slow_window"),
    ("trend_fast_period", "trend_slow_period"),
    ("trend_fast_ema", "trend_slow_ema"),
    ("mom_fast_window_bars", "mom_slow_window_bars"),
    ("ret_fast_window_bars", "ret_slow_window_bars"),
    ("research_parameters.fast_window", "research_parameters.slow_window"),
)
_MOMENTUM_EXIT_KEY = "momentum_exit_min_abs_pct"
_MOMENTUM_ENTER_KEY = "momentum_enter_min_abs_pct"


def _current_value(baseline_config: dict[str, Any], key: str) -> Any:
    if key.startswith(_NESTED_PREFIX):
        nested = baseline_config.get("research_parameters")
        if not isinstance(nested, dict):
            return None
        return nested.get(key[len(_NESTED_PREFIX) :])
    return baseline_config.get(key)


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _effective(
    baseline_config: dict[str, Any], changes: dict[str, int | float], key: str
) -> float | None:
    if key in changes:
        return _finite_number(changes[key])
    return _finite_number(_current_value(baseline_config, key))


def _violates_bitpro_rules(
    baseline_config: dict[str, Any], changes: dict[str, int | float]
) -> bool:
    for first, second in _ORDERING_PAIRS:
        first_value = _effective(baseline_config, changes, first)
        second_value = _effective(baseline_config, changes, second)
        if first_value is None or second_value is None:
            continue
        if first_value >= second_value:
            return True
    exit_threshold = _effective(baseline_config, changes, _MOMENTUM_EXIT_KEY)
    enter_threshold = _effective(baseline_config, changes, _MOMENTUM_ENTER_KEY)
    return (
        exit_threshold is not None
        and enter_threshold is not None
        and exit_threshold > enter_threshold
    )


def parameter_neighbours(
    policy: dict[str, Any], baseline_config: dict[str, Any], *, seed: str
) -> list[dict[str, int | float]]:
    """One-step parameter neighbours of the baseline, rotated by a deterministic seed."""
    parameters = policy.get("authorized_parameters") if isinstance(policy, dict) else None
    if not isinstance(parameters, list) or not isinstance(baseline_config, dict):
        return []
    ordered: list[dict[str, int | float]] = []
    entries = sorted(
        (entry for entry in parameters if isinstance(entry, dict)),
        key=lambda entry: str(entry.get("key") or entry.get("name") or ""),
    )
    for entry in entries:
        key = str(entry.get("key") or entry.get("name") or "")
        if not key:
            continue
        current = _finite_number(_current_value(baseline_config, key))
        if current is None:
            continue
        minimum = _finite_number(entry.get("min", entry.get("minimum")))
        maximum = _finite_number(entry.get("max", entry.get("maximum")))
        integral = str(entry.get("type") or "").lower() in {"int", "integer"}
        if integral:
            step = float(max(1, round(abs(current) * STEP_FRACTION)))
        elif current == 0:
            if minimum is None or maximum is None:
                continue
            step = (maximum - minimum) * ZERO_STEP_FRACTION
        else:
            step = abs(current) * STEP_FRACTION
        candidates: list[int | float] = []
        for offset in (current + step, current - step):
            if minimum is not None:
                offset = max(offset, minimum)
            if maximum is not None:
                offset = min(offset, maximum)
            value: int | float = int(offset) if integral else round(offset, 10)
            if value == current or value in candidates:
                continue
            candidates.append(value)
        for value in candidates:
            changes: dict[str, int | float] = {key: value}
            if _violates_bitpro_rules(baseline_config, changes):
                continue
            if tried_variant(policy.get("relay"), changes, {}) is not None:
                continue
            ordered.append(changes)
    if not ordered:
        return []
    offset = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(ordered)
    return ordered[offset:] + ordered[:offset]


def _evidence_refs(context: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    report = context.get("attribution_report")
    if isinstance(report, dict):
        dimensions = report.get("dimensions")
        report_id = report.get("report_id")
        if isinstance(dimensions, dict) and dimensions and isinstance(report_id, str) and report_id:
            refs.append(f"attribution:{report_id}:{sorted(dimensions)[0]}")
    if context.get("paper_feedback"):
        refs.append("paper_feedback")
    else:
        orders = context.get("orders")
        sample_count = orders.get("sample_count") if isinstance(orders, dict) else None
        if (
            isinstance(sample_count, (int, float))
            and not isinstance(sample_count, bool)
            and sample_count > 0
        ):
            refs.append("order_sample")
    return refs


class RuleTweakProvider:
    """Deterministic ChatProvider that only ever returns one AVO tool call."""

    name = RULE_TWEAK_PROVIDER
    model = RULE_TWEAK_MODEL

    def __init__(self, controller: ARCController) -> None:
        self.controller = controller

    @staticmethod
    def _call(projection: Any, name: str, arguments: dict[str, Any]) -> ChatResponse:
        return ChatResponse(
            content="",
            tool_calls=[
                ToolCallRequest(f"rt_{len(projection.events)}_0", name, arguments),
            ],
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        # Never read `messages`: the decision is a function of committed mission state.
        projection = self.controller.projection
        goal = projection.goal
        if goal is None:
            return self._call(projection, "stop", {"reason": "rule_tweak: mission goal is missing"})
        budget = goal.budget
        avo = projection.avo
        development = avo.get("development") or {}
        dev_left = budget.max_backtests - budget.backtests_used - FINAL_RESERVE
        requested = [
            (event.payload.get("arguments") or {}).get("parameter_changes")
            for event in projection.events
            if event.event_type == "avo_tool_requested"
            and event.payload.get("name") == "propose"
        ]
        finish_requested = any(
            event.event_type == "avo_tool_requested" and event.payload.get("name") == "finish"
            for event in projection.events
        )
        context = goal.evolution_context or {}
        policy = context.get("variant_policy") or {}
        baseline_spec = (context.get("baseline") or {}).get("strategy_spec") or {}
        baseline_config = baseline_spec.get("baseline_config") or {}
        untried = [
            changes
            for changes in parameter_neighbours(
                policy, baseline_config, seed=projection.mission_id
            )
            if changes not in requested
        ]

        for attempt in projection.attempts:
            if attempt.attempt_id not in development and dev_left >= 1:
                return self._call(projection, "develop", {"attempt_id": attempt.attempt_id})

        if budget.candidates_used < budget.max_candidates and dev_left >= 1 and untried:
            changes = untried[0]
            refs = _evidence_refs(context)
            if not refs:
                return self._call(
                    projection,
                    "stop",
                    {"reason": "rule_tweak: no citable evidence for a hypothesis"},
                )
            key, value = next(iter(changes.items()))
            current = _current_value(baseline_config, key)
            return self._call(
                projection,
                "propose",
                {
                    "hypothesis": (
                        f"规则微调：{key} 从 {current} 调到 {value}"
                        "（单参数一步，约20%），检验同窗净收益是否改善"
                    ),
                    "parameter_changes": changes,
                    "evolution_hypothesis": {
                        "evidence_refs": refs,
                        "expected_metric": "net_return",
                        "expected_direction": "increase",
                        "falsification": (
                            "Refuted if the development and final backtests do not raise net "
                            "return versus the unchanged source on the same window."
                        ),
                    },
                },
            )

        best = self._best_developed(projection, development)
        if best is not None and not finish_requested:
            return self._call(projection, "finish", {"attempt_id": best.attempt_id})
        if not untried:
            reason = "rule_tweak: no untried one-step parameter neighbour is available"
        else:
            reason = "rule_tweak: no developed neighbour traded on the development window"
        return self._call(projection, "stop", {"reason": reason})

    @staticmethod
    def _best_developed(projection: Any, development: dict[str, Any]) -> Any | None:
        ranked: list[tuple[float, float, str]] = []
        for attempt in projection.attempts:
            receipt = development.get(attempt.attempt_id)
            if not isinstance(receipt, dict):
                continue
            if not receipt.get("backtest_id") or receipt.get("terminal_failure"):
                continue
            metrics = receipt.get("metrics")
            if not isinstance(metrics, dict):
                continue
            trades = _number(metrics, "trades", "out_of_sample_trades", "trade_count")
            if trades is None or trades <= 0:
                continue
            net_return = _fraction(
                metrics,
                fractions=("net_return", "out_of_sample_return", "total_return"),
                percentages=("total_return_pct",),
            )
            drawdown = _fraction(
                metrics,
                fractions=("max_drawdown", "out_of_sample_max_drawdown", "drawdown"),
                percentages=("max_drawdown_pct",),
            )
            ranked.append(
                (
                    -(net_return if net_return is not None else -math.inf),
                    abs(drawdown) if drawdown is not None else math.inf,
                    attempt.attempt_id,
                )
            )
        if not ranked:
            return None
        ranked.sort()
        best_id = ranked[0][2]
        return next(attempt for attempt in projection.attempts if attempt.attempt_id == best_id)
