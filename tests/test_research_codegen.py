from __future__ import annotations

import ast
from typing import Any

import pytest
from hypertrade.research.codegen import (
    FAMILIES,
    StrategyCodegenError,
    compile_strategy_code,
    generate_strategy,
    static_code_rejections,
)


def _spec(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "schema_version": "research_strategy_spec.v1",
        "mandate_id": "rman_test",
        "strategy_key": "baseline_candidate",
        "title": "baseline candidate",
        "hypothesis": "a bounded research hypothesis for regression coverage",
        "symbols": ["BTC"],
        "timeframes": ["1H"],
        "strategy_category": "TREND",
        "entry_logic": "enter when the configured signal condition holds",
        "exit_logic": "exit when the configured signal condition reverses",
        "risk_conditions": ["bounded notional"],
        "data_requirements": ["ohlcv"],
        "parameter_bounds": {},
        "invalidation_conditions": ["insufficient data"],
    }
    spec.update(overrides)
    return spec


def test_identical_specs_compile_to_identical_bytes() -> None:
    """The experiment ledger fingerprints candidates by code hash."""
    spec = _spec(strategy_key="determinism_probe")
    assert compile_strategy_code(spec) == compile_strategy_code(dict(spec))


@pytest.mark.parametrize(
    ("expected_family", "hypothesis", "entry_logic"),
    [
        ("ma_crossover", "fast and slow moving average crossover", "golden cross forms"),
        ("atr_breakout", "ATR volatility channel expansion", "close breaks the ATR band"),
        ("mean_reversion_zscore", "price mean reversion after dispersion", "z-score exceeds two"),
        ("rsi_reversal", "RSI oversold bounce", "RSI drops below the oversold level"),
        ("donchian_breakout", "donchian turtle channel", "close exceeds the highest high"),
        ("momentum_roc", "rate of change momentum persists", "roc exceeds the threshold"),
    ],
)
def test_spec_vocabulary_selects_the_matching_family(
    expected_family: str, hypothesis: str, entry_logic: str
) -> None:
    generated = generate_strategy(
        _spec(strategy_key="family_probe", hypothesis=hypothesis, entry_logic=entry_logic)
    )
    assert generated.family == expected_family


def test_semantically_distinct_specs_do_not_collapse_onto_one_strategy() -> None:
    """Every downstream gate assumes candidates differ; this is that assumption."""
    variants = [
        ("ma_probe", "moving average golden cross confirms trend"),
        ("atr_probe", "ATR volatility channel breakout"),
        ("zscore_probe", "z-score mean reversion after dispersion"),
        ("rsi_probe", "RSI oversold reversal"),
        ("donchian_probe", "donchian turtle highest high channel"),
        ("roc_probe", "rate of change momentum continuation"),
    ]
    codes = {
        compile_strategy_code(_spec(strategy_key=key, hypothesis=hypothesis))
        for key, hypothesis in variants
    }
    assert len(codes) == len(variants)


def test_explicit_prohibition_outranks_a_bare_short_mention() -> None:
    long_only = generate_strategy(
        _spec(
            strategy_key="long_only_probe",
            hypothesis="donchian channel breakout, no shorting allowed even on a short signal",
        )
    )
    assert long_only.direction == "long_only"
    assert 'self._enter(symbol, "short"' not in long_only.code


def test_short_only_spec_never_emits_a_long_entry() -> None:
    generated = generate_strategy(
        _spec(
            strategy_key="short_only_probe",
            hypothesis="z-score mean reversion, 仅做空",
            entry_logic="short when the z-score exceeds the entry threshold",
        )
    )
    assert generated.direction == "short_only"
    assert 'self._enter(symbol, "long"' not in generated.code
    assert 'self._enter(symbol, "short"' in generated.code


def test_bidirectional_spec_emits_both_entries() -> None:
    generated = generate_strategy(
        _spec(
            strategy_key="both_sides_probe",
            hypothesis="donchian channel breakout traded long and short",
        )
    )
    assert generated.direction == "long_short"
    assert 'self._enter(symbol, "long"' in generated.code
    assert 'self._enter(symbol, "short"' in generated.code


@pytest.mark.parametrize("family", FAMILIES, ids=lambda family: family.key)
def test_every_family_emits_admissible_parseable_code(family: Any) -> None:
    spec = _spec(
        strategy_key=f"{family.key}_probe",
        hypothesis=f"{family.signature[0]} driven candidate traded long and short",
        risk_conditions=["stop loss", "take profit", "max holding period"],
    )
    generated = generate_strategy(spec)
    assert generated.family == family.key
    ast.parse(generated.code)
    assert static_code_rejections(generated.code) == []
    assert "from app.core.execution.base_strategy import BaseStrategy" in generated.code
    assert "async def on_bar(self, bar):" in generated.code
    assert "async def on_init(self):" in generated.code
    assert "def __init__" not in generated.code


