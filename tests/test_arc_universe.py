import pytest
from hypertrade.arc.contracts import ARCGoalV1
from hypertrade.arc.universe import candidate_symbol, normalize_symbols, resolve_universe


def test_arbitrary_symbols_normalize_without_coin_allowlist():
    assert normalize_symbols(["sol", "1inch/usdt:usdt", "SOL-USDT-SWAP"]) == [
        "SOL-USDT-SWAP",
        "1INCH-USDT-SWAP",
    ]
    with pytest.raises(ValueError):
        normalize_symbols(["AAPL/USD"])


def test_discovery_freezes_available_instruments_and_never_falls_back():
    assert resolve_universe([], discover=lambda: ["SOL/USDT:USDT", "DOGE/USDT:USDT"]) == [
        "SOL-USDT-SWAP",
        "DOGE-USDT-SWAP",
    ]
    with pytest.raises(ValueError):
        resolve_universe([], discover=lambda: [])


def test_explicit_scope_is_checked_against_catalog():
    assert resolve_universe(["DOGE"], discover=lambda: ["DOGE-USDT-SWAP"]) == ["DOGE-USDT-SWAP"]
    with pytest.raises(ValueError):
        resolve_universe(["SOL"], discover=lambda: ["DOGE-USDT-SWAP"])


def test_candidate_requires_choice_and_stays_inside_scope():
    goal = ARCGoalV1(objective="research", symbols=["SOL-USDT-SWAP", "DOGE-USDT-SWAP"])
    assert candidate_symbol({"symbol": "DOGE-USDT-SWAP"}, goal.symbols) == "DOGE-USDT-SWAP"
    for spec in ({}, {"symbol": "BTC-USDT-SWAP"}):
        with pytest.raises(ValueError):
            candidate_symbol(spec, goal.symbols)


def test_avo_selects_second_instrument_and_review_binds_only_that_candidate():
    from hypertrade.arc.store import reset_store
    reset_store()
    from hypertrade.arc.avo import _perform
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.paper_review import build_paper_review
    from hypertrade.arc.self_test import ARCSelfTestService

    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="研究DOGE",
            symbols=["SOL-USDT-SWAP", "DOGE-USDT-SWAP"],
            paper_review_required=True,
        )
    )
    ctrl.apply_event(
        "avo_model_requested", {"provider": "fixture", "model": "test", "request_hash": "test"}
    )
    args = {
        "symbol": "DOGE-USDT-SWAP",
        "hypothesis": "DOGE trend",
        "family_key": "ma_crossover",
        "direction": "long_short",
        "parameter_bounds": {},
    }
    _perform(ctrl, "propose", args, ARCSelfTestService())
    attempt = ctrl.projection.attempts[0]
    assert attempt.strategy_spec["symbol"] == "DOGE-USDT-SWAP"
    attempt.state = "validated"
    attempt.bitpro_strategy_id = "99"
    attempt.bitpro_backtest_id = "100"
    attempt.validation_id = "val"
    review = build_paper_review(ctrl.projection)
    assert review["unknowns"] == []
    assert review["paper_configuration"]["symbols"] == ["DOGE-USDT-SWAP"]
    with pytest.raises(ValueError):
        _perform(ctrl, "propose", {**args, "symbol": "BTC-USDT-SWAP"}, ARCSelfTestService())


def test_out_of_scope_backtest_does_not_call_external_client():
    from hypertrade.arc.contracts import ARCCandidateAttemptV1
    from hypertrade.arc.self_test import ARCSelfTestService

    goal = ARCGoalV1(objective="SOL", symbols=["SOL-USDT-SWAP"])
    attempt = ARCCandidateAttemptV1(
        attempt_id="bad",
        candidate_id="bad",
        hypothesis="test",
        strategy_code="pass",
        strategy_spec={"symbol": "BTC-USDT-SWAP"},
    )
    result = ARCSelfTestService(client=object()).run(attempt, goal)
    assert not result.passed
    assert result.reasons == ["candidate_symbol_missing_or_outside_research_scope"]
