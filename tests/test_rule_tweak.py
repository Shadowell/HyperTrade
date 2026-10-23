from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest
from hypertrade.arc.contracts import RULE_TWEAK_PROVIDER
from hypertrade.arc.evolution_memory import bind_hypothesis, experiment_key
from hypertrade.arc.rule_tweak import RuleTweakProvider, parameter_neighbours
from hypertrade.arc.self_test import ARCSelfTestService
from test_source_variant_avo import MockSelfTestClient, source_variant_mission  # noqa: F401


def _policy(*parameters: dict[str, Any]) -> dict[str, Any]:
    return {"authorized_parameters": list(parameters)}


def _param(key: str, kind: str, minimum: float, maximum: float) -> dict[str, Any]:
    return {"key": key, "type": kind, "min": minimum, "max": maximum}


def _values(neighbours: list[dict[str, int | float]], key: str) -> list[int | float]:
    return sorted(item[key] for item in neighbours)


def test_integer_parameter_moves_one_step_each_way() -> None:
    neighbours = parameter_neighbours(
        _policy(_param("fast_window", "integer", 0, 100)),
        {"fast_window": 10},
        seed="seed",
    )
    assert _values(neighbours, "fast_window") == [8, 12]
    assert all(len(item) == 1 for item in neighbours)


def test_integer_step_is_at_least_one() -> None:
    neighbours = parameter_neighbours(
        _policy(_param("fast_window", "integer", 0, 10)),
        {"fast_window": 2},
        seed="seed",
    )
    assert _values(neighbours, "fast_window") == [1, 3]


def test_values_are_clamped_to_declared_bounds() -> None:
    upper = parameter_neighbours(
        _policy(_param("fast_window", "integer", 0, 50)),
        {"fast_window": 50},
        seed="seed",
    )
    assert _values(upper, "fast_window") == [40]
    lower = parameter_neighbours(
        _policy(_param("fast_window", "integer", 5, 50)),
        {"fast_window": 5},
        seed="seed",
    )
    assert _values(lower, "fast_window") == [6]


def test_number_parameter_uses_a_fraction_of_its_value() -> None:
    neighbours = parameter_neighbours(
        _policy(_param("threshold", "number", 0.0, 2.0)),
        {"threshold": 0.5},
        seed="seed",
    )
    assert _values(neighbours, "threshold") == [0.4, 0.6]


def test_zero_number_uses_a_fraction_of_the_allowed_range() -> None:
    neighbours = parameter_neighbours(
        _policy(_param("threshold", "number", -1.0, 1.0)),
        {"threshold": 0},
        seed="seed",
    )
    assert _values(neighbours, "threshold") == [-0.2, 0.2]


def test_nested_research_parameters_are_read() -> None:
    neighbours = parameter_neighbours(
        _policy(_param("research_parameters.threshold", "number", 0.0, 1.0)),
        {"research_parameters": {"threshold": 0.02}},
        seed="seed",
    )
    assert _values(neighbours, "research_parameters.threshold") == [0.016, 0.024]


def test_neighbour_that_breaks_window_order_is_dropped() -> None:
    neighbours = parameter_neighbours(
        _policy(
            _param("fast_window", "integer", 1, 100),
            _param("slow_window", "integer", 1, 100),
        ),
        {"fast_window": 18, "slow_window": 20},
        seed="seed",
    )
    assert {"fast_window": 22} not in neighbours
    assert {"slow_window": 16} not in neighbours
    assert {"fast_window": 14} in neighbours
    assert {"slow_window": 24} in neighbours


def test_neighbour_that_breaks_trend_period_order_is_dropped() -> None:
    neighbours = parameter_neighbours(
        _policy(
            _param("trend_fast_period", "integer", 1, 100),
            _param("trend_slow_period", "integer", 1, 100),
        ),
        {"trend_fast_period": 18, "trend_slow_period": 20},
        seed="seed",
    )
    assert {"trend_fast_period": 22} not in neighbours
    assert {"trend_slow_period": 16} not in neighbours
    assert {"trend_fast_period": 14} in neighbours
    assert {"trend_slow_period": 24} in neighbours


