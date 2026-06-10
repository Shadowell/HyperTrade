from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from hypertrade.agent.kernel import AgentKernel
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.service import MemoryService
from hypertrade.providers.deepseek import ChatResponse, ToolCallRequest
from hypertrade.rag.service import RagService

FORBIDDEN_ADVICE_PHRASES = [
    "保证收益",
    "稳赚",
    "建议买入",
    "建议卖出",
    "满仓",
    "all in",
]


class ReplayDeepSeekClient:
    name = "deepseek"
    model = "replay-model"

    def __init__(self, responses: Iterable[ChatResponse]) -> None:
        self._responses = list(responses)
        self.messages: list[list[dict[str, Any]]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        self.messages.append(messages)
        if not self._responses:
            raise AssertionError("No replay LLM response left")
        return self._responses.pop(0)


class ReplayBitProAdapter:
    def capabilities(self) -> dict[str, Any]:
        return {
            "contract_version": "bitpro-mcp-v1",
            "tool_groups": {
                "research_backtest_paper_mutation": [
                    "strategy_generate",
                    "strategy_create",
                    "strategy_update",
                    "backtest_start_job",
                    "paper_configure",
                    "paper_start",
                ],
            },
        }

    def market_klines(self, *, symbol: str, timeframe: str, limit: int) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "health": {"status": "healthy"},
            "market": {
                "exchange": "okx",
                "symbol": "ETH/USDT:USDT",
                "timeframe": "1h",
                "limit": limit,
            },
            "candles": [
                {
                    "timestamp": 1_780_272_000_000 + index * 3_600_000,
                    "open": 100 + index,
                    "high": 101 + index,
                    "low": 99 + index,
                    "close": 100 + index,
                    "volume": 1000 + index,
                }
                for index in range(limit)
            ],
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {
                    "tool": "market_klines",
                    "status": "success",
                    "parameters": {
                        "exchange": "okx",
                        "symbol": "ETH/USDT:USDT",
                        "timeframe": "1h",
                        "limit": limit,
                    },
                },
            ],
        }

    def strategy_generate(self, *, prompt: str, symbol: str, timeframe: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "strategy": {
                "name": "ETH trend breakout",
                "script_content": "class ETHTrendBreakout: pass",
                "prompt": prompt,
                "symbol": symbol,
                "timeframe": timeframe,
            },
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {
                    "tool": "strategy_generate",
                    "status": "success",
                    "parameters": {"prompt": prompt, "symbol": symbol, "timeframe": timeframe},
                },
            ],
        }

    def strategy_create(
        self,
        *,
        name: str,
        script_content: str,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        exchange: str = "okx",
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "strategy": {
                "id": 42,
                "name": name,
                "script_content": script_content,
                "description": description,
                "config": config or {},
                "exchange": exchange,
                "symbols": symbols or [],
            },
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {
                    "tool": "strategy_create",
                    "status": "success",
                    "parameters": {"name": name, "exchange": exchange, "symbols": symbols or []},
                },
            ],
        }

    def strategy_update(
        self,
        *,
        strategy_id: int,
        name: str | None = None,
        script_content: str | None = None,
        description: str | None = None,
        config: dict[str, Any] | None = None,
        exchange: str | None = None,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "strategy": {
                "id": strategy_id,
                "name": name,
                "script_content": script_content,
                "description": description,
                "config": config or {},
                "exchange": exchange,
                "symbols": symbols or [],
            },
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {
                    "tool": "strategy_update",
                    "status": "success",
                    "parameters": {"strategy_id": strategy_id, "name": name},
                },
            ],
        }

    def backtest_start_job(
        self,
        *,
        strategy_id: int,
        start_date: str,
        end_date: str,
        initial_capital: float,
        exchange: str = "okx",
        symbol: str | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "job": {
                "job_id": "job_42",
                "strategy_id": strategy_id,
                "start_date": start_date,
                "end_date": end_date,
                "symbol": symbol,
                "timeframe": timeframe,
            },
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {
                    "tool": "backtest_start_job",
                    "status": "success",
                    "parameters": {
                        "strategy_id": strategy_id,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                },
            ],
        }

    def backtest_get_job(self, *, job_id: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "job": {"job_id": job_id, "status": "completed", "progress": 100},
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {"tool": "backtest_get_job", "status": "success", "parameters": {"job_id": job_id}},
            ],
        }

    def backtest_list_results(
        self,
        *,
        min_total_return_pct: float | None = None,
        status: str = "completed",
        sort_by: str = "return",
        sort_order: str = "desc",
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "health": {"status": "healthy"},
            "filter": {
                "metric": "total_return_pct",
                "min_total_return_pct": min_total_return_pct,
                "status": status,
                "sort_by": sort_by,
                "sort_order": sort_order,
                "limit": limit,
            },
            "result_count": 2,
            "raw_result_count": 21,
            "results": [
                {
                    "id": 161,
                    "strategy_id": 178,
                    "strategy_name": (
                        "[合约][1D][CTA] ETH · Donchian89/EMA89趋势跟踪稳健版 · 100U"
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
                        "[合约][1H][CTA] ETH · Heikin Ashi趋势跟踪低频版 · 100U"
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
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {
                    "tool": "backtest_list_results",
                    "status": "success",
                    "parameters": {
                        "offset": 0,
                        "limit": min(limit, 20),
                        "status": status,
                        "sort_by": sort_by,
                        "sort_order": sort_order,
                    },
                },
            ],
        }

    def paper_configure(
        self,
        *,
        strategy_id: int,
        initial_equity: float,
        exchange: str = "okx",
        loop_interval_sec: int = 60,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "paper": {"instance_id": 7, "strategy_id": strategy_id, "status": "configured"},
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {
                    "tool": "paper_configure",
                    "status": "success",
                    "parameters": {"strategy_id": strategy_id, "initial_equity": initial_equity},
                },
            ],
        }

    def paper_start(self, *, strategy_id: int) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "paper": {"instance_id": strategy_id, "status": "running"},
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {
                    "tool": "paper_start",
                    "status": "success",
                    "parameters": {"strategy_id": strategy_id},
                },
            ],
        }


