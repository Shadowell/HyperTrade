from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from hypertrade.agent.kernel import AgentKernel, _citations_from_tool_calls
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.market.repository import MarketRepository
from hypertrade.providers.deepseek import ChatResponse, ToolCallRequest
from hypertrade.rag.service import RagService


class ReplayChatProvider:
    name = "replay"
    model = "planner-test"

    def __init__(self, responses: list[ChatResponse]) -> None:
        self._responses = responses
        self.messages: list[list[dict[str, Any]]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        self.messages.append(messages)
        if not self._responses:
            raise AssertionError("No replay response left")
        return self._responses.pop(0)


def _patch_replay_provider(
    monkeypatch,
    responses: list[ChatResponse],
) -> ReplayChatProvider:
    provider = ReplayChatProvider(responses)
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda self, selected=None, selected_model=None: provider,
    )
    return provider


def test_agent_chat_market_summary_creates_report_trace_and_memory(monkeypatch, tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    repo = MarketRepository(db)
    repo.upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("70000"),
        volume_ccy_24h=Decimal("20000"),
        change_utc0_pct=Decimal("4.2"),
    )
    repo.upsert_ticker_snapshot(
        inst_id="ETH-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("3600"),
        volume_ccy_24h=Decimal("14000"),
        change_utc0_pct=Decimal("-2.5"),
    )
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "notes.md").write_text(
        "Focus on volume expansion and risk control.",
        encoding="utf-8",
    )
    RagService(db, knowledge_dir=knowledge_dir).scan_once()

    replay = _patch_replay_provider(
        monkeypatch,
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_market",
                        name="market_summary",
                        arguments={},
                    ),
                    ToolCallRequest(
                        id="call_rag",
                        name="rag_search",
                        arguments={"query": "market risk", "limit": 3},
                    ),
                    ToolCallRequest(
                        id="call_memory",
                        name="memory_write",
                        arguments={
                            "kind": "market_summary",
                            "content": "Latest market summary requested by user prompt.",
                        },
                    ),
                ],
            ),
            ChatResponse(content="已完成 OKX 永续合约行情归纳。", tool_calls=[]),
        ],
    )
    kernel = AgentKernel(
        db,
        settings=Settings(
            DEEPSEEK_API_KEY="test-key",
            KNOWLEDGE_DIR=tmp_path,
            OKX_REST_URL="http://127.0.0.1:9",
        ),
    )
    run = kernel.run_chat("请归纳一下当前 OKX 永续合约行情")

    assert run.status == "completed"
    assert (
        "BTC-USDT-SWAP" in run.report_markdown or "当前无法获取实时 OKX 行情" in run.report_markdown
    )
    if "当前无法获取实时 OKX 行情" in run.report_markdown:
        assert run.report_json["data_source"] == "unavailable"
    assert run.report_json["market_scope"] == "OKX SWAP"
    tool_names = [
        event.tool_name for event in run.trace_events if not event.tool_name.startswith("graph.")
    ]
    graph_names = [
        event.tool_name for event in run.trace_events if event.tool_name.startswith("graph.")
    ]
    assert "graph.intent_classify" in graph_names
    assert "graph.final_report" in graph_names
    assert run.report_json["graph"][-1]["node"] == "final_report"
    assert tool_names == [
        "market_summary",
        "rag_search",
        "memory_write",
    ]
    assert replay.messages
    assert run.report_json["planner"] == "replay"


def test_agent_without_provider_does_not_guess_business_tool_route(tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    kernel = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="", KNOWLEDGE_DIR=tmp_path),
    )

    run = kernel.run_chat("帮我判断一下现在应该看哪个交易方向")

    assert run.status == "completed"
    assert "未配置可用 Chat Provider" in run.report_markdown
    assert "市场热度总结" not in run.report_markdown
    assert run.report_json["status"] == "provider_unavailable"
    tool_names = [
        event.tool_name for event in run.trace_events if not event.tool_name.startswith("graph.")
    ]
    assert tool_names == []


def test_market_candle_citation_is_source_bound_and_omits_raw_payload() -> None:
    citations = _citations_from_tool_calls(
        [
            SimpleNamespace(
                tool_name="market_candles",
                output_json={
                    "data_source": "okx_rest",
                    "inst_id": "BTC-USDT-SWAP",
                    "candles": ["must-not-leak"],
                },
            )
        ]
    )

    assert citations == [
        {
            "source_path": "okx_rest/market_candles",
            "title": "OKX public market candles",
            "chunk_index": 0,
            "score": 1,
            "content_preview": "",
        }
    ]
    assert "must-not-leak" not in str(citations)


