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
from hypertrade.arc.relay_seats import tried_variant, variant_identity
from hypertrade.arc.self_test import _fraction, _number
from hypertrade.providers.chat import ChatResponse, ToolCallRequest

if TYPE_CHECKING:
    from hypertrade.arc.controller import ARCController

RULE_TWEAK_MODEL = "parameter-neighbours-v1"
STEP_FRACTION = 0.2
ZERO_STEP_FRACTION = 0.1
FINAL_RESERVE = 2

PARAMETER_DIMENSIONS = ("signal_period", "risk_exit", "filter_sizing")
DIMENSION_LABELS = {
    "signal_period": "信号与趋势周期",
    "risk_exit": "风控与退出边界",
    "filter_sizing": "阈值过滤与仓位",
}
_ACTIVE_SLOT_STATES = frozenset({"racing", "waiting", "adopting"})
_RISK_EXIT_TOKENS = (
    "stop",
    "loss",
    "profit",
    "take_profit",
    "tp",
    "sl",
    "trail",
    "drawdown",
    "exit",
    "hold",
    "timeout",
    "cooldown",
    "risk",
    "giveback",
    "breakeven",
    "protective",
    "cut",
)
_SIGNAL_PERIOD_TOKENS = (
    "window",
    "period",
    "lookback",
    "fast",
    "slow",
    "mid",
    "ema",
    "sma",
    "ma_",
    "macd",
    "kdj",
    "span",
    "horizon",
    "bars",
    "length",
    "lag",
    "smooth",
)

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


def parameter_dimension(key: str) -> str:
    """Classify a strategy parameter into one of three orthogonal functional dimensions."""
    bare = key[len(_NESTED_PREFIX) :] if key.startswith(_NESTED_PREFIX) else key
    lowered = bare.lower()
    parts = set(lowered.split("_"))
    for token in _RISK_EXIT_TOKENS:
        if token in {"tp", "sl", "cut", "hold"}:
            if token in parts:
                return "risk_exit"
        elif token in lowered:
            return "risk_exit"
    for token in _SIGNAL_PERIOD_TOKENS:
        if token in {"fast", "slow", "mid", "ema", "sma", "span", "bars", "lag"}:
            if token in parts:
                return "signal_period"
        elif token in lowered:
            return "signal_period"
    return "filter_sizing"


