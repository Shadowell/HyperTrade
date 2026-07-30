"""
Unit & Integration Tests for Agent Harness Industrialization
"""

from hypertrade.agent.planner import (
    ModelCallHarnessNormalizer,
    ToolExecutionSelfHealer,
)
from hypertrade.db import Database
from hypertrade.rag.service import RagService


def test_model_call_harness_normalizer():
    # 1. Test malformed raw call with stringified arguments
    raw_call = {
        "tool_name": "market_candles",
        "parameters": '{"symbol": "BTC-USDT-SWAP", "limit": 50}',
    }
    norm = ModelCallHarnessNormalizer.normalize_tool_call(raw_call)
    assert norm["name"] == "market_candles"
    assert norm["arguments"]["symbol"] == "BTC-USDT-SWAP"
    assert norm["arguments"]["limit"] == 50

    # 2. Test invalid non-dict input fallback
    norm_invalid = ModelCallHarnessNormalizer.normalize_tool_call("not a dict")
    assert norm_invalid["name"] == "invalid"


def test_tool_execution_self_healer_success():
    def dummy_executor(name: str, args: dict) -> dict:
        return {"status": "ok", "data": "success"}

    healer = ToolExecutionSelfHealer(dummy_executor)
    res = healer.execute_with_self_healing("test_tool", {"a": 1})
    assert res["status"] == "ok"


def test_tool_execution_self_healer_fallback_retry():
    def failing_executor(name: str, args: dict) -> dict:
        raise ValueError("Missing required param 'symbol'")

    def fallback_repair_fn(name: str, err_msg: str) -> dict:
        assert "symbol" in err_msg
        return {"status": "ok", "repaired": True}

    healer = ToolExecutionSelfHealer(failing_executor)
    res = healer.execute_with_self_healing(
        "test_tool", {}, fallback_retry_fn=fallback_repair_fn
    )
    assert res["status"] == "ok"
    assert res["repaired"] is True


def test_rag_hybrid_rrf_search(tmp_path):
    db = Database("sqlite:///:memory:")
    db.create_all()

    # Create dummy markdown document for RAG scan
    doc_path = tmp_path / "trading_risk.md"
    doc_path.write_text(
        "# Risk Governance Protocol\n\nDaily drawdown limit must strictly be 3 percent.",
        encoding="utf-8",
    )

    rag = RagService(db, knowledge_dir=tmp_path)
    rag.scan_once()

    hits = rag.search_hybrid("drawdown limit", limit=3)
    assert len(hits) > 0
    assert "drawdown" in hits[0].content.lower()
    assert hits[0].score > 0