def test_agent_routes_live_order_history_prompt_through_planner(monkeypatch, tmp_path):
    class FakeBitProAdapter:
        def live_order_history(self, *, exchange="okx", symbol=None, limit=50):
            return {
                "status": "ok",
                "contract_version": "bitpro-mcp-v1",
                "exchange": exchange,
                "symbol": symbol,
                "limit": limit,
                "orders": [
                    {
                        "id": "ord_latest",
                        "order_id": "ord_latest",
                        "symbol": "ETH/USDT:USDT",
                        "side": "buy",
                        "status": "closed",
                        "type": "market",
                        "average": "3500",
                        "amount": "0.2",
                        "filled": "0.2",
                        "timestamp": "2026-06-24T05:20:00Z",
                        "bitpro_source_label": "手动/外部订单",
                    }
                ],
                "order_summary": {"count": 1, "latest_order_id": "ord_latest"},
                "tool_calls": [
                    {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                    {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                    {
                        "tool": "trading_order_history",
                        "parameters": {"exchange": exchange, "limit": limit},
                        "status": "success",
                    },
                ],
            }

    db = Database("sqlite:///:memory:")
    db.create_all()
    replay = _patch_replay_provider(
        monkeypatch,
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_live_orders",
                        name="bitpro_live_order_history",
                        arguments={"exchange": "okx", "limit": 1},
                    )
                ],
            ),
            ChatResponse(content="已读取最近一笔实盘订单。", tool_calls=[]),
        ],
    )
    kernel = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="test-key", KNOWLEDGE_DIR=tmp_path),
        bitpro_adapter=FakeBitProAdapter(),
    )

    run = kernel.run_chat("我的实盘最近的一笔订单是什么")

    assert run.status == "completed"
    assert "## BitPro 实盘订单" in run.report_markdown
    assert "ord_latest ETH/USDT:USDT buy closed" in run.report_markdown
    assert "市场热度总结" not in run.report_markdown
    tool_names = [
        event.tool_name for event in run.trace_events if not event.tool_name.startswith("graph.")
    ]
    assert "bitpro.live_order_history" in tool_names
    assert "market.summary" not in tool_names
    assert replay.messages
    assert run.report_json["planner"] == "replay"


def test_agent_routes_live_strategy_performance_prompt_through_planner(monkeypatch, tmp_path):
    class FakeBitProAdapter:
        def live_strategy_performance(self, *, exchange="okx", limit=20):
            return {
                "status": "ok",
                "contract_version": "bitpro-mcp-v1",
                "exchange": exchange,
                "limit": limit,
                "rank_basis": "return_pct",
                "strategies": [
                    {
                        "strategy_id": 105,
                        "strategy_name": "Alpha Live",
                        "status": "running",
                        "workspace_status": "deployed",
                        "exchange": "okx",
                        "account_id": "main",
                        "symbols": ["ETH/USDT:USDT"],
                        "total_pnl": "123.45",
                        "return_pct": "4.56",
                    }
                ],
                "performance_summary": {
                    "count": 1,
                    "top_strategy_id": 105,
                    "top_return_pct": "4.56",
                    "top_total_pnl": "123.45",
                },
                "tool_calls": [
                    {"tool": "bitpro_capabilities", "parameters": {}, "status": "success"},
                    {"tool": "bitpro_health", "parameters": {}, "status": "success"},
                    {"tool": "live_strategies", "parameters": {}, "status": "success"},
                ],
            }

    db = Database("sqlite:///:memory:")
    db.create_all()
    replay = _patch_replay_provider(
        monkeypatch,
        [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_live_strategies",
                        name="bitpro_live_strategy_performance",
                        arguments={"exchange": "okx", "limit": 20},
                    )
                ],
            ),
            ChatResponse(content="已读取实盘策略收益排行。", tool_calls=[]),
        ],
    )
    kernel = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="test-key", KNOWLEDGE_DIR=tmp_path),
        bitpro_adapter=FakeBitProAdapter(),
    )

    run = kernel.run_chat("看下实盘收益最高的策略")

    assert run.status == "completed"
    assert "## BitPro 实盘策略收益" in run.report_markdown
    assert "Alpha Live" in run.report_markdown
    assert "收益率=4.56%" in run.report_markdown
    assert "市场热度总结" not in run.report_markdown
    tool_names = [
        event.tool_name for event in run.trace_events if not event.tool_name.startswith("graph.")
    ]
    assert "bitpro.live_strategy_performance" in tool_names
    assert "market.summary" not in tool_names
    assert replay.messages
    assert run.report_json["planner"] == "replay"
