from decimal import Decimal

from hypertrade.agent.kernel import AgentKernel
from hypertrade.agent.planner import ToolCallRecord
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.market.analysis import summarize_candles
from hypertrade.market.okx import parse_okx_candle


def test_parse_okx_candle_array_payload() -> None:
    candle = parse_okx_candle(
        [
            "1764200000000",
            "2000.0",
            "2050.0",
            "1980.0",
            "2030.0",
            "120.5",
            "120.5",
            "244000.0",
            "1",
        ]
    )

    assert candle.open_time.isoformat() == "2025-11-26T23:33:20+00:00"
    assert candle.open == Decimal("2000.0")
    assert candle.high == Decimal("2050.0")
    assert candle.low == Decimal("1980.0")
    assert candle.close == Decimal("2030.0")
    assert candle.volume_ccy == Decimal("120.5")
    assert candle.volume_ccy_quote == Decimal("244000.0")
    assert candle.confirmed is True


def test_summarize_candles_calculates_trend_features() -> None:
    candles = [
        parse_okx_candle(row)
        for row in [
            ["1764200000000", "100", "110", "95", "105", "1", "1", "1000", "1"],
            ["1764203600000", "105", "115", "100", "110", "2", "2", "2000", "1"],
            ["1764207200000", "110", "125", "108", "121", "3", "3", "3000", "1"],
        ]
    ]

    summary = summarize_candles("ETH-USDT-SWAP", "1H", candles)

    assert summary["inst_id"] == "ETH-USDT-SWAP"
    assert summary["bar"] == "1H"
    assert summary["candle_count"] == 3
    assert summary["return_pct"] == "21.000000"
    assert summary["range_pct"] == "30.000000"
    assert summary["close_position_pct"] == "86.666666"
    assert summary["volume_ccy_quote_total"] == "6000.000000000000"
    assert summary["trend_bias"] == "up"


def test_planner_report_includes_market_candles_values() -> None:
    report = AgentKernel._render_planner_report(
        "趋势分析完成。\n\nResearch output only. Not investment advice.",
        [
            ToolCallRecord(
                tool_name="market_candles",
                input_json={"symbol": "ETH", "bar": "1H", "limit": 100},
                output_json={
                    "inst_id": "ETH-USDT-SWAP",
                    "bar": "1H",
                    "found": True,
                    "candle_count": 100,
                    "return_pct": "3.210000",
                    "range_pct": "8.760000",
                    "close_position_pct": "71.420000",
                    "ma20": "2010.500000000000",
                    "ma60": "1988.100000000000",
                    "trend_bias": "up",
                    "data_source": "okx_rest",
                    "as_of_utc": "2026-05-29T09:00:00+00:00",
                },
            )
        ],
    )

    assert "## K线趋势特征" in report
    assert "ETH-USDT-SWAP" in report
    assert "周期: 1H" in report
    assert "区间涨跌幅 3.210000%" in report
    assert "趋势偏向 up" in report


def test_planner_report_distinguishes_bitpro_paper_dashboard_scope() -> None:
    report = AgentKernel._render_planner_report(
        "模拟盘状态读取完成。",
        [
            ToolCallRecord(
                tool_name="bitpro_paper_dashboard",
                input_json={},
                output_json={
                    "status": "ok",
                    "contract_version": "bitpro-mcp-v1",
                    "dashboard": {
                        "system": {
                            "state": "running",
                            "mode": "paper",
                            "uptime": "26D",
                            "strategy_id": 105,
                            "strategy": "[合约][1H][CTA] SOL · EMA5/20趋势跟踪对照版 · 100U",
                        },
                        "equity": {"current": 106.08},
                        "performance": {
                            "total_pnl_pct": 6.08,
                            "sharpe_ratio": 1.6,
                            "max_drawdown": 3.63,
                        },
                    },
                    "paper_scope": {
                        "dashboard_scope": "current_instance",
                        "current_strategy_id": 105,
                        "running_strategy_count": 2,
                        "coverage_note": (
                            "paper_dashboard exposes the current BitPro paper dashboard only"
                        ),
                    },
                    "running_strategies": {
                        "total": 2,
                        "items": [
                            {
                                "id": 105,
                                "name": "[合约][1H][CTA] SOL · EMA5/20趋势跟踪对照版 · 100U",
                                "status": "running",
                                "symbols": ["SOL/USDT:USDT"],
                            },
                            {
                                "id": 293,
                                "name": "[合约][1H][CTA] ETH · Agent EMA ATR 回撤 · 100U",
                                "status": "running",
                                "symbols": ["ETH/USDT:USDT"],
                            },
                        ],
                    },
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                        {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                        {"tool": "paper_dashboard", "parameters": {}, "status": "success"},
                        {
                            "tool": "strategy_search",
                            "parameters": {"status": "running"},
                            "status": "success",
                        },
                    ],
                },
            )
        ],
    )

    assert "## BitPro 模拟盘状态" in report
    assert "Dashboard 范围: current_instance" in report
    assert "当前 dashboard: strategy_id=105" in report
    assert "strategy_search(status=running) 返回 2 个" in report
    assert "293: [合约][1H][CTA] ETH · Agent EMA ATR 回撤 · 100U [running]" in report
    assert "paper_dashboard exposes the current BitPro paper dashboard only" in report


def test_market_candles_payload_uses_fetcher_and_returns_features(monkeypatch, tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    kernel = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="", DATABASE_URL="sqlite:///:memory:"),
        knowledge_dir=str(tmp_path),
    )

    def fake_fetch(inst_id: str, bar: str, limit: int):
        assert inst_id == "SOL-USDT-SWAP"
        assert bar == "4H"
        assert limit == 2
        return [
            parse_okx_candle(["1764200000000", "100", "110", "95", "105", "1", "1", "1000", "1"]),
            parse_okx_candle(["1764214400000", "105", "120", "104", "118", "2", "2", "2000", "1"]),
        ]

    monkeypatch.setattr(kernel, "_fetch_market_candles", fake_fetch)

    payload = kernel._market_candles_payload(symbol="sol", bar="4h", limit=2)

    assert payload["found"] is True
    assert payload["inst_id"] == "SOL-USDT-SWAP"
    assert payload["bar"] == "4H"
    assert payload["return_pct"] == "18.000000"
    assert payload["data_source"] == "okx_rest"