def test_neighbour_that_breaks_nested_window_order_is_dropped() -> None:
    neighbours = parameter_neighbours(
        _policy(
            _param("research_parameters.fast_window", "integer", 1, 100),
            _param("research_parameters.slow_window", "integer", 1, 100),
        ),
        {"research_parameters": {"fast_window": 18, "slow_window": 20}},
        seed="seed",
    )
    assert {"research_parameters.fast_window": 22} not in neighbours
    assert {"research_parameters.slow_window": 16} not in neighbours
    assert {"research_parameters.fast_window": 14} in neighbours
    assert {"research_parameters.slow_window": 24} in neighbours


def test_momentum_exit_must_not_exceed_entry_threshold() -> None:
    neighbours = parameter_neighbours(
        _policy(
            _param("momentum_enter_min_abs_pct", "number", 0.0, 10.0),
            _param("momentum_exit_min_abs_pct", "number", 0.0, 10.0),
        ),
        {"momentum_enter_min_abs_pct": 0.4, "momentum_exit_min_abs_pct": 0.38},
        seed="seed",
    )
    # 0.38 -> 0.456 would exceed the unchanged 0.4 entry threshold.
    assert {"momentum_exit_min_abs_pct": 0.456} not in neighbours
    assert {"momentum_exit_min_abs_pct": 0.304} in neighbours
    # Lowering entry to 0.32 would leave it below the unchanged 0.38 exit threshold.
    assert {"momentum_enter_min_abs_pct": 0.32} not in neighbours
    assert {"momentum_enter_min_abs_pct": 0.48} in neighbours


def test_variant_bitpro_already_tried_is_dropped() -> None:
    policy = _policy(_param("fast_window", "integer", 0, 100))
    policy["relay"] = {
        "tried_variants": [
            {
                "candidate_strategy_id": 9001,
                "state": "racing",
                "parameter_changes": {"fast_window": 12},
                "structural_changes": {},
            }
        ]
    }
    neighbours = parameter_neighbours(policy, {"fast_window": 10}, seed="seed")
    assert _values(neighbours, "fast_window") == [8]


def test_rotation_is_deterministic_per_seed() -> None:
    policy = _policy(
        _param("fast_window", "integer", 0, 100),
        _param("slow_window", "integer", 0, 200),
        _param("threshold", "number", 0.0, 1.0),
    )
    config = {"fast_window": 10, "slow_window": 30, "threshold": 0.02}
    first = parameter_neighbours(policy, config, seed="seed-a")
    assert parameter_neighbours(policy, config, seed="seed-a") == first
    for seed in ("seed-b", "seed-c", "seed-d", "seed-e"):
        if parameter_neighbours(policy, config, seed=seed) != first:
            break
    else:  # pragma: no cover - hashing is stable, so a different seed must rotate
        pytest.fail("different seeds never changed the rotation")


def test_missing_or_boolean_current_values_are_skipped() -> None:
    neighbours = parameter_neighbours(
        _policy(
            _param("enabled", "integer", 0, 10),
            _param("ghost", "integer", 0, 10),
            _param("fast_window", "integer", 0, 100),
        ),
        {"enabled": True, "fast_window": 10},
        seed="seed",
    )
    assert {key for item in neighbours for key in item} == {"fast_window"}
    assert _values(neighbours, "fast_window") == [8, 12]


def _bitpro_policy(controller: Any) -> None:
    controller.projection.goal.evolution_context["variant_policy"]["authorized_parameters"] = [
        {"key": "fast_window", "type": "integer", "min": 5, "max": 50},
        {"key": "slow_window", "type": "integer", "min": 20, "max": 200},
        {"key": "threshold", "type": "number", "min": 0.01, "max": 0.1},
    ]


def _tool_requests(controller: Any, name: str) -> list[dict[str, Any]]:
    return [
        event.payload
        for event in controller.projection.events
        if event.event_type == "avo_tool_requested" and event.payload.get("name") == name
    ]