def active_slot_changes(
    relay: Any,
    extra_changes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return parameter_changes dicts currently occupying active variant slots on the parent."""
    changes_list: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(relay, dict):
        slots = relay.get("slots")
        if isinstance(slots, list):
            for slot in slots:
                if not isinstance(slot, dict):
                    continue
                if slot.get("occupied") is False:
                    continue
                state = str(slot.get("state") or "").lower()
                if state and state not in _ACTIVE_SLOT_STATES:
                    continue
                changes = slot.get("parameter_changes")
                if isinstance(changes, dict) and changes:
                    identity = variant_identity(changes, {})
                    if identity not in seen:
                        seen.add(identity)
                        changes_list.append(dict(changes))
    for extra in extra_changes or []:
        if isinstance(extra, dict) and extra:
            identity = variant_identity(extra, {})
            if identity not in seen:
                seen.add(identity)
                changes_list.append(dict(extra))
    return changes_list


def occupied_slot_dimensions(
    relay: Any,
    extra_changes: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[str]]:
    """Return (occupied_dimensions, occupied_parameter_keys) across active parent slots."""
    dimensions: list[str] = []
    parameters: list[str] = []
    for changes in active_slot_changes(relay, extra_changes):
        for key in changes:
            key_str = str(key)
            dim = parameter_dimension(key_str)
            if dim not in dimensions:
                dimensions.append(dim)
            if key_str not in parameters:
                parameters.append(key_str)
    return dimensions, parameters


def exploration_plan_for_policy(
    policy: Any,
    baseline_config: Any,
    extra_active_changes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize the 3 functional exploration dimensions and which dimension to target next."""
    parameters = policy.get("authorized_parameters") if isinstance(policy, dict) else None
    grouped: dict[str, list[str]] = {dim: [] for dim in PARAMETER_DIMENSIONS}
    if isinstance(parameters, list):
        for entry in sorted(
            (e for e in parameters if isinstance(e, dict)),
            key=lambda e: str(e.get("key") or e.get("name") or ""),
        ):
            key = str(entry.get("key") or entry.get("name") or "")
            if not key:
                continue
            if (
                isinstance(baseline_config, dict)
                and _finite_number(_current_value(baseline_config, key)) is None
            ):
                continue
            dim = parameter_dimension(key)
            if key not in grouped[dim]:
                grouped[dim].append(key)
    relay = policy.get("relay") if isinstance(policy, dict) else None
    occupied_dims, occupied_params = occupied_slot_dimensions(relay, extra_active_changes)
    available_dims = [dim for dim in PARAMETER_DIMENSIONS if grouped.get(dim)]
    unoccupied_dims = [dim for dim in available_dims if dim not in occupied_dims]
    preferred_dim = (
        unoccupied_dims[0]
        if unoccupied_dims
        else (available_dims[0] if available_dims else PARAMETER_DIMENSIONS[0])
    )
    return {
        "dimensions": {
            dim: {
                "label": DIMENSION_LABELS[dim],
                "parameters": grouped[dim],
                "occupied": dim in occupied_dims,
            }
            for dim in PARAMETER_DIMENSIONS
        },
        "occupied_dimensions": occupied_dims,
        "occupied_parameters": occupied_params,
        "unoccupied_dimensions": unoccupied_dims,
        "preferred_dimension": preferred_dim,
        "preferred_dimension_label": DIMENSION_LABELS.get(preferred_dim, preferred_dim),
    }


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
    policy: dict[str, Any],
    baseline_config: dict[str, Any],
    *,
    seed: str,
    extra_active_changes: list[dict[str, Any]] | None = None,
) -> list[dict[str, int | float]]:
    """One-step parameter neighbours interleaved across 3 functional dimensions."""
    parameters = policy.get("authorized_parameters") if isinstance(policy, dict) else None
    if not isinstance(parameters, list) or not isinstance(baseline_config, dict):
        return []
    relay = policy.get("relay")
    active_identities = {
        variant_identity(changes, {})
        for changes in active_slot_changes(relay, extra_active_changes)
    }
    by_dim_and_key: dict[str, list[list[dict[str, int | float]]]] = {
        dim: [] for dim in PARAMETER_DIMENSIONS
    }
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
        key_changes: list[dict[str, int | float]] = []
        for value in candidates:
            changes: dict[str, int | float] = {key: value}
            if _violates_bitpro_rules(baseline_config, changes):
                continue
            if tried_variant(relay, changes, {}) is not None:
                continue
            if variant_identity(changes, {}) in active_identities:
                continue
            key_changes.append(changes)
        if key_changes:
            by_dim_and_key[parameter_dimension(key)].append(key_changes)

    # Interleave across keys within each dimension first, then round-robin across the
    # 3 orthogonal functional dimensions so any prefix of 3 proposals covers 3 directions.
    dim_queues: dict[str, list[dict[str, int | float]]] = {}
    for dim in PARAMETER_DIMENSIONS:
        key_lists = by_dim_and_key[dim]
        interleaved: list[dict[str, int | float]] = []
        max_key_len = max((len(items) for items in key_lists), default=0)
        for idx in range(max_key_len):
            for items in key_lists:
                if idx < len(items):
                    interleaved.append(items[idx])
        if interleaved:
            dim_queues[dim] = interleaved

    if not dim_queues:
        return []

    active_dims = [dim for dim in PARAMETER_DIMENSIONS if dim in dim_queues]
    dim_offset = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(active_dims)
    rotated_dims = active_dims[dim_offset:] + active_dims[:dim_offset]
    for dim in rotated_dims:
        queue = dim_queues[dim]
        key_offset = int(hashlib.sha256(f"{seed}:{dim}".encode()).hexdigest(), 16) % len(queue)
        dim_queues[dim] = queue[key_offset:] + queue[:key_offset]

    ordered: list[dict[str, int | float]] = []
    max_dim_len = max(len(queue) for queue in dim_queues.values())
    for idx in range(max_dim_len):
        for dim in rotated_dims:
            queue = dim_queues[dim]
            if idx < len(queue):
                ordered.append(queue[idx])

    occupied_dims, occupied_params = occupied_slot_dimensions(relay, extra_active_changes)
    if occupied_dims or occupied_params:
        occupied_dim_set = set(occupied_dims)
        occupied_param_set = set(occupied_params)
        ordered.sort(
            key=lambda item: (
                parameter_dimension(next(iter(item))) in occupied_dim_set,
                next(iter(item)) in occupied_param_set,
            )
        )
    return ordered


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
            if event.event_type == "avo_tool_requested" and event.payload.get("name") == "propose"
        ]
        finish_requested = any(
            event.event_type == "avo_tool_requested" and event.payload.get("name") == "finish"
            for event in projection.events
        )
        context = goal.evolution_context or {}
        policy = context.get("variant_policy") or {}
        extra_active = context.get("active_slot_variants")
        extra_active_changes = extra_active if isinstance(extra_active, list) else None
        relay = policy.get("relay") if isinstance(policy, dict) else None
        occupied_dims, occupied_params = occupied_slot_dimensions(relay, extra_active_changes)
        baseline_spec = (context.get("baseline") or {}).get("strategy_spec") or {}
        baseline_config = baseline_spec.get("baseline_config") or {}
        untried = [
            changes
            for changes in parameter_neighbours(
                policy,
                baseline_config,
                seed=projection.mission_id,
                extra_active_changes=extra_active_changes,
            )
            if changes not in requested
        ]

        for attempt in projection.attempts:
            if attempt.attempt_id not in development and dev_left >= 1:
                return self._call(projection, "develop", {"attempt_id": attempt.attempt_id})

        if budget.candidates_used < budget.max_candidates and dev_left >= 1 and untried:
            requested_dims = {
                parameter_dimension(str(next(iter(item))))
                for item in requested
                if isinstance(item, dict) and item
            }
            requested_keys = {
                str(next(iter(item))) for item in requested if isinstance(item, dict) and item
            }
            occupied_dim_set = set(occupied_dims)
            occupied_param_set = set(occupied_params)
            changes = min(
                untried,
                key=lambda item: (
                    parameter_dimension(str(next(iter(item)))) in requested_dims,
                    parameter_dimension(str(next(iter(item)))) in occupied_dim_set,
                    str(next(iter(item))) in requested_keys,
                    str(next(iter(item))) in occupied_param_set,
                ),
            )
            refs = _evidence_refs(context)
            if not refs:
                return self._call(
                    projection,
                    "stop",
                    {"reason": "rule_tweak: no citable evidence for a hypothesis"},
                )
            key, value = next(iter(changes.items()))
            current = _current_value(baseline_config, key)
            dim = parameter_dimension(key)
            dim_label = DIMENSION_LABELS.get(dim, dim)
            return self._call(
                projection,
                "propose",
                {
                    "hypothesis": (
                        f"规则微调（{dim_label}）：{key} 从 {current} 调到 {value}"
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

        best = self._best_developed(
            projection,
            development,
            occupied_dimensions=occupied_dims,
            occupied_parameters=occupied_params,
        )
        if best is not None and not finish_requested:
            return self._call(projection, "finish", {"attempt_id": best.attempt_id})
        if not untried:
            reason = "rule_tweak: no untried one-step parameter neighbour is available"
        else:
            reason = "rule_tweak: no developed neighbour traded on the development window"
        return self._call(projection, "stop", {"reason": reason})

    @staticmethod
    def _best_developed(
        projection: Any,
        development: dict[str, Any],
        *,
        occupied_dimensions: list[str] | tuple[str, ...] = (),
        occupied_parameters: list[str] | tuple[str, ...] = (),
    ) -> Any | None:
        occupied_dim_set = set(occupied_dimensions)
        occupied_param_set = set(occupied_parameters)
        ranked: list[tuple[bool, bool, float, float, str]] = []
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
            spec = attempt.strategy_spec if isinstance(attempt.strategy_spec, dict) else {}
            changes = spec.get("parameter_changes")
            key = str(next(iter(changes))) if isinstance(changes, dict) and changes else ""
            dim = parameter_dimension(key) if key else "filter_sizing"
            ranked.append(
                (
                    dim in occupied_dim_set,
                    key in occupied_param_set,
                    -(net_return if net_return is not None else -math.inf),
                    abs(drawdown) if drawdown is not None else math.inf,
                    attempt.attempt_id,
                )
            )
        if not ranked:
            return None
        ranked.sort()
        best_id = ranked[0][4]
        return next(attempt for attempt in projection.attempts if attempt.attempt_id == best_id)
