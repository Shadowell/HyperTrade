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
