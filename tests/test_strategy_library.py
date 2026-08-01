from __future__ import annotations

import json
from decimal import Decimal

from hypertrade.db import Database
from hypertrade.memory.service import MemoryService
from hypertrade.strategy.evidence import (
    STRATEGY_EVIDENCE_SCHEMA_VERSION,
    StrategyEvidence,
    parse_strategy_evidence,
)
from hypertrade.strategy.iteration import StrategyIterationService
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


def _write_structured_strategy_memory(
    db: Database,
    *,
    experiment_id: str,
    backtest_id: str = "",
    bitpro_result_id: str = "",
    winner: str = "fast",
    total_return: str = "18.2500",
    drawdown: str = "2.7500",
    trade_count: str = "11",
) -> str:
    evidence = StrategyEvidence(
        strategy_key="momentum_breakout_v1",
        experiment_id=experiment_id,
        research_id="srch_structured",
        backtest_id=backtest_id,
        bitpro_result_id=bitpro_result_id,
        variant_id=winner,
        variant_count=3,
        parameters={"sma_period": "3", "breakout_pct": "0.0"},
        metrics={
            "total_return_pct": total_return,
            "max_drawdown_pct": drawdown,
            "trade_count": trade_count,
            "score": "16.875000",
        },
        gate_results={
            "min_trade_count": True,
            "max_drawdown_pct": True,
            "require_non_negative_return": True,
        },
        failure_reasons=[],
        source_data={
            "source": "bitpro_mcp_market_klines",
            "inst_id": "ETH-USDT-SWAP",
            "bar": "1H",
            "candle_count": "720",
        },
        next_experiment="Retest adjacent SMA windows on a larger BitPro candle window.",
        boundaries=["research_only", "no_bitpro_write", "no_live_or_testnet_order"],
        passed=True,
    )
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
        importance=Decimal("0.82"),
        confidence=Decimal("0.74"),
        content=evidence.to_memory_content(),
    )
    return item.id


def test_strategy_evidence_memory_content_round_trips_json_schema() -> None:
    evidence = StrategyEvidence(
        strategy_key="momentum_breakout_v1",
        experiment_id="exp_schema",
        research_id="srch_schema",
        backtest_id="bt_schema",
        bitpro_result_id="196",
        variant_id="fast",
        variant_count=3,
        parameters={"sma_period": "3"},
        metrics={"total_return_pct": "4.0441", "trade_count": "11"},
        gate_results={"min_trade_count": True},
        failure_reasons=[],
        source_data={"source": "bitpro_mcp_market_klines"},
        next_experiment="Retest on adjacent windows.",
        boundaries=["research_only"],
        passed=True,
    )

    parsed = parse_strategy_evidence(evidence.to_memory_content())

    assert parsed is not None
    assert parsed.schema_version == STRATEGY_EVIDENCE_SCHEMA_VERSION
    assert parsed.bitpro_result_id == "196"
    assert parsed.metrics["total_return_pct"] == "4.0441"
    assert parsed.parameters["sma_period"] == "3"


def test_strategy_library_prefers_structured_strategy_evidence_payload() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    memory_id = _write_structured_strategy_memory(
        db,
        experiment_id="exp_structured",
        backtest_id="bt_structured",
        bitpro_result_id="196",
    )

    summary = StrategyLibraryService(db).search(query="fast")

    item = summary["items"][0]
    assert summary["memory_count"] == 1
    assert item["strategy_key"] == "momentum_breakout_v1"
    assert item["best"]["schema_version"] == STRATEGY_EVIDENCE_SCHEMA_VERSION
    assert item["best"]["memory_id"] == memory_id
    assert item["best"]["experiment_id"] == "exp_structured"
    assert item["best"]["backtest_id"] == "bt_structured"
    assert item["best"]["bitpro_result_id"] == "196"
    assert item["best"]["variant_id"] == "fast"
    assert item["best"]["params"] == {"breakout_pct": "0.0", "sma_period": "3"}
    assert item["best"]["total_return_pct"] == "18.2500"
    assert item["best"]["max_drawdown_pct"] == "2.7500"
    assert item["best"]["trade_count"] == 11
    assert item["best"]["data"]["source"] == "bitpro_mcp_market_klines"
    assert item["best"]["boundaries"] == [
        "research_only",
        "no_bitpro_write",
        "no_live_or_testnet_order",
    ]
    assert item["source_memory_ids"] == [memory_id]


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