def test_agent_acceptance_specific_symbol_report_uses_exact_ticker_tool(
    monkeypatch,
    tmp_path,
) -> None:
    db = _memory_db()
    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="DOGE-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("0.200000000000"),
        volume_ccy_24h=Decimal("1200000.000000000000"),
        change_utc0_pct=Decimal("1.500000"),
    )
    replay = _patch_replay_llm(
        monkeypatch,
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_ticker",
                        name="market_ticker",
                        arguments={"symbol": "DOGE"},
                    )
                ],
            ),
            ChatResponse(
                content=(
                    "DOGE 已查询，重点观察价格、涨跌幅和成交额。"
                ),
                tool_calls=[],
            ),
        ],
    )
    kernel = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="test-key", KNOWLEDGE_DIR=tmp_path),
        knowledge_dir=str(tmp_path),
    )
    monkeypatch.setattr(kernel, "_refresh_market_snapshot", lambda: ("unavailable", "offline"))

    run = kernel.run_chat("看下DOGE行情")

    assert run.status == "completed"
    assert _tool_names(run) == ["market_ticker"]
    ticker_event = _business_events(run)[0]
    assert ticker_event.input_json == {"symbol": "DOGE"}
    assert ticker_event.output_json["inst_id"] == "DOGE-USDT-SWAP"
    assert "## 单标的行情" in run.report_markdown
    assert "DOGE-USDT-SWAP" in run.report_markdown
    assert "最新价 0.200000000000" in run.report_markdown
    _assert_research_quality(run.report_markdown)
    assert replay.messages[0][0]["role"] == "system"
    assert "Always end with" not in replay.messages[0][0]["content"]
    assert "Not investment advice" not in replay.messages[0][0]["content"]


def test_agent_acceptance_trend_and_relative_strength_reports_are_structured(
    monkeypatch,
    tmp_path,
) -> None:
    db = _memory_db()
    _patch_replay_llm(
        monkeypatch,
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_candles",
                        name="market_candles",
                        arguments={"symbol": "ETH", "bar": "1H", "limit": 100},
                    ),
                    ToolCallRequest(
                        id="call_compare",
                        name="market_compare",
                        arguments={"symbols": ["ETH", "SOL"], "bar": "4H", "limit": 100},
                    ),
                ],
            ),
            ChatResponse(
                content=(
                    "ETH 短线偏强，和 SOL 对比时需要继续观察成交量确认。"
                ),
                tool_calls=[],
            ),
        ],
    )
    kernel = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="test-key", KNOWLEDGE_DIR=tmp_path),
        knowledge_dir=str(tmp_path),
    )
    monkeypatch.setattr(
        kernel,
        "_market_candles_payload",
        lambda *, symbol, bar, limit: _candle_summary(symbol=symbol, bar=bar),
    )

    run = kernel.run_chat("看下ETH走势，并和SOL比较哪个更强")

    assert _tool_names(run) == ["market_candles", "market_compare"]
    assert "## K线趋势特征" in run.report_markdown
    assert "ETH-USDT-SWAP" in run.report_markdown
    assert "## 多标的强弱比较" in run.report_markdown
    assert "领先标的: ETH-USDT-SWAP" in run.report_markdown
    assert "1. ETH-USDT-SWAP" in run.report_markdown
    assert "2. SOL-USDT-SWAP" in run.report_markdown
    _assert_research_quality(run.report_markdown)


