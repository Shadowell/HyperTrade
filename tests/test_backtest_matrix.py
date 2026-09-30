from __future__ import annotations

from hypertrade.research.codegen import generate_strategy
from hypertrade.research.optimization.matrix import (
    BacktestMatrixEngine,
    generate_synthetic_bars,
)
from hypertrade.research.optimization.metrics import (
    QuantitativeMetrics,
)


def _spec(**overrides):
    spec = {
        "schema_version": "research_strategy_spec.v1",
        "strategy_key": "replay_probe",
        "hypothesis": "快慢均线金叉确认趋势",
        "entry_logic": "快线上穿慢线",
        "exit_logic": "快线下穿慢线",
        "risk_conditions": ["stop loss"],
    }
    spec.update(overrides)
    return spec


def test_synthetic_bars_generation() -> None:
    bars = generate_synthetic_bars("BTC-USDT-SWAP", count=100, timeframe="1H")
    assert len(bars) == 100
    assert bars[0].symbol == "BTC-USDT-SWAP"
    assert bars[0].open > 0
    assert bars[0].high >= bars[0].low


def test_quantitative_metrics_serialization() -> None:
    metrics = QuantitativeMetrics(
        total_return_pct=15.5,
        annualized_return_pct=32.1,
        annualized_sharpe=1.85,
        sortino_ratio=2.4,
        calmar_ratio=3.2,
        max_drawdown_pct=10.0,
        win_rate=0.60,
        profit_factor=1.75,
        trade_count=20,
        turnover=2.5,
        exposure_rate=0.45,
        avg_holding_bars=12.0,
        fees_paid=15.0,
        is_inert=False,
    )
    d = metrics.to_dict()
    assert d["annualized_sharpe"] == 1.85
    assert d["win_rate"] == 0.60

    restored = QuantitativeMetrics.from_dict(d)
    assert restored.total_return_pct == 15.5
    assert restored.annualized_sharpe == 1.85


def test_backtest_matrix_engine_execution() -> None:
    bars_1h = generate_synthetic_bars("BTC-USDT-SWAP", count=150, timeframe="1H", seed=10)
    bars_4h = generate_synthetic_bars("BTC-USDT-SWAP", count=150, timeframe="4H", seed=20)

    bars_map = {
        ("BTC-USDT-SWAP", "1H"): bars_1h,
        ("BTC-USDT-SWAP", "4H"): bars_4h,
    }

    generated = generate_strategy(_spec())
    base_params = dict(generated.tunable_parameters)

    engine = BacktestMatrixEngine(
        strategy_code=generated.code,
        symbols=["BTC-USDT-SWAP"],
        timeframes=["1H", "4H"],
        is_ratio=0.70,
        starting_equity=10_000.0,
        trade_notional_usdt=1_000.0,
    )

    variant1 = dict(base_params)
    variant2 = dict(base_params)
    # Tweak one param if available
    for k, v in variant2.items():
        if isinstance(v, (int, float)):
            variant2[k] = v + 2
            break

    variants = [variant1, variant2]

    results = engine.run_matrix(
        parameter_variants=variants,
        bars_by_dimension=bars_map,
    )

    assert len(results) == 2
    assert results[0].is_successful
    assert results[1].is_successful

    # Check dimensions
    assert len(results[0].dimension_results) == 2
    dim0 = results[0].dimension_results[0]
    assert dim0.symbol == "BTC-USDT-SWAP"
    assert dim0.timeframe == "1H"
    assert dim0.is_metrics.total_return_pct is not None
    assert dim0.oos_metrics.total_return_pct is not None