# Mirrors BitPro's `code_sandbox.FORBIDDEN_NAMES`. Duplicated as a literal because
# HyperTrade must not import BitPro code; a candidate calling any of these is rejected by
# `strategy_validate_code`, so it can never be validated however good its evidence is.
_BITPRO_FORBIDDEN_CALLS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "globals",
        "locals",
        "getattr",
        "setattr",
        "delattr",
        "breakpoint",
        "exit",
        "quit",
    }
)


@pytest.mark.parametrize("family", FAMILIES, ids=lambda family: family.key)
@pytest.mark.parametrize("direction", ["long_only", "short_only", "long_short"])
def test_no_family_emits_a_call_bitpro_forbids(family: Any, direction: str) -> None:
    """`getattr` in the high/low families made donchian and atr_breakout unvalidatable.

    Their candidates cleared held-out evidence — donchian short was the best scoring
    family on real ETH history — and were then rejected by BitPro's code check, so the
    mission stalled at validation with the reason recorded as a platform outage.
    """
    hypothesis = f"{family.signature[0]} driven candidate"
    if direction == "short_only":
        hypothesis += "，仅做空"
    elif direction == "long_short":
        hypothesis += " traded long and short"
    generated = generate_strategy(_spec(strategy_key=f"{family.key}_probe", hypothesis=hypothesis))

    called = {
        node.func.id
        for node in ast.walk(ast.parse(generated.code))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not (called & _BITPRO_FORBIDDEN_CALLS), (
        f"{family.key}/{direction} emits calls BitPro rejects: "
        f"{sorted(called & _BITPRO_FORBIDDEN_CALLS)}"
    )


def test_generated_parameters_are_the_ones_on_init_reads() -> None:
    """A knob the matrix tunes but the code never reads is silent dead coverage."""
    generated = generate_strategy(
        _spec(strategy_key="knob_probe", hypothesis="RSI oversold reversal")
    )
    for name in generated.tunable_parameters:
        assert f'params.get("{name}"' in generated.code
    assert set(generated.tunable_parameters) == set(generated.parameter_bounds)


def test_placeholder_bounds_are_replaced_by_real_knobs() -> None:
    """Drafted specs name knobs like `lookback` that no family implements."""
    generated = generate_strategy(
        _spec(
            strategy_key="placeholder_probe",
            hypothesis="moving average crossover trend candidate",
            parameter_bounds={
                "lookback": {"min": 5, "max": 60},
                "threshold": {"min": 0.1, "max": 2.0},
            },
        )
    )
    assert "lookback" not in generated.parameter_bounds
    assert "threshold" not in generated.parameter_bounds
    assert {"fast_window", "slow_window"} <= set(generated.parameter_bounds)


def test_declared_bounds_narrow_but_never_widen_the_family_range() -> None:
    generated = generate_strategy(
        _spec(
            strategy_key="clamp_probe",
            hypothesis="moving average crossover trend candidate",
            parameter_bounds={
                "fast_window": {"min": 5, "max": 20},
                "slow_window": {"min": 1, "max": 100_000},
            },
        )
    )
    assert generated.parameter_bounds["fast_window"] == {"min": 5.0, "max": 20.0}
    # Family ceiling of 400 wins over the spec's 100_000 request.
    assert generated.parameter_bounds["slow_window"]["max"] == 400.0


def test_a_candidate_always_carries_a_loss_guard() -> None:
    generated = generate_strategy(
        _spec(strategy_key="guard_probe", risk_conditions=["bounded notional"])
    )
    assert "stop_loss" in generated.risk_overlays
    assert generated.tunable_parameters["stop_loss"] > 0.0


def test_requested_overlays_default_to_active_thresholds() -> None:
    generated = generate_strategy(
        _spec(
            strategy_key="overlay_probe",
            risk_conditions=["take profit target", "max holding period"],
        )
    )
    assert generated.tunable_parameters["take_profit"] > 0.0
    assert generated.tunable_parameters["max_holding_bars"] > 0


def test_missing_strategy_key_is_rejected() -> None:
    with pytest.raises(StrategyCodegenError, match="strategy_spec_missing_strategy_key"):
        generate_strategy(_spec(strategy_key=""))


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        ("class A(BaseStrategy):\n    x = open('/etc/passwd')\n", "filesystem_access"),
        ("import socket\n\nclass A(BaseStrategy):\n    pass\n", "network_access"),
        ("class A(BaseStrategy):\n    x = eval('1')\n", "dynamic_execution"),
        ("class A(BaseStrategy):\n    x = 1\n\nclass B(BaseStrategy):\n    y = 2\n",
         "code_requires_single_basestrategy_subclass"),
    ],
)
def test_static_gate_rejects_inadmissible_constructs(code: str, reason: str) -> None:
    assert reason in static_code_rejections(code)


def test_static_gate_accepts_a_minimal_admissible_candidate() -> None:
    assert static_code_rejections("class A(BaseStrategy):\n    pass\n") == []