def test_strategy_library_aggregates_mixed_structured_and_legacy_memory() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    legacy_id = _write_strategy_memory(
        db,
        experiment_id="exp_legacy",
        backtest_id="bt_legacy",
        winner="baseline",
        passed=True,
        total_return="3.5",
        drawdown="1.2",
        trade_count=5,
        score="3.4",
        failure_reasons="none",
        next_experiment="Retest the baseline on more candles.",
    )
    structured_id = _write_structured_strategy_memory(
        db,
        experiment_id="exp_structured",
        backtest_id="bt_structured",
        winner="fast",
        total_return="9.25",
    )

    summary = StrategyLibraryService(db).search(query="baseline")

    item = summary["items"][0]
    assert item["evidence_count"] == 2
    assert item["best"]["memory_id"] == structured_id
    assert item["latest"]["memory_id"] == structured_id
    assert item["source_memory_ids"] == [legacy_id, structured_id]
    assert item["variants"] == [
        {"variant_id": "baseline", "evidence_count": 1, "passed_count": 1},
        {"variant_id": "fast", "evidence_count": 1, "passed_count": 1},
    ]


def test_strategy_library_uses_safe_defaults_for_missing_structured_fields() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    item = MemoryService(db).write(
        kind="strategy_knowledge",
        source_run_id="exp_minimal",
        source_tool="strategy.experiment",
        tags=["strategy", "strategy_experiment", "evidence", "minimal_strategy"],
        content="策略经验: StrategyEvidence\n"
        + json.dumps(
            {
                "schema_version": STRATEGY_EVIDENCE_SCHEMA_VERSION,
                "strategy_key": "minimal_strategy",
                "experiment_id": "exp_minimal",
            },
            sort_keys=True,
        ),
    )

    summary = StrategyLibraryService(db).search(strategy_key="minimal_strategy")

    best = summary["items"][0]["best"]
    assert best["memory_id"] == item.id
    assert best["research_id"] == ""
    assert best["backtest_id"] == ""
    assert best["bitpro_result_id"] == ""
    assert best["variant_id"] == "n/a"
    assert best["variant_count"] == 0
    assert best["params"] == {}
    assert best["total_return_pct"] == "n/a"
    assert best["max_drawdown_pct"] == "n/a"
    assert best["trade_count"] == 0
    assert best["data"] == {}
    assert best["gate_results"] == {}
    assert best["failure_reasons"] == []
    assert best["boundaries"] == []


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
    assert (
        StrategyLibraryService(db).search(strategy_key="momentum_breakout_v1")["items"][0][
            "strategy_key"
        ]
        == "momentum_breakout_v1"
    )


def test_strategy_iteration_plan_uses_prior_evidence_and_failure_constraints() -> None:
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

    plan = StrategyIterationService(db).plan("继续优化 momentum_breakout_v1")

    assert plan["mode"] == "evidence_driven"
    assert plan["strategy_key"] == "momentum_breakout_v1"
    assert plan["prior_evidence"]["source"] == "memory.strategy_knowledge"
    assert set(plan["prior_evidence"]["source_memory_ids"]) == {
        losing_memory_id,
        winning_memory_id,
    }
    assert plan["prior_evidence"]["best"]["memory_id"] == winning_memory_id
    assert plan["max_variants"] == 3
    assert len(plan["variants"]) <= 3
    assert plan["variants"][0]["variant_id"] == "evidence_baseline"
    assert plan["variants"][0]["source_memory_id"] == winning_memory_id
    assert all(item["reason"] for item in plan["variants"])
    assert any("require_non_negative_return" in item["reason"] for item in plan["variants"])


def test_strategy_iteration_plan_creates_first_baseline_without_prior_evidence() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()

    plan = StrategyIterationService(db).plan("研究新的动量突破")

    assert plan["mode"] == "first_baseline"
    assert plan["strategy_key"] == "momentum_breakout_v1"
    assert plan["prior_evidence"]["items"] == []
    assert plan["prior_evidence"]["source_memory_ids"] == []
    assert "first baseline" in plan["summary"]
    assert {item["variant_id"] for item in plan["variants"]} >= {
        "baseline",
        "fast",
        "conservative",
    }
    assert all(item["reason"] for item in plan["variants"])
