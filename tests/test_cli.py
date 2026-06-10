from __future__ import annotations

from collections.abc import Iterator
from io import StringIO
from typing import Any

import httpx
from hypertrade.cli import (
    SLASH_COMMAND_HELP,
    AgentApiClient,
    CliConfig,
    LocalAgentClient,
    main,
    render_backtest_result,
    render_run,
    render_run_stream,
    render_slash_help,
    render_strategy_research_result,
    render_tools,
    render_welcome_banner,
    run_chat,
)


class TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class FakeAgentClient:
    def __init__(self) -> None:
        self.logged_in = False
        self.prompts: list[str] = []
        self.research_prompts: list[str] = []
        self.experiment_prompts: list[str] = []
        self.backtest_calls: list[dict[str, Any]] = []
        self.price_symbols: list[str] = []
        self.candle_calls: list[dict[str, Any]] = []
        self.compare_calls: list[dict[str, Any]] = []
        self.paper_actions: list[str] = []
        self.live_decisions: list[dict[str, str]] = []
        self.selected_model = "deepseek"
        self.disabled_memory_ids: list[str] = []

    def login(self) -> None:
        self.logged_in = True

    def run_agent(self, prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        return {
            "id": "run_cli",
            "status": "completed",
            "report_markdown": "# CLI Report\n\nResearch only. Not investment advice.",
            "trace_events": [
                {"tool_name": "market.summary", "status": "completed"},
                {"tool_name": "memory.write", "status": "completed"},
            ],
        }

    def run_agent_events(self, prompt: str):
        self.prompts.append(prompt)
        yield {"event": "run_started", "run_id": "pending", "status": "running"}
        yield {"event": "tool_started", "tool_name": "market.summary"}
        yield {"event": "tool_completed", "tool_name": "market.summary", "status": "completed"}
        yield {
            "event": "run_completed",
            "run": {
                "id": "run_cli",
                "status": "completed",
                "report_markdown": "# CLI Report\n\nResearch only. Not investment advice.",
                "trace_events": [
                    {"tool_name": "market.summary", "status": "completed"},
                    {"tool_name": "memory.write", "status": "completed"},
                ],
            },
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "market.summary",
                "category": "market",
                "requires_approval": False,
                "description": "Summarize market.",
            },
            {
                "name": "live.order_intent",
                "category": "live",
                "requires_approval": True,
                "description": "Create order intent.",
            },
        ]

    def list_runs(self) -> list[dict[str, Any]]:
        return [{"id": "run_recent", "status": "completed", "prompt": "请做行情归纳"}]

    def list_memory(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "mem_recent",
                "kind": "market_summary",
                "content": "BTC was reviewed",
                "tags": ["market_summary"],
                "usage_count": 1,
            }
        ]

    def search_memory(self, query: str) -> list[dict[str, Any]]:
        return [
            {
                "id": "mem_search",
                "kind": "user_preference",
                "content": f"Memory match for {query}",
                "tags": ["preference"],
                "usage_count": 2,
            }
        ]

    def disable_memory(self, memory_id: str) -> dict[str, Any]:
        self.disabled_memory_ids.append(memory_id)
        return {"status": "ok"}

    def search_rag(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return [
            {
                "source_path": "docs/knowledge/rag-usage.md",
                "title": "RAG Usage",
                "chunk_index": 0,
                "score": 1.25,
                "content_preview": f"Knowledge match for {query}",
            }
        ]

    def get_evals_status(self) -> dict[str, Any]:
        return {
            "status": "passed",
            "cases": [
                {"name": "tool_selection", "status": "passed"},
                {"name": "rag_citation", "status": "passed"},
            ],
        }

    def list_strategy_research(self) -> list[dict[str, Any]]:
        return [{"id": "srch_recent", "strategy_key": "momentum_breakout_v1", "title": "趋势突破"}]

    def list_backtests(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "bt_recent",
                "strategy_key": "momentum_breakout_v1",
                "status": "completed",
                "metrics": {"total_return_pct": "0.019000", "trade_count": 1},
            }
        ]

    def get_paper_status(self) -> dict[str, Any]:
        return {
            "session": {
                "id": "paper_cli",
                "status": "running",
                "cash": "100000",
                "equity": "100250",
                "realized_pnl": "12.5",
            },
            "positions": [
                {
                    "inst_id": "ETH-USDT-SWAP",
                    "side": "long",
                    "quantity": "1.2",
                    "entry_price": "1900",
                    "mark_price": "1980",
                    "notional": "2376",
                    "unrealized_pnl": "96",
                }
            ],
            "recent_fills": [
                {
                    "inst_id": "ETH-USDT-SWAP",
                    "side": "long",
                    "quantity": "1.2",
                    "price": "1900",
                    "fee": "1.14",
                    "created_at": "2026-06-02T08:00:00+00:00",
                }
            ],
            "recent_events": [
                {
                    "kind": "fill",
                    "message": "Paper long fill for ETH-USDT-SWAP",
                    "created_at": "2026-06-02T08:00:00+00:00",
                }
            ],
        }

    def control_paper(self, action: str, *, symbol: str | None = None) -> dict[str, Any]:
        self.paper_actions.append(action)
        if action == "close":
            return {
                "session": {
                    "id": "paper_cli",
                    "status": "running",
                    "cash": "100050",
                    "equity": "100050",
                    "realized_pnl": "50",
                },
                "closed_count": 1,
                "closed": [
                    {
                        "inst_id": f"{(symbol or 'ETH').upper()}-USDT-SWAP",
                        "side": "long",
                        "exit_price": "2000",
                        "realized_pnl": "50",
                    }
                ],
            }
        if action == "reset":
            return {
                "session": {
                    "id": "paper_new",
                    "status": "running",
                    "cash": "100000",
                    "equity": "100000",
                    "realized_pnl": "0",
                }
            }
        return {
            "session": {
                "id": "paper_cli",
                "status": "paused" if action == "pause" else "running",
                "cash": "100000",
                "equity": "100250",
                "realized_pnl": "12.5",
            }
        }

    def get_status(self) -> dict[str, Any]:
        return {
            "mode": "test",
            "database_url": "sqlite:///:memory:",
            "agent_runs": 1,
            "memory_items": 1,
            "tools": 2,
        }

    def create_strategy_research(self, prompt: str) -> dict[str, Any]:
        self.research_prompts.append(prompt)
        return {
            "id": "srch_cli",
            "strategy_key": "momentum_breakout_v1",
            "title": "趋势突破",
            "report_markdown": "# Research\n\nBTC breakout study.",
        }

    def create_strategy_experiment(self, prompt: str) -> dict[str, Any]:
        self.experiment_prompts.append(prompt)
        return {
            "id": "exp_cli",
            "status": "completed",
            "research_id": "srch_cli",
            "backtest_id": "bt_cli",
            "report_markdown": "# Experiment\n\nCritique and next experiment. 不构成投资建议。",
        }

    def run_backtest(
        self,
        *,
        research_id: str = "",
        strategy_key: str = "momentum_breakout_v1",
        use_live_candles: bool = False,
        symbol: str = "BTC",
        bar: str = "1H",
        candle_limit: int = 100,
        candle_source: str = "sample",
    ) -> dict[str, Any]:
        self.backtest_calls.append(
            {
                "research_id": research_id,
                "strategy_key": strategy_key,
                "use_live_candles": use_live_candles,
                "symbol": symbol,
                "bar": bar,
                "candle_limit": candle_limit,
                "candle_source": candle_source,
            }
        )
        return {
            "id": "bt_cli",
            "research_id": research_id,
            "strategy_key": strategy_key,
            "status": "completed",
            "metrics": {"total_return_pct": "0.019000", "trade_count": 1},
            "report_markdown": "# Backtest\n\nReturn 1.9%.",
        }

    def get_market_ticker(self, symbol: str) -> dict[str, Any]:
        self.price_symbols.append(symbol)
        return {
            "found": True,
            "inst_id": f"{symbol.upper()}-USDT-SWAP",
            "last": "3500.000000000000",
            "change_utc0_pct": "1.230000",
            "volume_ccy_24h": "987654.000000000000",
            "data_source": "okx_rest",
            "as_of_utc": "2026-06-02T08:00:00+00:00",
        }

    def get_market_candles(
        self,
        *,
        symbol: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> dict[str, Any]:
        self.candle_calls.append({"symbol": symbol, "bar": bar, "limit": limit})
        return {
            "found": True,
            "inst_id": f"{symbol.upper()}-USDT-SWAP",
            "bar": bar,
            "candle_count": limit,
            "return_pct": "2.400000",
            "range_pct": "7.500000",
            "close_position_pct": "72.000000",
            "ma20": "2000.000000000000",
            "ma60": "1975.000000000000",
            "trend_bias": "up",
            "data_source": "okx_rest",
            "as_of_utc": "2026-06-02T08:00:00+00:00",
        }

    def compare_markets(
        self,
        *,
        symbols: list[str],
        bar: str = "4H",
        limit: int = 100,
    ) -> dict[str, Any]:
        self.compare_calls.append({"symbols": symbols, "bar": bar, "limit": limit})
        return {
            "found": True,
            "bar": bar,
            "leader": "ETH-USDT-SWAP",
            "rankings": [
                {
                    "rank": 1,
                    "inst_id": "ETH-USDT-SWAP",
                    "strength_score": "75.000000",
                    "return_pct": "2.500000",
                    "close_position_pct": "70.000000",
                    "trend_bias": "up",
                },
                {
                    "rank": 2,
                    "inst_id": "SOL-USDT-SWAP",
                    "strength_score": "20.000000",
                    "return_pct": "-3.000000",
                    "close_position_pct": "25.000000",
                    "trend_bias": "down",
                },
            ],
            "data_source": "okx_rest",
            "as_of_utc": "2026-06-02T08:00:00+00:00",
        }

    def get_model_status(self) -> dict[str, Any]:
        return {
            "default_provider": self.selected_model,
            "model": "deepseek-v4-flash",
            "providers": [
                {
                    "name": "deepseek",
                    "display_name": "DeepSeek",
                    "model": "deepseek-v4-flash",
                    "enabled": True,
                    "default": True,
                    "key_status": "configured",
                }
            ],
        }

    def set_model(self, provider: str) -> dict[str, Any]:
        self.selected_model = provider
        return self.get_model_status()

    def list_live_order_intents(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "loi_recent",
                "environment": "testnet",
                "status": "pending_approval",
                "inst_id": "ETH-USDT-SWAP",
                "side": "buy",
                "order_type": "market",
                "size": "0.01",
                "price": None,
                "reason": "test intent",
            }
        ]

    def create_live_order_intent(
        self,
        *,
        symbol: str,
        side: str,
        size: str,
        order_type: str = "market",
        price: str | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        return {
            "id": "loi_new",
            "environment": "testnet",
            "status": "pending_approval",
            "inst_id": f"{symbol.upper()}-USDT-SWAP",
            "side": side,
            "order_type": order_type,
            "size": size,
            "price": price,
            "reason": reason,
        }

    def decide_live_order_intent(
        self,
        intent_id: str,
        *,
        decision: str,
        reason: str = "",
    ) -> dict[str, Any]:
        self.live_decisions.append({"intent_id": intent_id, "decision": decision, "reason": reason})
        return {
            "id": intent_id,
            "environment": "testnet",
            "status": "approved" if decision == "approve" else "rejected",
            "inst_id": "ETH-USDT-SWAP",
            "side": "buy",
            "order_type": "market",
            "size": "0.01",
            "price": None,
            "reason": "test intent",
            "decision_reason": reason,
        }

    def execute_live_order_intent(self, intent_id: str) -> dict[str, Any]:
        return {
            "id": intent_id,
            "environment": "testnet",
            "status": "execution_failed",
            "inst_id": "ETH-USDT-SWAP",
            "side": "buy",
            "order_type": "market",
            "size": "0.01",
            "price": None,
            "reason": "test intent",
            "risk_status": "allowed",
            "exchange_order_id": "",
        }


def test_ask_prints_agent_run_trace_and_report(capsys) -> None:
    client = FakeAgentClient()

    exit_code = main(["ask", "请做行情归纳"], client=client)

    assert exit_code == 0
    assert client.logged_in is True
    assert client.prompts == ["请做行情归纳"]
    output = capsys.readouterr().out
    assert "run_cli" in output
    assert "market.summary" in output
    assert "# CLI Report" in output


def test_render_run_prefers_structured_market_summary_over_raw_markdown(capsys) -> None:
    render_run(
        {
            "id": "run_structured",
            "status": "completed",
            "report_markdown": "# Raw Markdown Should Not Render",
            "report_json": {
                "market_scope": "OKX SWAP",
                "trigger": "user_request",
                "data_source": "okx_rest",
                "as_of_utc": "2026-06-02T08:00:00+00:00",
                "top_movers": [
                    {
                        "inst_id": "ETH-USDT-SWAP",
                        "last": "3500.000000000000",
                        "change_utc0_pct": "1.230000",
                        "volume_ccy_24h": "987654.000000000000",
                    }
                ],
                "rag_hits": [{"source_path": "docs/knowledge/risk.md", "score": 0.91}],
                "disclaimer": "Research output only. Not investment advice.",
            },
            "trace_events": [
                {"tool_name": "market.summary", "status": "completed"},
                {"tool_name": "rag.search", "status": "completed"},
            ],
        }
    )

    output = capsys.readouterr().out
    assert "Market Report" in output
    assert "Scope: OKX SWAP" in output
    assert "Source: okx_rest" in output
    assert "Top movers:" in output
    assert "ETH-USDT-SWAP" in output
    assert "Knowledge hits:" in output
    assert "Raw Markdown Should Not Render" not in output
    assert "Research output only. Not investment advice." not in output


def test_render_run_prefers_structured_tool_outputs_over_planner_markdown(capsys) -> None:
    render_run(
        {
            "id": "run_tools",
            "status": "completed",
            "report_markdown": "# Planner Markdown Should Not Render",
            "report_json": {
                "planner": "deepseek",
                "disclaimer": "Research output only. Not investment advice.",
            },
            "trace_events": [
                {
                    "tool_name": "market_ticker",
                    "status": "completed",
                    "output_json": {
                        "found": True,
                        "inst_id": "ETH-USDT-SWAP",
                        "last": "3500.000000000000",
                        "change_utc0_pct": "1.230000",
                        "volume_ccy_24h": "987654.000000000000",
                        "data_source": "okx_rest",
                    },
                },
                {
                    "tool_name": "market_candles",
                    "status": "completed",
                    "output_json": {
                        "found": True,
                        "inst_id": "ETH-USDT-SWAP",
                        "bar": "1H",
                        "candle_count": 100,
                        "return_pct": "2.400000",
                        "trend_bias": "up",
                        "data_source": "okx_rest",
                    },
                },
            ],
        }
    )

    output = capsys.readouterr().out
    assert "Agent Report" in output
    assert "Ticker:" in output
    assert "Trend:" in output
    assert "ETH-USDT-SWAP" in output
    assert "Planner Markdown Should Not Render" not in output
    assert "Research output only. Not investment advice." not in output


def test_welcome_banner_does_not_repeat_fixed_risk_warning() -> None:
    output = StringIO()

    render_welcome_banner(client=FakeAgentClient(), output=output)

    rendered = output.getvalue()
    assert "HyperTrade" in rendered
    assert "风险提示：本工具输出仅用于研究辅助，不构成投资建议。" not in rendered
    assert "Research only. Not investment advice." not in rendered


def test_render_run_can_use_rich_structured_output(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    output = StringIO()

    render_run(
        {
            "id": "run_rich",
            "status": "completed",
            "report_markdown": "# Rich Markdown Should Not Render",
            "report_json": {
                "planner": "deepseek",
                "disclaimer": "Research output only. Not investment advice.",
            },
            "trace_events": [
                {
                    "tool_name": "market_ticker",
                    "status": "completed",
                    "output_json": {
                        "found": True,
                        "inst_id": "ETH-USDT-SWAP",
                        "last": "3500.000000000000",
                        "change_utc0_pct": "1.230000",
                        "volume_ccy_24h": "987654.000000000000",
                        "data_source": "okx_rest",
                    },
                }
            ],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "┏" in rendered
    assert "Agent Report" in rendered
    assert "ETH-USDT-SWAP" in rendered
    assert "Rich Markdown Should Not Render" not in rendered


def test_rich_run_collapses_internal_trace_by_default(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    monkeypatch.delenv("HYPERTRADE_TRACE", raising=False)
    output = StringIO()

    render_run(
        {
            "id": "run_folded",
            "status": "completed",
            "report_markdown": "# Report\n\nok",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {"tool_name": "graph.intent_classify", "status": "completed"},
                {"tool_name": "graph.plan_tools", "status": "completed"},
                {"tool_name": "bitpro.capabilities", "status": "completed"},
                {"tool_name": "bitpro.health", "status": "completed"},
                {"tool_name": "bitpro.strategy_search", "status": "completed"},
                {"tool_name": "bitpro_strategy_search", "status": "completed"},
                {"tool_name": "bitpro_strategy_search", "status": "completed"},
                {"tool_name": "memory_search", "status": "completed"},
                {"tool_name": "graph.final_report", "status": "completed"},
            ],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "Tool Trace Summary" in rendered
    assert "bitpro_strategy_search" in rendered
    assert "memory_search" in rendered
    assert "Trace folded: 6 internal events hidden" in rendered
    assert "graph.intent_classify" not in rendered
    assert "bitpro.capabilities" not in rendered
    assert "bitpro.strategy_search" not in rendered


def test_rich_run_can_show_full_trace(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    monkeypatch.setenv("HYPERTRADE_TRACE", "full")
    output = StringIO()

    render_run(
        {
            "id": "run_full_trace",
            "status": "completed",
            "report_markdown": "# Report\n\nok",
            "report_json": {"planner": "deepseek"},
            "trace_events": [
                {"tool_name": "graph.intent_classify", "status": "completed"},
                {"tool_name": "bitpro.capabilities", "status": "completed"},
                {"tool_name": "bitpro_strategy_search", "status": "completed"},
            ],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "Tool Trace" in rendered
    assert "Tool Trace Summary" not in rendered
    assert "graph.intent_classify" in rendered
    assert "bitpro.capabilities" in rendered
    assert "Trace folded" not in rendered


def test_render_run_uses_rich_markdown_for_unknown_report(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    output = StringIO()

    render_run(
        {
            "id": "run_markdown",
            "status": "completed",
            "report_markdown": (
                "# HyperTrade 技能清单\n\n"
                "| 技能 | 说明 |\n"
                "|---|---|\n"
                "| market_summary | 获取 OKX 行情概览 |\n"
            ),
            "report_json": {"planner": "deepseek"},
            "trace_events": [{"tool_name": "graph.final_report", "status": "completed"}],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "Agent Report" in rendered
    assert "HyperTrade 技能清单" in rendered
    assert "market_summary" in rendered
    assert "# HyperTrade" not in rendered
    assert "|---|---|" not in rendered


def test_render_run_keeps_plain_markdown_when_renderer_plain(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "plain")
    output = StringIO()

    render_run(
        {
            "id": "run_plain",
            "status": "completed",
            "report_markdown": "# Plain Report\n\n| A | B |\n|---|---|\n| 1 | 2 |",
            "trace_events": [],
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "# Plain Report" in rendered
    assert "|---|---|" in rendered


def test_workflow_results_use_rich_markdown_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_RENDERER", "rich")
    output = StringIO()

    render_strategy_research_result(
        {
            "id": "srch_cli",
            "strategy_key": "momentum_breakout_v1",
            "title": "突破研究",
            "report_markdown": "# Research\n\n| Item | Value |\n|---|---|\n| bias | up |",
        },
        output=output,
    )
    render_backtest_result(
        {
            "id": "bt_cli",
            "research_id": "srch_cli",
            "strategy_key": "momentum_breakout_v1",
            "metrics": {"total_return_pct": "1.2", "trade_count": 3},
            "report_markdown": "# Backtest\n\n- pass",
        },
        output=output,
    )

    rendered = output.getvalue()
    assert "Strategy Research" in rendered
    assert "Backtest Report" in rendered
    assert "# Research" not in rendered
    assert "|---|---|" not in rendered


def test_ask_streams_agent_run_progress(capsys) -> None:
    client = FakeAgentClient()

    exit_code = main(["ask", "请做行情归纳"], client=client)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Agent status: run created" in output
    assert "Agent status: executing tool market.summary" in output
    assert "Agent status: tool market.summary completed" in output
    assert "Agent status: generating final report" in output
    assert "# CLI Report" in output
    assert "+ Thought:" not in output


def test_run_stream_shows_thinking_animation_for_tty() -> None:
    client = FakeAgentClient()
    output = TtyStringIO()

    render_run_stream(client, "你会哪些技能？", output=output)

    rendered = output.getvalue()
    assert "+ Thought:" in rendered
    assert "Thinking" in rendered
    assert "Agent status: run created" in rendered
    assert "CLI Report" in rendered
    assert "# CLI Report" not in rendered


def test_chat_reuses_client_until_exit(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(["研究趋势突破策略", "exit"])

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.logged_in is True
    assert client.prompts == ["研究趋势突破策略"]
    output = capsys.readouterr().out
    assert "run_cli" in output
    assert "memory.write" in output


def test_chat_handles_slash_commands_without_agent_run(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(
        [
            "/help",
            "/commands",
            "/status",
            "/model",
            "/model deepseek",
            "/providers",
            "/tools",
            "/runs",
            "/memory",
            "/memory search 风控",
            "/memory disable mem_recent",
            "/rag 风控",
            "/evals",
            "/strategy",
            "/backtests",
            "/price ETH",
            "/candles ETH --bar 1H --limit 50",
            "/compare ETH SOL --bar 4H --limit 100",
            "/experiment 研究ETH突破",
            "/paper status",
            "/paper pause",
            "/paper resume",
            "/paper close ETH",
            "/paper reset",
            "/live intents",
            "/live intent ETH buy 0.01 --reason test order",
            "/live approve loi_new --reason checked",
            "/live execute loi_new",
            "/live reject loi_old --reason no",
            "exit",
        ]
    )

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.logged_in is True
    assert client.prompts == []
    output = capsys.readouterr().out
    assert "/tools" in output
    assert "List registered Agent tools with category, approval gate, and purpose." in output
    assert "Status:" in output
    assert "Model:" in output
    assert "Model switched: deepseek" in output
    assert "Providers:" in output
    assert "market.summary" in output
    assert "Summarize market." in output
    assert "live.order_intent" in output
    assert "Create order intent." in output
    assert "run_recent" in output
    assert "mem_recent" in output
    assert "mem_search" in output
    assert "Memory disable: ok" in output
    assert "RAG hits:" in output
    assert "rag-usage.md" in output
    assert "Eval suite:" in output
    assert "tool_selection passed" in output
    assert client.disabled_memory_ids == ["mem_recent"]
    assert "srch_recent" in output
    assert "bt_recent" in output
    assert "ETH-USDT-SWAP" in output
    assert "K-line trend:" in output
    assert "Relative strength:" in output
    assert "Strategy experiment completed" in output
    assert client.experiment_prompts == ["研究ETH突破"]
    assert client.price_symbols == ["ETH"]
    assert client.candle_calls == [{"symbol": "ETH", "bar": "1H", "limit": 50}]
    assert client.compare_calls == [{"symbols": ["ETH", "SOL"], "bar": "4H", "limit": 100}]
    assert client.paper_actions == ["pause", "resume", "close", "reset"]
    assert "Paper trading:" in output
    assert "paper_cli" in output
    assert "ETH-USDT-SWAP" in output
    assert "Paper control: paused" in output
    assert "Paper control: running" in output
    assert "Paper close: 1 positions" in output
    assert "Paper reset: new session paper_new" in output
    assert "Live order intents:" in output
    assert "loi_recent" in output
    assert "loi_new pending_approval testnet ETH-USDT-SWAP buy 0.01 market" in output
    assert "loi_new approved testnet ETH-USDT-SWAP buy 0.01 market" in output
    assert "loi_new execution_failed testnet ETH-USDT-SWAP buy 0.01 market" in output
    assert "risk: allowed" in output
    assert "loi_old rejected testnet ETH-USDT-SWAP buy 0.01 market" in output


def test_slash_help_describes_every_command() -> None:
    output = StringIO()

    render_slash_help(output=output)

    rendered = output.getvalue()
    lines = [line for line in rendered.splitlines() if line.startswith("- ")]
    assert lines
    assert len(lines) == len(SLASH_COMMAND_HELP)
    for command, description in SLASH_COMMAND_HELP:
        assert command in rendered
        assert description in rendered
    assert any(
        "/memory search <query>" in line and "Search audited memory" in line
        for line in lines
    )
    assert any(
        "/backtest --source bitpro_mcp" in line and "BitPro MCP K-lines" in line
        for line in lines
    )


def test_render_tools_includes_tool_descriptions() -> None:
    output = StringIO()

    render_tools(
        [
            {
                "name": "market.summary",
                "category": "market",
                "requires_approval": False,
                "description": "Summarize market.",
            },
            {
                "name": "live.order_intent",
                "category": "live",
                "requires_approval": True,
                "description": "Create order intent.",
            },
        ],
        output=output,
    )

    rendered = output.getvalue()
    assert "- market.summary [market]: Summarize market." in rendered
    assert "- live.order_intent [live] approval: Create order intent." in rendered


def test_bare_command_starts_chat_loop(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(["请做行情归纳", ":q"])

    exit_code = main([], client=client, input_fn=_next_input(inputs))

    assert exit_code == 0
    assert client.logged_in is True
    assert client.prompts == ["请做行情归纳"]
    output = capsys.readouterr().out
    assert "HyperTrade CLI chat" in output
    assert "run_cli" in output


def test_remote_flag_uses_api_client(monkeypatch) -> None:
    monkeypatch.setenv("HYPERTRADE_USERNAME", "operator")
    monkeypatch.setenv("HYPERTRADE_PASSWORD", "secret")
    captured: list[tuple[CliConfig, bool]] = []

    exit_code = main(
        ["--remote", "http://remote.test:3333", "ask", "hello"],
        client_factory=lambda config, local: _capture_client(config, local, captured),
    )

    assert exit_code == 0
    assert captured == [
        (
            CliConfig(
                api_url="http://remote.test:3333",
                username="operator",
                password="secret",
            ),
            False,
        )
    ]


def test_local_agent_client_runs_kernel(tmp_path) -> None:
    from hypertrade.config import Settings
    from hypertrade.db import Database

    db = Database("sqlite:///:memory:")
    db.create_all()
    client = LocalAgentClient(
        settings=Settings(
            DATABASE_URL="sqlite:///:memory:",
            KNOWLEDGE_DIR=tmp_path,
            DEEPSEEK_API_KEY="",
        ),
        db=db,
    )

    client.login()
    run = client.run_agent("请做行情归纳")

    assert run["status"] == "completed"
    trace_names = [event["tool_name"] for event in run["trace_events"]]
    assert trace_names[0] == "graph.intent_classify"
    assert "market.summary" in trace_names
    assert run["run_state_json"]["current_node"] == "final_report"


def test_api_client_logs_in_and_posts_agent_run() -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {}
        if request.content:
            payload = dict(httpx.Response(200, content=request.content).json())
        seen.append((request.method, request.url.path, payload))
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(
            200,
            json={
                "id": "run_api",
                "status": "completed",
                "report_markdown": "ok",
                "trace_events": [],
            },
        )

    transport = httpx.MockTransport(handler)
    client = AgentApiClient(
        CliConfig(
            api_url="http://example.test/",
            username="admin",
            password="secret",
            timeout_seconds=3.0,
        ),
        http_client=httpx.Client(transport=transport),
    )

    client.login()
    run = client.run_agent("hello")

    assert run["id"] == "run_api"
    assert seen == [
        ("POST", "/api/auth/login", {"username": "admin", "password": "secret"}),
        ("POST", "/api/agent/runs", {"prompt": "hello"}),
    ]


def test_chat_runs_research_and_backtest_shortcuts(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(
        [
            "/research 研究BTC趋势突破",
            "/backtest latest",
            "exit",
        ]
    )

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.research_prompts == ["研究BTC趋势突破"]
    assert client.backtest_calls == [
        {
            "research_id": "srch_recent",
            "strategy_key": "momentum_breakout_v1",
            "use_live_candles": False,
            "symbol": "BTC",
            "bar": "1H",
            "candle_limit": 100,
            "candle_source": "sample",
        }
    ]
    output = capsys.readouterr().out
    assert "srch_cli" in output
    assert "Strategy research created" in output
    assert "bt_cli" in output
    assert "Backtest completed" in output
    assert "Return 1.9%" in output


def test_chat_runs_live_candle_backtest_shortcut(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(["/backtest --live --symbol ETH --bar 1H --limit 24", "exit"])

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.backtest_calls == [
        {
            "research_id": "srch_recent",
            "strategy_key": "momentum_breakout_v1",
            "use_live_candles": True,
            "symbol": "ETH",
            "bar": "1H",
            "candle_limit": 24,
            "candle_source": "okx",
        }
    ]
    assert "Backtest completed" in capsys.readouterr().out


def test_chat_runs_bitpro_archive_backtest_shortcut(capsys) -> None:
    client = FakeAgentClient()
    inputs = iter(["/backtest --source bitpro --symbol ETH --bar 1H --limit 24", "exit"])

    run_chat(client=client, input_fn=_next_input(inputs))

    assert client.backtest_calls == [
        {
            "research_id": "srch_recent",
            "strategy_key": "momentum_breakout_v1",
            "use_live_candles": False,
            "symbol": "ETH",
            "bar": "1H",
            "candle_limit": 24,
            "candle_source": "bitpro",
        }
    ]
    assert "Backtest completed" in capsys.readouterr().out


def test_api_client_creates_research_and_backtest() -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {}
        if request.content:
            payload = dict(httpx.Response(200, content=request.content).json())
        seen.append((request.method, request.url.path, payload))
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/api/strategy/research":
            return httpx.Response(
                200,
                json={
                    "id": "srch_api_new",
                    "strategy_key": "momentum_breakout_v1",
                    "title": "趋势突破",
                    "report_markdown": "# Research",
                },
            )
        if request.url.path == "/api/backtests":
            return httpx.Response(
                200,
                json={
                    "id": "bt_api_new",
                    "research_id": payload.get("research_id", ""),
                    "strategy_key": payload.get("strategy_key", ""),
                    "status": "completed",
                    "metrics": {"total_return_pct": "0.019000", "trade_count": 1},
                    "report_markdown": "# Backtest",
                },
            )
        raise AssertionError(request.url.path)

    client = AgentApiClient(
        CliConfig(api_url="http://example.test/", username="admin", password="secret"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    research = client.create_strategy_research("研究ETH动量")
    backtest = client.run_backtest(research_id="srch_api_new")

    assert research["id"] == "srch_api_new"
    assert backtest["id"] == "bt_api_new"
    assert ("POST", "/api/strategy/research", {"prompt": "研究ETH动量"}) in seen
    backtest_call = next(item for item in seen if item[1] == "/api/backtests")
    assert backtest_call[2]["research_id"] == "srch_api_new"


def test_local_client_runs_strategy_workflow(tmp_path) -> None:
    from hypertrade.config import Settings
    from hypertrade.db import Database

    db = Database("sqlite:///:memory:")
    db.create_all()
    client = LocalAgentClient(
        settings=Settings(DATABASE_URL="sqlite:///:memory:", KNOWLEDGE_DIR=tmp_path),
        db=db,
    )

    research = client.create_strategy_research("研究SOL突破")
    backtest = client.run_backtest(research_id=str(research["id"]))

    assert research["id"].startswith("srch_")
    assert backtest["id"].startswith("bt_")
    assert backtest["research_id"] == research["id"]
    assert backtest["metrics"]["trade_count"] == 1


def test_api_client_lists_slash_command_resources() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        payloads: dict[str, dict[str, Any]] = {
            "/api/harness/tools": {"tools": [{"name": "market.summary"}]},
            "/api/agent/runs": {"runs": [{"id": "run_api"}]},
            "/api/memory": {"items": [{"id": "mem_api"}]},
            "/api/strategy/research": {"items": [{"id": "srch_api"}]},
            "/api/backtests": {"items": [{"id": "bt_api"}]},
            "/api/harness/overview": {
                "agent_runs": {"total_count": 2},
                "memory": {"active_count": 1},
                "tools": [{"name": "market.summary"}],
                "market": {"ticker_count": 344, "latest_update_age_seconds": 3},
                "providers": [
                    {
                        "name": "deepseek",
                        "display_name": "DeepSeek",
                        "model": "deepseek-v4-flash",
                        "enabled": True,
                        "default": True,
                        "key_status": "configured",
                    }
                ],
            },
        }
        return httpx.Response(200, json=payloads[request.url.path])

    client = AgentApiClient(
        CliConfig(api_url="http://example.test/", username="admin", password="secret"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert client.list_tools()[0]["name"] == "market.summary"
    assert client.list_runs()[0]["id"] == "run_api"
    assert client.list_memory()[0]["id"] == "mem_api"
    assert client.list_strategy_research()[0]["id"] == "srch_api"
    assert client.list_backtests()[0]["id"] == "bt_api"
    assert client.get_status()["agent_runs"] == 2
    assert client.get_model_status()["model"] == "deepseek-v4-flash"
    assert seen == [
        ("GET", "/api/harness/tools"),
        ("GET", "/api/agent/runs"),
        ("GET", "/api/memory"),
        ("GET", "/api/strategy/research"),
        ("GET", "/api/backtests"),
        ("GET", "/api/harness/overview"),
        ("GET", "/api/harness/overview"),
    ]


def _next_input(values: Iterator[str]):
    def inner(_: str) -> str:
        return next(values)

    return inner


def _capture_client(
    config: CliConfig,
    local: bool,
    captured: list[tuple[CliConfig, bool]],
) -> FakeAgentClient:
    captured.append((config, local))
    return FakeAgentClient()
