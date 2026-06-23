from __future__ import annotations

from decimal import Decimal

from hypertrade.db import Database
from hypertrade.memory.service import MemoryService
from hypertrade.strategy.library import StrategyLibraryService


def _write_strategy_memory(
    db: Database,
    *,
    experiment_id: str,
    backtest_id: str,
    winner: str,
    passed: bool,
    total_return: str,
    drawdown: str,
    trade_count: int,
    score: str,
    failure_reasons: str,
    next_experiment: str,
) -> str:
    item = MemoryService(db).write(
        kind="strategy_knowledge",
        source_run_id=experiment_id,
        source_tool="strategy.experiment",
        tags=[
            "strategy",
            "strategy_experiment",
            "evidence",
            "momentum_breakout_v1",
            f"winner:{winner}",
        ],
        importance=Decimal("0.82") if passed else Decimal("0.68"),
        confidence=Decimal("0.74"),
        content="\n".join(
            [
                "策略经验: local strategy experiment evidence",
                (
                    f"experiment={experiment_id}; research=srch_demo; "
                    f"backtest={backtest_id}; strategy=momentum_breakout_v1; "
                    f"winner={winner}; passed={str(passed).lower()}"
                ),
                "variant_count=3",
                "params=breakout_pct=0.0, sma_period=3",
                (
                    "metrics="
                    f"total_return_pct={total_return}; "
                    f"max_drawdown_pct={drawdown}; "
                    f"trade_count={trade_count}; score={score}"
                ),
                "data=source=sample_candles; inst_id=ETH-USDT-SWAP; bar=1H; candle_count=100",
                (
                    "gate_results=max_drawdown_pct=true, min_trade_count=true, "
                    "require_non_negative_return=true"
                ),
                f"failure_reasons={failure_reasons}",
                f"next_experiment={next_experiment}",
                "boundary=research_only; no_bitpro_write; no_live_or_testnet_order",
            ]
        ),
    )
    return item.id


def test_strategy_library_aggregates_strategy_knowledge_memory() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    losing_memory_id = _write_strategy_memory(
        db,
        experiment_id="exp_losing",
        backtest_id="bt_losing",
        winner="baseline",
        passed=False,
        total_return="-4.2",
        drawdown="6.5",
        trade_count=4,
        score="-1002.1",
        failure_reasons="require_non_negative_return",
        next_experiment="Reduce breakout_pct before retesting.",
    )
    winning_memory_id = _write_strategy_memory(
        db,
        experiment_id="exp_winning",
        backtest_id="bt_winning",
        winner="fast",
        passed=True,
        total_return="12.5",
        drawdown="3.1",
        trade_count=8,
        score="11.75",
        failure_reasons="none",
        next_experiment="Test adjacent SMA windows around 3 on BitPro MCP candles.",
    )

    summary = StrategyLibraryService(db).search(query="fast")

    assert summary["source"] == "memory.strategy_knowledge"
    assert summary["memory_count"] == 2
    assert len(summary["items"]) == 1
    item = summary["items"][0]
    assert item["strategy_key"] == "momentum_breakout_v1"
    assert item["evidence_count"] == 2
    assert item["passed_count"] == 1
    assert item["failed_count"] == 1
    assert item["best"]["memory_id"] == winning_memory_id
    assert item["best"]["variant_id"] == "fast"
    assert item["best"]["total_return_pct"] == "12.5"
    assert item["best"]["max_drawdown_pct"] == "3.1"
    assert item["best"]["trade_count"] == 8
    assert item["latest"]["memory_id"] == winning_memory_id
    assert item["variants"] == [
        {"variant_id": "baseline", "evidence_count": 1, "passed_count": 0},
        {"variant_id": "fast", "evidence_count": 1, "passed_count": 1},
    ]
    assert item["failure_reasons"] == ["require_non_negative_return"]
    assert item["next_experiments"] == [
        "Test adjacent SMA windows around 3 on BitPro MCP candles.",
        "Reduce breakout_pct before retesting.",
    ]
    assert item["source_memory_ids"] == [losing_memory_id, winning_memory_id]


def test_strategy_library_filters_by_strategy_key() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    _write_strategy_memory(
        db,
        experiment_id="exp_demo",
        backtest_id="bt_demo",
        winner="fast",
        passed=True,
        total_return="3.0",
        drawdown="1.0",
        trade_count=2,
        score="2.7",
        failure_reasons="none",
        next_experiment="Retest on longer window.",
    )

    assert StrategyLibraryService(db).search(strategy_key="missing")["items"] == []
    assert StrategyLibraryService(db).search(strategy_key="momentum_breakout_v1")[
        "items"
    ][0]["strategy_key"] == "momentum_breakout_v1"
