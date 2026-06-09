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