def test_agent_acceptance_rag_memory_run_is_auditable(monkeypatch, tmp_path) -> None:
    db = _memory_db()
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "risk.md").write_text(
        "Funding-rate spikes and low liquidity require tighter risk controls.",
        encoding="utf-8",
    )
    RagService(db, knowledge_dir=knowledge_dir).scan_once()
    MemoryService(db).write(
        content="User cares about risk control before signal strength.",
        kind="preference",
        source_run_id="manual",
        source_tool="test",
    )
    _patch_replay_llm(
        monkeypatch,
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_rag",
                        name="rag_search",
                        arguments={"query": "funding liquidity risk", "limit": 3},
                    ),
                    ToolCallRequest(id="call_memory_search", name="memory_search", arguments={}),
                    ToolCallRequest(
                        id="call_memory_write",
                        name="memory_write",
                        arguments={
                            "kind": "agent_note",
                            "content": "Reviewed funding liquidity risk context.",
                        },
                    ),
                ],
            ),
            ChatResponse(
                content=(
                    "已结合知识库和历史记忆输出风险上下文。"
                ),
                tool_calls=[],
            ),
        ],
    )

    run = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="test-key", KNOWLEDGE_DIR=knowledge_dir),
        knowledge_dir=str(knowledge_dir),
    ).run_chat("结合知识库和记忆，说下资金费率风险")

    assert _tool_names(run) == ["rag_search", "memory_search", "memory_write"]
    events = _business_events(run)
    assert events[0].output_json["hits"][0]["source_path"].endswith("risk.md")
    assert events[2].output_json["memory_id"].startswith("mem_")
    assert run.report_json["planner"] == "deepseek"
    assert run.report_json["tool_calls"] == [
        {"tool": "rag_search", "input": {"query": "funding liquidity risk", "limit": 3}},
        {"tool": "memory_search", "input": {}},
        {
            "tool": "memory_write",
            "input": {
                "kind": "agent_note",
                "content": "Reviewed funding liquidity risk context.",
            },
        },
    ]
    _assert_research_quality(run.report_markdown)


def test_agent_acceptance_strategy_research_and_backtest_chain(
    monkeypatch,
    tmp_path,
) -> None:
    db = _memory_db()
    _patch_replay_llm(
        monkeypatch,
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_strategy",
                        name="strategy_draft",
                        arguments={"prompt": "研究ETH趋势突破"},
                    )
                ],
            ),
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_backtest",
                        name="backtest_run",
                        arguments={
                            "research_id": "",
                            "strategy_key": "momentum_breakout_v1",
                        },
                    )
                ],
            ),
            ChatResponse(
                content=(
                    "策略研究和样例回测已完成，结果只用于流程验收。"
                ),
                tool_calls=[],
            ),
        ],
    )

    run = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="test-key", KNOWLEDGE_DIR=tmp_path),
        knowledge_dir=str(tmp_path),
    ).run_chat("研究ETH趋势突破并回测")

    assert _tool_names(run) == ["strategy_draft", "backtest_run"]
    events = _business_events(run)
    assert events[0].output_json["id"].startswith("srch_")
    assert events[0].output_json["strategy_key"] == "momentum_breakout_v1"
    assert events[1].output_json["id"].startswith("bt_")
    assert events[1].output_json["status"] == "completed"
    assert events[1].output_json["metrics"]["trade_count"] >= 0
    _assert_research_quality(run.report_markdown)


