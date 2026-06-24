from decimal import Decimal

from hypertrade.agent.kernel import AgentKernel
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.market.repository import MarketRepository
from hypertrade.rag.service import RagService


def test_agent_chat_market_summary_creates_report_trace_and_memory(tmp_path):
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

    kernel = AgentKernel(
        db,
        settings=Settings(
            DEEPSEEK_API_KEY="",
            KNOWLEDGE_DIR=tmp_path,
            OKX_REST_URL="http://127.0.0.1:9",
        ),
    )
    run = kernel.run_chat("请归纳一下当前 OKX 永续合约行情")

    assert run.status == "completed"
    assert (
        "BTC-USDT-SWAP" in run.report_markdown
        or "当前无法获取实时 OKX 行情" in run.report_markdown
    )
    if "当前无法获取实时 OKX 行情" in run.report_markdown:
        assert run.report_json["data_source"] == "unavailable"
    assert run.report_json["market_scope"] == "OKX SWAP"
    tool_names = [
        event.tool_name
        for event in run.trace_events
        if not event.tool_name.startswith("graph.")
    ]
    graph_names = [
        event.tool_name
        for event in run.trace_events
        if event.tool_name.startswith("graph.")
    ]
    assert "graph.intent_classify" in graph_names
    assert "graph.final_report" in graph_names
    assert tool_names == [
        "market.summary",
        "rag.search",
        "memory.write",
    ]


def test_agent_routes_live_order_history_prompt_away_from_market_fallback(tmp_path):
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
    kernel = AgentKernel(
        db,
        settings=Settings(DEEPSEEK_API_KEY="", KNOWLEDGE_DIR=tmp_path),
        bitpro_adapter=FakeBitProAdapter(),
    )

    run = kernel.run_chat("我的实盘最近的一笔订单是什么")

    assert run.status == "completed"
    assert "## BitPro 实盘订单" in run.report_markdown
    assert "ord_latest ETH/USDT:USDT buy closed" in run.report_markdown
    assert "市场热度总结" not in run.report_markdown
    tool_names = [
        event.tool_name
        for event in run.trace_events
        if not event.tool_name.startswith("graph.")
    ]
    assert "bitpro.live_order_history" in tool_names
    assert "market.summary" not in tool_names
