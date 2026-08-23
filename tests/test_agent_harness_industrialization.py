"""Surviving coverage from the harness industrialization module.

The dead executor classes (ModelCallHarnessNormalizer,
ToolExecutionSelfHealer, ParallelToolPipeline) were removed from
agent/planner.py; production uses the harness_v2 implementations, which are
covered by tests/test_agent_harness_v2.py.
"""

from hypertrade.db import Database
from hypertrade.rag.service import RagService


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