def test_agent_acceptance_bitpro_mcp_market_klines_are_audited(
    monkeypatch,
    tmp_path,
) -> None:
    db = _memory_db()
    _patch_replay_llm(
        monkeypatch,
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_bitpro_klines",
                        name="bitpro_market_klines",
                        arguments={"symbol": "ETH", "timeframe": "1H", "limit": 12},
                    )
                ],
            ),
            ChatResponse(content="BitPro K线已读取。", tool_calls=[]),
        ],
    )

    run = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="test-key", KNOWLEDGE_DIR=tmp_path),
        knowledge_dir=str(tmp_path),
        bitpro_adapter=ReplayBitProAdapter(),
    ).run_chat("用 BitPro MCP 读取 ETH 1H K线")

    names = _tool_names(run)
    assert "bitpro.capabilities" in names
    assert "bitpro.health" in names
    assert "bitpro.market_klines" in names
    assert "bitpro_market_klines" in names
    bitpro_event = next(
        event for event in _business_events(run) if event.tool_name == "bitpro_market_klines"
    )
    assert bitpro_event.output_json["market"]["symbol"] == "ETH/USDT:USDT"
    assert bitpro_event.output_json["market"]["timeframe"] == "1h"
    assert [call["tool"] for call in bitpro_event.output_json["tool_calls"]] == [
        "bitpro_capabilities",
        "bitpro_health",
        "market_klines",
    ]
    assert "## BitPro MCP K线直连" in run.report_markdown
    assert "ETH/USDT:USDT" in run.report_markdown
    assert "market_klines" in run.report_markdown
    _assert_research_quality(run.report_markdown)


def test_agent_acceptance_bitpro_backtest_return_query_uses_result_list_tool(
    monkeypatch,
    tmp_path,
) -> None:
    db = _memory_db()
    _patch_replay_llm(
        monkeypatch,
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_backtest_results",
                        name="bitpro_backtest_list_results",
                        arguments={
                            "min_total_return_pct": 100,
                            "status": "completed",
                            "sort_by": "return",
                            "sort_order": "desc",
                            "limit": 40,
                        },
                    )
                ],
            ),
            ChatResponse(content="已按 BitPro 回测总收益读取结果。", tool_calls=[]),
        ],
    )

    run = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="test-key", KNOWLEDGE_DIR=tmp_path),
        knowledge_dir=str(tmp_path),
        bitpro_adapter=ReplayBitProAdapter(),
    ).run_chat("让 agent 查看回测收益大于100%的策略有哪些")

    names = _tool_names(run)
    assert "bitpro.capabilities" in names
    assert "bitpro.health" in names
    assert "bitpro.backtest_list_results" in names
    assert "bitpro_backtest_list_results" in names
    bitpro_event = next(
        event
        for event in _business_events(run)
        if event.tool_name == "bitpro_backtest_list_results"
    )
    assert bitpro_event.input_json["min_total_return_pct"] == 100
    assert bitpro_event.output_json["filter"]["metric"] == "total_return_pct"
    assert [row["id"] for row in bitpro_event.output_json["results"]] == [161, 193]
    assert "## BitPro 回测结果" in run.report_markdown
    assert "口径: total_return_pct" in run.report_markdown
    assert "命中数量: 2" in run.report_markdown
    assert "result #161, strategy #178" in run.report_markdown
    assert "收益 305.53878586955756%" in run.report_markdown
    assert "result #193, strategy #162" in run.report_markdown
    _assert_research_quality(run.report_markdown)