def test_rule_tweak_mission_runs_end_to_end_without_a_provider(
    source_variant_mission: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = source_variant_mission
    goal = controller.projection.goal
    goal.provider_name = RULE_TWEAK_PROVIDER
    goal.model_name = None
    goal.budget.max_candidates = 4
    _bitpro_policy(controller)

    class ExplodingRuntime:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("rule_tweak must never reach ProviderRuntime")

    monkeypatch.setattr("hypertrade.arc.avo.ProviderRuntime", ExplodingRuntime)
    client = MockSelfTestClient()
    from hypertrade.arc.avo import run_avo_research

    run_avo_research(controller.mission_id, experiments=ARCSelfTestService(client=client))

    attempts = controller.projection.attempts
    assert len(attempts) == 4
    for attempt in attempts:
        assert len(attempt.strategy_spec["parameter_changes"]) == 1
    assert len(_tool_requests(controller, "finish")) == 1
    assert client.backtests_started
    model_requests = [
        event
        for event in controller.projection.events
        if event.event_type == "avo_model_requested"
    ]
    assert model_requests
    assert all(event.payload["provider"] == RULE_TWEAK_PROVIDER for event in model_requests)


def test_rejected_proposals_are_not_retried_and_the_mission_stops(
    source_variant_mission: Any,  # noqa: F811
) -> None:
    from hypertrade.arc.avo import run_avo_research

    controller = source_variant_mission
    goal = controller.projection.goal
    goal.provider_name = RULE_TWEAK_PROVIDER
    goal.model_name = None
    _bitpro_policy(controller)
    context = goal.evolution_context
    policy = context["variant_policy"]
    baseline = context["baseline"]
    baseline_config = baseline["strategy_spec"]["baseline_config"]
    neighbours = parameter_neighbours(policy, baseline_config, seed=controller.mission_id)
    assert neighbours
    code_sha256 = hashlib.sha256(baseline["strategy_code"].encode()).hexdigest()
    context["memory"] = [
        {
            "memory_id": f"mem_archived_{index}",
            "experiment_key": experiment_key(
                code_sha256,
                {**baseline["strategy_spec"], "parameter_changes": changes},
                goal.paper_initial_equity,
                goal.research_windows,
            ),
        }
        for index, changes in enumerate(neighbours)
    ]

    run_avo_research(
        controller.mission_id, experiments=ARCSelfTestService(client=MockSelfTestClient())
    )

    proposals = _tool_requests(controller, "propose")
    assert len(proposals) == len(neighbours)
    seen = {
        json.dumps(request["arguments"]["parameter_changes"], sort_keys=True)
        for request in proposals
    }
    assert len(seen) == len(proposals)
    assert controller.projection.attempts == []
    stopped = [
        event.payload
        for event in controller.projection.events
        if event.event_type == "operator_needed"
    ]
    assert stopped
    assert stopped[-1]["reason"] == "avo_no_candidate"
    assert stopped[-1]["message"].startswith("rule_tweak:")


def test_proposal_binds_an_attribution_report(
    source_variant_mission: Any,  # noqa: F811
) -> None:
    controller = source_variant_mission
    context = controller.projection.goal.evolution_context
    context.pop("paper_feedback")
    context.pop("orders", None)
    context["attribution_report"] = {
        "report_id": "attr01",
        "dimensions": {
            "slippage": {"state": "observed"},
            "alpha": {"state": "observed"},
        },
    }
    response = RuleTweakProvider(controller).chat([], None)
    call = response.tool_calls[0]
    assert call.name == "propose"
    hypothesis = call.arguments["evolution_hypothesis"]
    assert hypothesis["evidence_refs"] == ["attribution:attr01:alpha"]
    assert bind_hypothesis(call.arguments, context, {})


def test_proposal_binds_paper_feedback(
    source_variant_mission: Any,  # noqa: F811
) -> None:
    controller = source_variant_mission
    context = controller.projection.goal.evolution_context
    assert context["paper_feedback"]
    response = RuleTweakProvider(controller).chat([], None)
    call = response.tool_calls[0]
    assert call.name == "propose"
    assert call.arguments["evolution_hypothesis"]["evidence_refs"] == ["paper_feedback"]
    assert bind_hypothesis(call.arguments, context, {})


def test_integer_neighbours_are_python_ints_and_numbers_are_floats() -> None:
    # BitPro rejects an exact-integral float such as 12.0 for an int parameter, so the
    # emitted value must be a Python int, including when a step is clamped to the bound.
    integral = parameter_neighbours(
        _policy(_param("fast_window", "integer", 0, 11)),
        {"fast_window": 10},
        seed="seed",
    )
    integer_values = _values(integral, "fast_window")
    assert integer_values == [8, 11]
    assert all(type(value) is int for value in integer_values)
    decimal = parameter_neighbours(
        _policy(_param("threshold", "number", 0.0, 2.0)),
        {"threshold": 0.5},
        seed="seed",
    )
    assert all(type(value) is float for value in _values(decimal, "threshold"))


def _developed_attempts(
    controller: Any, receipts: list[tuple[float, int]]
) -> list[str]:
    """Create real variant attempts through `_perform`, then pin development receipts."""
    from hypertrade.arc.avo import _perform

    goal = controller.projection.goal
    goal.provider_name = RULE_TWEAK_PROVIDER
    goal.model_name = None
    _bitpro_policy(controller)
    experiments = ARCSelfTestService(client=MockSelfTestClient())
    attempt_ids: list[str] = []
    for offset in range(2, 2 + 2 * len(receipts), 2):
        result = _perform(
            controller,
            "propose",
            {
                "hypothesis": f"规则微调：fast_window 从 10 调到 {10 + offset}",
                "parameter_changes": {"fast_window": 10 + offset},
                "evolution_hypothesis": {
                    "evidence_refs": ["paper_feedback"],
                    "expected_metric": "net_return",
                    "expected_direction": "increase",
                    "falsification": (
                        "Refuted if the development and final backtests do not raise net "
                        "return versus the unchanged source on the same window."
                    ),
                },
            },
            experiments,
        )
        attempt_ids.append(result["attempt_id"])
    # Exhaust the candidate budget so `chat` cannot propose or develop any more attempts.
    goal.budget.max_candidates = len(attempt_ids)
    development = controller.projection.avo.setdefault("development", {})
    for attempt_id, (net_return, trades) in zip(attempt_ids, receipts, strict=True):
        development[attempt_id] = {
            "attempt_id": attempt_id,
            "backtest_id": f"bt_{attempt_id}",
            "metrics": {"net_return": net_return, "trades": trades},
        }
    return attempt_ids


def test_finish_goes_to_the_highest_development_net_return(
    source_variant_mission: Any,  # noqa: F811
) -> None:
    attempt_ids = _developed_attempts(source_variant_mission, [(0.02, 12), (0.08, 12)])
    call = RuleTweakProvider(source_variant_mission).chat([], None).tool_calls[0]
    assert call.name == "finish"
    assert call.arguments["attempt_id"] == attempt_ids[1]


def test_untraded_candidate_is_never_finished(
    source_variant_mission: Any,  # noqa: F811
) -> None:
    attempt_ids = _developed_attempts(source_variant_mission, [(0.02, 12), (0.08, 0)])
    call = RuleTweakProvider(source_variant_mission).chat([], None).tool_calls[0]
    assert call.name == "finish"
    assert call.arguments["attempt_id"] == attempt_ids[0]


def test_all_untraded_candidates_stop_with_the_no_trade_reason(
    source_variant_mission: Any,  # noqa: F811
) -> None:
    _developed_attempts(source_variant_mission, [(0.02, 0), (0.08, 0)])
    call = RuleTweakProvider(source_variant_mission).chat([], None).tool_calls[0]
    assert call.name == "stop"
    assert call.arguments["reason"] == (
        "rule_tweak: no developed neighbour traded on the development window"
    )
