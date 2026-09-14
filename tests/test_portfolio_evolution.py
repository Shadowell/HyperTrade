"""Portfolio-aware evolution: a basket strategy is evolved as a whole."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypertrade.arc.avo import enforce_source_scope
from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1, PaperFeedbackPolicyV1
from hypertrade.arc.feedback import _benchmark_series, evaluate_windows
from hypertrade.arc.provider_hypothesis import _bounded_spec
from hypertrade.arc.self_test import ARCSelfTestService
from hypertrade.arc.universe import candidate_symbols, declared_symbols
from hypertrade.research.codegen import FAMILIES
from test_arc_evolution import Paper, prepare
from test_evolution_memory import WINDOWS, record

BASKET = [
    "NVDA-USDT-SWAP",
    "AMD-USDT-SWAP",
    "MU-USDT-SWAP",
    "SOXL-USDT-SWAP",
]
END = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
START = END - timedelta(days=14)
MIDDLE = END - timedelta(days=7)


@pytest.fixture
def service():
    from hypertrade.arc.evolution import EvolutionService
    from hypertrade.arc.store import configure_store, reset_store
    from hypertrade.db import Database

    database = Database("sqlite:///:memory:")
    database.create_all()
    configure_store(database)
    yield EvolutionService(database)
    reset_store()


# ---------------------------------------------------------------- universe


def test_candidate_symbols_accepts_declared_portfolio_inside_scope() -> None:
    spec = {"symbols": ["NVDA-USDT-SWAP", "AMD-USDT-SWAP"]}
    assert candidate_symbols(spec, BASKET) == ["NVDA-USDT-SWAP", "AMD-USDT-SWAP"]
    assert declared_symbols(spec) == ["NVDA-USDT-SWAP", "AMD-USDT-SWAP"]


def test_candidate_symbols_refuses_outside_scope_and_empty() -> None:
    with pytest.raises(ValueError, match="outside_research_scope"):
        candidate_symbols({"symbols": ["TSLA-USDT-SWAP"]}, BASKET)
    with pytest.raises(ValueError):
        candidate_symbols({"symbols": []}, BASKET)


def test_candidate_symbols_single_scope_inheritance_kept() -> None:
    assert candidate_symbols({}, ["BTC-USDT-SWAP"]) == ["BTC-USDT-SWAP"]
    with pytest.raises(ValueError, match="candidate_symbol_missing_or_outside"):
        candidate_symbols({}, BASKET)


# ---------------------------------------------------------------- scan gate


class PortfolioPaper(Paper):
    def paper_snapshot(self, **kwargs):
        row = super().paper_snapshot(**kwargs)
        row["strategy"] = {"symbols": [f"{item.split('-')[0]}/USDT:USDT" for item in BASKET]}
        return row


def test_portfolio_degradation_opens_research_with_full_basket(service, monkeypatch) -> None:
    from hypertrade.arc.store import get_controller

    now = prepare(service, monkeypatch)  # collect_windows stub reports degradation
    service.client = PortfolioPaper()
    result = service.tick(now)
    assert result["status"] == "research_created"
    goal = get_controller(result["payload"]["mission_id"]).projection.goal
    assert goal.symbols == BASKET
    spec = goal.evolution_context["baseline"]["strategy_spec"]
    assert spec["symbols"] == BASKET
    assert "symbol" not in spec


# ---------------------------------------------------------------- self-test


def test_self_test_portfolio_backtests_the_full_basket() -> None:
    calls: list[tuple[str, dict]] = []

    class Client:
        def strategy_validate_code(self, **kwargs):
            calls.append(("validate", kwargs))
            return {"status": "ok"}

        def strategy_create(self, **kwargs):
            calls.append(("create", kwargs))
            return {"strategy": {"id": 9}}

        def backtest_start_job(self, **kwargs):
            calls.append(("backtest", kwargs))
            return {
                "backtest_result": {
                    "id": "proof",
                    "metrics": {
                        "sharpe": 2,
                        "max_drawdown": 0.01,
                        "trades": 100,
                        "net_return": 0.1,
                    },
                }
            }

    goal = ARCGoalV1(
        objective="portfolio evolution",
        symbols=BASKET,
        paper_review_required=True,
        research_id="pf-test",
    )
    attempt = ARCCandidateAttemptV1(
        attempt_id="pf",
        candidate_id="pf",
        hypothesis="keep the basket, tighten entries",
        strategy_code="class X: pass",
        strategy_spec={"symbols": BASKET, "timeframe": "1H"},
    )
    assert ARCSelfTestService(Client()).run(attempt, goal).passed

    validate_kwargs = next(payload for name, payload in calls if name == "validate")
    assert validate_kwargs["symbols"] == BASKET
    create_kwargs = next(payload for name, payload in calls if name == "create")
    assert create_kwargs["symbols"] == BASKET
    assert "NVDA/AMD/MU等4" in create_kwargs["name"]
    backtest_kwargs = next(payload for name, payload in calls if name == "backtest")
    assert backtest_kwargs["symbol"] is None  # BitPro derives the basket from config


def test_self_test_single_symbol_still_passes_explicit_symbol() -> None:
    calls: list[tuple[str, dict]] = []

    class Client:
        def strategy_validate_code(self, **kwargs):
            return {"status": "ok"}

        def strategy_create(self, **kwargs):
            calls.append(("create", kwargs))
            return {"strategy": {"id": 9}}

        def backtest_start_job(self, **kwargs):
            calls.append(("backtest", kwargs))
            return {
                "backtest_result": {
                    "id": "proof",
                    "metrics": {
                        "sharpe": 2,
                        "max_drawdown": 0.01,
                        "trades": 100,
                        "net_return": 0.1,
                    },
                }
            }

    goal = ARCGoalV1(
        objective="single symbol",
        symbols=["SOL-USDT-SWAP"],
        paper_review_required=True,
        research_id="single-test",
    )
    attempt = ARCCandidateAttemptV1(
        attempt_id="single",
        candidate_id="single",
        hypothesis="h",
        strategy_code="class X: pass",
        strategy_spec={"symbol": "SOL-USDT-SWAP", "timeframe": "1H"},
    )
    assert ARCSelfTestService(Client()).run(attempt, goal).passed
    backtest_kwargs = next(payload for name, payload in calls if name == "backtest")
    assert backtest_kwargs["symbol"] == "SOL-USDT-SWAP"


# ---------------------------------------------------------------- provider spec


def test_bounded_spec_carries_portfolio_scope() -> None:
    parsed = {
        "family_key": FAMILIES[0].key,
        "direction": "long_only",
        "parameter_bounds": {},
        "hypothesis": "basket-wide entry filter",
    }
    spec = _bounded_spec(
        parsed, objective="o", symbol=BASKET[0], symbols=BASKET, timeframe="1H"
    )
    assert spec is not None
    assert spec["symbols"] == BASKET
    assert "4sym" in spec["strategy_key"]
    assert "NVDA/AMD/MU等4" in spec["title"]


def test_enforce_source_scope_preserves_basket_and_blocks_widening() -> None:
    enforce_source_scope({"symbols": BASKET}, BASKET)  # identical set is fine
    with pytest.raises(ValueError, match="preserve the full source symbol set"):
        enforce_source_scope({"symbols": BASKET}, [BASKET[0]])
    enforce_source_scope({"symbol": "SOL-USDT-SWAP"}, ["SOL-USDT-SWAP"])
    with pytest.raises(ValueError, match="cannot widen"):
        enforce_source_scope({"symbol": "SOL-USDT-SWAP"}, ["SOL-USDT-SWAP", "BTC-USDT-SWAP"])


# ---------------------------------------------------------------- benchmark


def build_series(prev_week_return: float, recent_week_return: float) -> list[dict]:
    points = []
    equity = 100.0
    for hour in range(0, 169):
        points.append(
            {"timestamp": (START + timedelta(hours=hour)).isoformat(), "equity": equity}
        )
        equity *= 1 + prev_week_return / 168
    for hour in range(1, 169):
        equity *= 1 + recent_week_return / 168
        points.append(
            {"timestamp": (MIDDLE + timedelta(hours=hour)).isoformat(), "equity": equity}
        )
    return points


class MultiKlineClient:
    def __init__(self, series: dict[str, list[dict]]) -> None:
        self.series = series
        self.calls: list[str] = []

    def market_klines(self, **kwargs):
        symbol = kwargs["symbol"]
        self.calls.append(symbol)
        if symbol not in self.series:
            raise RuntimeError("symbol unavailable")
        rows = [
            {
                "timestamp": int(datetime.fromisoformat(point["timestamp"]).timestamp() * 1000),
                "close": point["equity"],
            }
            for point in self.series[symbol]
        ]
        return {"candles": rows}


def test_benchmark_series_builds_equal_weight_composite() -> None:
    flat = build_series(0.0, 0.0)
    doubler = [
        {"timestamp": point["timestamp"], "equity": 100.0 + (100.0 * index / 336)}
        for index, point in enumerate(flat)
    ]
    client = MultiKlineClient({"NVDA-USDT-SWAP": doubler, "AMD-USDT-SWAP": flat})
    block = _benchmark_series(client, ["NVDA-USDT-SWAP", "AMD-USDT-SWAP"], "1H", START, END)
    assert block["status"] == "observed"
    assert block["symbols"] == ["NVDA-USDT-SWAP", "AMD-USDT-SWAP"]
    assert client.calls == ["NVDA-USDT-SWAP", "AMD-USDT-SWAP"]
    first, last = block["points"][0]["equity"], block["points"][-1]["equity"]
    assert first == pytest.approx(100.0, abs=0.5)
    assert last == pytest.approx(150.0, abs=1.0)  # (200 + 100) / 2


def test_benchmark_series_fails_closed_when_a_member_is_missing() -> None:
    client = MultiKlineClient({"NVDA-USDT-SWAP": build_series(0.0, 0.0)})
    block = _benchmark_series(client, ["NVDA-USDT-SWAP", "AMD-USDT-SWAP"], "1H", START, END)
    assert block["status"] == "unavailable"
    assert block["symbols"] == ["NVDA-USDT-SWAP", "AMD-USDT-SWAP"]


def policy() -> PaperFeedbackPolicyV1:
    return PaperFeedbackPolicyV1(enabled=True, threshold_pp=10, benchmark_relative=True)


def test_market_wide_crash_does_not_trigger_portfolio_degradation() -> None:
    strategy = build_series(0.10, -0.05)  # 15pp deterioration
    crowded = {
        "NVDA-USDT-SWAP": build_series(0.10, -0.30),
        "AMD-USDT-SWAP": build_series(0.10, -0.30),
    }
    block = _benchmark_series(MultiKlineClient(crowded), list(crowded), "1H", START, END)
    result = evaluate_windows(strategy, END, policy(), benchmark=block)
    assert result["degradation_basis"] == "benchmark_relative"
    assert result["triggered"] is False


def test_portfolio_underperformance_against_composite_triggers() -> None:
    strategy = build_series(0.10, -0.05)  # 15pp deterioration
    mild = {"NVDA-USDT-SWAP": build_series(0.10, 0.05), "AMD-USDT-SWAP": build_series(0.10, 0.05)}
    block = _benchmark_series(MultiKlineClient(mild), list(mild), "1H", START, END)
    result = evaluate_windows(strategy, END, policy(), benchmark=block)
    assert result["triggered"] is True
    assert "relative_return_drop" in result["reasons"]


# ---------------------------------------------------------------- memory scope


def test_curate_memory_accepts_portfolio_member_scope() -> None:
    from hypertrade.arc.evolution_memory import curate_memory

    entry = record(spec={"symbol": "AMD-USDT-SWAP", "timeframe": "1H", "family": "ma_crossover"})
    accepted, _ = curate_memory(
        [entry],
        symbol="NVDA-USDT-SWAP",
        timeframe="1H",
        windows=WINDOWS,
        symbols={"NVDA-USDT-SWAP", "AMD-USDT-SWAP"},
    )
    assert len(accepted) == 1
    rejected, manifest = curate_memory(
        [entry], symbol="NVDA-USDT-SWAP", timeframe="1H", windows=WINDOWS
    )
    assert rejected == []
    assert manifest["excluded"]["scope_mismatch"] == 1
