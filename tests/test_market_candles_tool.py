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
                    "monitor_summary": {
                        "mode": "read_only",
                        "current_dashboard": {
                            "strategy_id": 105,
                            "strategy_name": (
                                "[合约][1H][CTA] SOL · EMA5/20趋势跟踪对照版 · 100U"
                            ),
                            "state": "running",
                            "mode": "paper",
                            "total_pnl_pct": "-3.3",
                            "max_drawdown_pct": "12.4",
                            "sharpe_ratio": "0.2",
                            "equity": "96.7",
                        },
                        "running_inventory": {
                            "listed_count": 2,
                            "reported_total": 5,
                            "is_truncated": True,
                        },
                        "alerts": [
                            {
                                "level": "warning",
                                "code": "negative_pnl",
                                "message": "当前 dashboard 策略总收益为负: -3.3%",
                            },
                            {
                                "level": "warning",
                                "code": "high_drawdown",
                                "message": "当前 dashboard 策略最大回撤偏高: 12.4%",
                            },
                        ],
                        "data_gaps": [
                            (
                                "running strategy inventory does not include "
                                "per-strategy PnL/drawdown metrics"
                            ),
                        ],
                        "recommended_actions": [
                            {
                                "action": "inspect_current_dashboard_strategy",
                                "message": "优先检查当前 dashboard 策略 105 的成交、事件和权益曲线",
                            },
                            {
                                "action": "continue_read_only_monitoring",
                                "message": "继续只读监控；不要自动暂停、停止或实盘操作",
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
    assert "不能据此判断 BitPro 全局实盘功能关闭" in report
    assert "strategy_search(status=running) 返回 2 个" in report
    assert "293: [合约][1H][CTA] ETH · Agent EMA ATR 回撤 · 100U [running]" in report
    assert "监控结论: read_only" in report
    assert "运行策略覆盖: 已列出 2 个，BitPro 返回总数 5 个，清单未完全展开" in report
    assert "告警 warning/negative_pnl: 当前 dashboard 策略总收益为负: -3.3%" in report
    assert (
        "数据缺口: running strategy inventory does not include per-strategy "
        "PnL/drawdown metrics"
    ) in report
    assert "建议 inspect_current_dashboard_strategy: 优先检查当前 dashboard 策略 105" in report
    assert "建议 continue_read_only_monitoring: 继续只读监控" in report
    assert "paper_dashboard exposes the current BitPro paper dashboard only" in report


def test_planner_report_renders_bitpro_paper_event_and_equity_evidence() -> None:
    report = AgentKernel._render_planner_report(
        "模拟盘事件和权益曲线读取完成。",
        [
            ToolCallRecord(
                tool_name="bitpro_paper_events",
                input_json={"strategy_id": 105, "limit": 5},
                output_json={
                    "status": "ok",
                    "contract_version": "bitpro-mcp-v1",
                    "strategy_id": 105,
                    "limit": 5,
                    "events": [
                        {
                            "id": 9001,
                            "strategy_id": 105,
                            "level": "error",
                            "type": "order_rejected",
                            "message": "insufficient paper balance",
                            "timestamp": "2026-06-23T09:10:00Z",
                        },
                        {
                            "id": 9000,
                            "strategy_id": 105,
                            "level": "info",
                            "type": "heartbeat",
                            "message": "loop ok",
                            "timestamp": "2026-06-23T09:09:00Z",
                        },
                    ],
                    "event_summary": {
                        "count": 2,
                        "sample_count": 2,
                        "error_count": 1,
                        "latest_event_at": "2026-06-23T09:10:00Z",
                    },
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                        {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                        {
                            "tool": "paper_events",
                            "parameters": {"strategy_id": 105, "limit": 5},
                            "status": "success",
                        },
                    ],
                },
            ),
            ToolCallRecord(
                tool_name="bitpro_paper_equity_curve",
                input_json={"strategy_id": 105, "sample_limit": 2},
                output_json={
                    "status": "ok",
                    "contract_version": "bitpro-mcp-v1",
                    "strategy_id": 105,
                    "sample_limit": 2,
                    "equity_curve": [
                        {
                            "timestamp": "2026-06-23T07:00:00Z",
                            "equity": "100",
                            "drawdown_pct": "0",
                        },
                        {
                            "timestamp": "2026-06-23T08:00:00Z",
                            "equity": "101.25",
                            "drawdown_pct": "1.5",
                        },
                    ],
                    "equity_summary": {
                        "count": 3,
                        "sample_count": 2,
                        "latest_at": "2026-06-23T09:00:00Z",
                        "latest_equity": "102.5",
                        "latest_drawdown_pct": "0.8",
                        "max_drawdown_pct": "1.5",
                    },
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                        {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                        {
                            "tool": "paper_equity_curve",
                            "parameters": {"strategy_id": 105},
                            "status": "success",
                        },
                    ],
                },
            ),
        ],
    )

    assert "## BitPro 模拟盘状态" in report
    assert "事件证据: strategy_id=105, events=2, sample=2, errors=1" in report
    assert "9001 error/order_rejected: insufficient paper balance" in report
    assert "权益曲线证据: strategy_id=105, points=3, sample=2" in report
    assert "latest_equity=102.5" in report
    assert "max_drawdown=1.5%" in report


def test_planner_report_renders_bitpro_backtest_total_return_results() -> None:
    report = AgentKernel._render_planner_report(
        "已读取 BitPro 回测结果。",
        [
            ToolCallRecord(
                tool_name="bitpro_backtest_list_results",
                input_json={"min_total_return_pct": 100},
                output_json={
                    "status": "ok",
                    "contract_version": "bitpro-mcp-v1",
                    "filter": {
                        "metric": "total_return_pct",
                        "min_total_return_pct": 100,
                        "status": "completed",
                        "sort_by": "return",
                        "sort_order": "desc",
                        "limit": 40,
                    },
                    "result_count": 2,
                    "raw_result_count": 21,
                    "results": [
                        {
                            "id": 161,
                            "strategy_id": 178,
                            "strategy_name": (
                                "[合约][1D][CTA] ETH · "
                                "Donchian89/EMA89趋势跟踪稳健版 · 100U"
                            ),
                            "total_return_pct": "305.53878586955756",
                            "annual_return_pct": "80.6615",
                            "max_drawdown_pct": "30.4763",
                            "sharpe_ratio": "1.1422",
                            "win_rate_pct": "87.5",
                            "trade_count": 8,
                            "start_date": "2024-01-01",
                            "end_date": "2026-05-15",
                        },
                        {
                            "id": 193,
                            "strategy_id": 162,
                            "strategy_name": (
                                "[合约][1H][CTA] ETH · "
                                "Heikin Ashi趋势跟踪低频版 · 100U"
                            ),
                            "total_return_pct": "141.83713784801657",
                            "annual_return_pct": "142.4246",
                            "max_drawdown_pct": "14.5667",
                            "sharpe_ratio": "0.3969",
                            "win_rate_pct": "50.63",
                            "trade_count": 239,
                            "start_date": "2025-06-08",
                            "end_date": "2026-06-07",
                        },
                    ],
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                        {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                        {
                            "tool": "backtest_list_results",
                            "parameters": {"offset": 0, "limit": 20},
                            "status": "success",
                        },
                    ],
                },
            )
        ],
    )

    assert "## BitPro 回测结果" in report
    assert "口径: total_return_pct" in report
    assert "过滤: total_return_pct > 100%" in report
    assert "命中数量: 2" in report
    assert "result #161, strategy #178" in report
    assert "Donchian89/EMA89趋势跟踪稳健版" in report
    assert "收益 305.53878586955756%" in report
    assert "result #193, strategy #162" in report
    assert "Heikin Ashi趋势跟踪低频版" in report


def test_planner_report_renders_completed_bitpro_backtest_job_result() -> None:
    report = AgentKernel._render_planner_report(
        "Planning loop reached max iterations.",
        [
            ToolCallRecord(
                tool_name="bitpro_backtest_start_job",
                input_json={"strategy_id": 292},
                output_json={
                    "status": "ok",
                    "job": {"job_id": "job_292", "strategy_id": 292, "status": "started"},
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                        {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                        {"tool": "backtest_start_job", "parameters": {}, "status": "success"},
                    ],
                },
            ),
            ToolCallRecord(
                tool_name="bitpro_backtest_get_job",
                input_json={"job_id": "job_292"},
                output_json={
                    "status": "ok",
                    "contract_version": "bitpro-mcp-v1",
                    "job": {
                        "job_id": "job_292",
                        "strategy_id": 292,
                        "status": "completed",
                        "percent": 100.0,
                        "updated_at": "2026-06-12 09:36:15",
                    },
                    "backtest_result": {
                        "id": 197,
                        "strategy_id": 292,
                        "strategy_name": (
                            "[合约][4H][CTA] Top20 · 波动压缩突破高收益实验 · 100U"
                        ),
                        "status": "completed",
                        "start_date": "2026-01-01",
                        "end_date": "2026-06-12",
                        "timeframe": "4h",
                        "metrics": {
                            "total_return_pct": "9.701471818245139",
                            "annual_return_pct": "23.1976",
                            "max_drawdown_pct": "5.6088",
                            "sharpe_ratio": "0.494",
                            "win_rate_pct": "56.52",
                            "trade_count": 23,
                            "final_capital": "109.70147181824514",
                        },
                    },
                    "artifact_summary": {
                        "equity_curve": {"available": True, "count": 19461, "sample_count": 20},
                        "trades": {"available": True, "count": 23, "sample_count": 20},
                    },
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                        {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                        {"tool": "backtest_get_job", "parameters": {}, "status": "success"},
                        {"tool": "backtest_list_results", "parameters": {}, "status": "success"},
                    ],
                },
            ),
        ],
    )

    assert "## BitPro 回测结果" in report
    assert "回测任务: job=job_292, status=completed, progress=100.0%" in report
    assert "result #197, strategy #292" in report
    assert "波动压缩突破高收益实验" in report
    assert "### 核心指标" in report
    assert "收益: 9.701471818245139%" in report
    assert "年化收益: 23.1976%" in report
    assert "最大回撤: 5.6088%" in report
    assert "胜率: 56.52%" in report
    assert "交易次数: 23" in report
    assert "权益曲线: 可用，19461 条" in report
    assert "Planning loop reached max iterations" not in report
    assert "## BitPro 策略生命周期" not in report


def test_planner_report_renders_bitpro_backtest_artifact_detail() -> None:
    report = AgentKernel._render_planner_report(
        "### 模型自由发挥\n- 不应该出现在 BitPro 证据报告里",
        [
            ToolCallRecord(
                tool_name="bitpro_backtest_start_job",
                input_json={"strategy_id": 293},
                output_json={
                    "status": "ok",
                    "job": {"job_id": "job_196", "status": "completed"},
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                        {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                        {"tool": "backtest_start_job", "parameters": {}, "status": "success"},
                    ],
                },
            ),
            ToolCallRecord(
                tool_name="bitpro_backtest_get_result",
                input_json={"backtest_id": "196", "sample_limit": 2},
                output_json={
                    "status": "ok",
                    "contract_version": "bitpro-mcp-v1",
                    "result": {
                        "id": 196,
                        "strategy_id": 293,
                        "strategy_name": "[合约][1H][CTA] ETH · Agent EMA ATR 回撤 · 100U",
                        "status": "completed",
                        "start_date": "2026-05-10",
                        "end_date": "2026-06-09",
                        "symbol": "ETH/USDT:USDT",
                        "timeframe": "1h",
                        "metrics": {
                            "total_return_pct": "4.044128",
                            "max_drawdown_pct": "1.4438",
                            "sharpe_ratio": "0.8029",
                            "win_rate_pct": "63.64",
                            "trade_count": 11,
                        },
                    },
                    "artifact_summary": {
                        "equity_curve": {"available": True, "count": 3, "sample_count": 2},
                        "trades": {"available": True, "count": 11, "sample_count": 2},
                        "orders": {"available": False, "count": 0, "sample_count": 0},
                        "fills": {"available": True, "count": 11, "sample_count": 2},
                        "drawdown_series": {"available": True, "count": 3, "sample_count": 2},
                    },
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                        {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                        {
                            "tool": "backtest_get_result",
                            "parameters": {"backtest_id": "196"},
                            "status": "success",
                        },
                    ],
                },
            )
        ],
    )

    assert "## BitPro 回测详情" in report
    assert "result #196, strategy #293" in report
    assert "Agent EMA ATR 回撤" in report
    assert "### 核心指标" in report
    assert "收益: 4.044128%" in report
    assert "最大回撤: 1.4438%" in report
    assert "权益曲线: 可用，3 条，展示 2 条样本" in report
    assert "订单: 不可用，0 条，展示 0 条样本" in report
    assert "backtest_get_result" not in report
    assert "## BitPro 策略生命周期" not in report
    assert "bitpro_backtest_start_job" not in report
    assert "模型自由发挥" not in report
    assert "不应该出现在 BitPro 证据报告里" not in report


def test_planner_report_keeps_bitpro_backtest_output_page_focused() -> None:
    report = AgentKernel._render_planner_report(
        "### 模型自由发挥\n- 不应该盖过 BitPro 结果",
        [
            ToolCallRecord(
                tool_name="rag_search",
                input_json={"query": "BitPro 回测"},
                output_json={
                    "hits": [
                        {
                            "title": "HyperTrade 工具运维指南",
                            "source_path": "docs/knowledge/tool-usage-guide.md",
                            "chunk_index": 2,
                            "score": 1.23,
                            "content": "BitPro tool usage.",
                        }
                    ]
                },
            ),
            ToolCallRecord(
                tool_name="bitpro_backtest_start_job",
                input_json={"strategy_id": 292},
                output_json={
                    "status": "ok",
                    "job": {
                        "job_id": "job_292",
                        "status": "completed",
                        "percent": 100,
                    },
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                        {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                        {"tool": "backtest_start_job", "parameters": {}, "status": "success"},
                    ],
                },
            ),
            ToolCallRecord(
                tool_name="bitpro_backtest_get_result",
                input_json={"backtest_id": "200", "sample_limit": 20},
                output_json={
                    "status": "ok",
                    "contract_version": "bitpro-mcp-v1",
                    "result": {
                        "id": 200,
                        "strategy_id": 292,
                        "strategy_name": "[合约][4H][CTA] Top20 · 波动压缩突破高收益实验 · 100U",
                        "status": "completed",
                        "start_date": "2026-02-01",
                        "end_date": "2026-06-01",
                        "symbol": None,
                        "timeframe": "4h",
                        "metrics": {
                            "total_return_pct": "3.8734033137765063",
                            "max_drawdown_pct": "5.6088",
                            "sharpe_ratio": "0.3181",
                            "win_rate_pct": "50",
                            "trade_count": 18,
                        },
                    },
                    "artifact_summary": {
                        "equity_curve": {"available": True, "count": 721, "sample_count": 20},
                        "trades": {"available": True, "count": 36, "sample_count": 20},
                        "orders": {"available": False, "count": 0, "sample_count": 0},
                        "fills": {"available": False, "count": 0, "sample_count": 0},
                        "drawdown_series": {"available": False, "count": 0, "sample_count": 0},
                    },
                    "tool_calls": [
                        {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                        {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                        {
                            "tool": "backtest_get_result",
                            "parameters": {"backtest_id": "200"},
                            "status": "success",
                        },
                    ],
                },
            ),
        ],
    )

    assert "## BitPro 回测详情" in report
    assert "result #200, strategy #292" in report
    assert "### 核心指标" in report
    assert "收益: 3.8734033137765063%" in report
    assert "最大回撤: 5.6088%" in report
    assert "权益曲线: 可用，721 条，展示 20 条样本" in report
    assert "## BitPro 策略生命周期" not in report
    assert "bitpro_backtest_start_job" not in report
    assert "## 引用来源" not in report
    assert "HyperTrade 工具运维指南" not in report
    assert "合同版本" not in report
    assert "工具顺序" not in report
    assert "backtest_get_result" not in report
    assert "模型自由发挥" not in report


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