def test_agent_acceptance_bitpro_strategy_lifecycle_is_audited(
    monkeypatch,
    tmp_path,
) -> None:
    db = _memory_db()
    _patch_replay_llm(
        monkeypatch,
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_generate",
                        name="bitpro_strategy_generate",
                        arguments={
                            "prompt": "ETH 趋势突破策略",
                            "symbol": "ETH",
                            "timeframe": "1H",
                        },
                    )
                ],
            ),
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_create",
                        name="bitpro_strategy_create",
                        arguments={
                            "name": "ETH trend breakout",
                            "script_content": "class ETHTrendBreakout: pass",
                            "description": "Agent generated research draft",
                            "symbols": ["ETH"],
                        },
                    )
                ],
            ),
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_backtest_start",
                        name="bitpro_backtest_start_job",
                        arguments={
                            "strategy_id": 42,
                            "start_date": "2026-06-01",
                            "end_date": "2026-06-08",
                            "initial_capital": 10000,
                            "symbol": "ETH",
                            "timeframe": "1H",
                        },
                    )
                ],
            ),
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_update",
                        name="bitpro_strategy_update",
                        arguments={
                            "strategy_id": 42,
                            "name": "[合约][1H][CTA] ETH · EMA ATR趋势回撤 · 10000U",
                            "description": "Canonical BitPro strategy name",
                            "symbols": ["ETH/USDT:USDT"],
                        },
                    )
                ],
            ),
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_backtest_get",
                        name="bitpro_backtest_get_job",
                        arguments={"job_id": "job_42"},
                    )
                ],
            ),
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_paper_configure",
                        name="bitpro_paper_configure",
                        arguments={"strategy_id": 42, "initial_equity": 10000},
                    )
                ],
            ),
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_paper_start",
                        name="bitpro_paper_start",
                        arguments={"strategy_id": 7},
                    )
                ],
            ),
            ChatResponse(content="BitPro 策略研发、回测和模拟盘验证链路已完成。", tool_calls=[]),
        ],
    )

    run = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="test-key", KNOWLEDGE_DIR=tmp_path),
        knowledge_dir=str(tmp_path),
        bitpro_adapter=ReplayBitProAdapter(),
    ).run_chat("用 BitPro skills 开发 ETH 策略，回测并启动模拟盘验证")

    names = _tool_names(run)
    assert [name for name in names if name.startswith("bitpro_")] == [
        "bitpro_strategy_generate",
        "bitpro_strategy_create",
        "bitpro_backtest_start_job",
        "bitpro_strategy_update",
        "bitpro_backtest_get_job",
        "bitpro_paper_configure",
        "bitpro_paper_start",
    ]
    assert "bitpro.strategy_generate" in names
    assert "bitpro.strategy_create" in names
    assert "bitpro.backtest_start_job" in names
    assert "bitpro.strategy_update" in names
    assert "bitpro.backtest_get_job" in names
    assert "bitpro.paper_configure" in names
    assert "bitpro.paper_start" in names
    create_event = next(
        event for event in _business_events(run) if event.tool_name == "bitpro_strategy_create"
    )
    assert create_event.output_json["strategy"]["id"] == 42
    assert "## BitPro 策略生命周期" in run.report_markdown
    assert "strategy_generate" in run.report_markdown
    assert "paper_start" in run.report_markdown
    _assert_research_quality(run.report_markdown)


def _memory_db() -> Database:
    db = Database("sqlite:///:memory:")
    db.create_all()
    return db


def _patch_replay_llm(
    monkeypatch,
    responses: Iterable[ChatResponse],
) -> ReplayDeepSeekClient:
    replay = ReplayDeepSeekClient(responses)
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda self, selected=None: replay,
    )
    return replay


def _tool_names(run: Any) -> list[str]:
    return [event.tool_name for event in _business_events(run)]


def _business_events(run: Any) -> list[Any]:
    return [event for event in run.trace_events if not event.tool_name.startswith("graph.")]


def _assert_research_quality(markdown: str) -> None:
    assert markdown.strip()
    assert "Research output only. Not investment advice." not in markdown
    assert "风险提示：本工具输出仅用于研究辅助，不构成投资建议。" not in markdown
    lowered = markdown.lower()
    for phrase in FORBIDDEN_ADVICE_PHRASES:
        assert phrase.lower() not in lowered


def _candle_summary(*, symbol: str, bar: str) -> dict[str, Any]:
    upper = symbol.upper()
    if upper == "SOL":
        return {
            "market_scope": "OKX SWAP",
            "symbol": symbol,
            "inst_id": "SOL-USDT-SWAP",
            "bar": bar,
            "found": True,
            "candle_count": 100,
            "return_pct": "-1.200000",
            "range_pct": "6.000000",
            "close_position_pct": "35.000000",
            "trend_bias": "down",
            "ma20": "80.000000000000",
            "ma60": "83.000000000000",
            "data_source": "okx_rest",
            "as_of_utc": "2026-06-02T08:00:00+00:00",
        }
    return {
        "market_scope": "OKX SWAP",
        "symbol": symbol,
        "inst_id": "ETH-USDT-SWAP",
        "bar": bar,
        "found": True,
        "candle_count": 100,
        "return_pct": "2.400000",
        "range_pct": "7.500000",
        "close_position_pct": "72.000000",
        "trend_bias": "up",
        "ma20": "2000.000000000000",
        "ma60": "1975.000000000000",
        "data_source": "okx_rest",
        "as_of_utc": "2026-06-02T08:00:00+00:00",
    }
