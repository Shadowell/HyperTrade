from pathlib import Path

from hypertrade.db import Database
from hypertrade.memory.service import MemoryService
from hypertrade.rag.service import RagHit, RagService
from hypertrade.runtime.adapters.tool_runtime import _focus_rag_hits


def test_rag_ingests_changed_markdown_and_memory_can_be_disabled(tmp_path: Path):
    db = Database("sqlite:///:memory:")
    db.create_all()
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "risk.md").write_text(
        "# Risk\nNever treat reports as investment advice.",
        encoding="utf-8",
    )

    rag = RagService(db, knowledge_dir=knowledge_dir)
    result = rag.scan_once()
    hits = rag.search("investment advice")

    memory = MemoryService(db)
    item = memory.write(
        content="User prefers aggressive paper scanning.",
        kind="preference",
        source_run_id="run-1",
        source_tool="memory.write",
    )
    memory.disable(item.id)

    assert result.ingested_files == 1
    assert hits and hits[0].source_path.endswith("risk.md")
    assert hits[0].title == "Risk"
    assert hits[0].chunk_index == 0
    assert hits[0].content_preview
    assert memory.list_active() == []


def test_memory_policy_fields_dedupe_and_search():
    db = Database("sqlite:///:memory:")
    db.create_all()
    memory = MemoryService(db)

    first = memory.write(
        content="User prefers conservative risk sizing.",
        kind="user_preference",
        source_run_id="run-1",
        source_tool="memory.write",
        tags=["risk", "preference"],
        importance=0.8,
        confidence=0.9,
    )
    second = memory.write(
        content="User prefers conservative risk sizing.",
        kind="user_preference",
        source_run_id="run-2",
        source_tool="memory.write",
        tags=["risk"],
    )
    hits = memory.search(query="conservative", tag="risk")

    assert first.id == second.id
    assert hits[0].id == first.id
    assert hits[0].usage_count >= 2
    assert hits[0].last_used_at is not None
    assert str(hits[0].importance) == "0.8000"
    assert str(hits[0].confidence) == "0.9000"


def test_rag_public_projection_rejects_late_mentions_in_operator_guides():
    guide = RagHit(
        source_path="docs/knowledge/tool-usage-guide.md",
        title="HyperTrade 工具运维指南",
        chunk_index=3,
        content=("运维命令说明。" * 80) + " momentum_breakout_v1",
        score=2.0,
        content_preview="运维命令说明。",
    )
    evidence = RagHit(
        source_path="eval://momentum-breakout",
        title="动量策略研究证据",
        chunk_index=0,
        content="momentum_breakout_v1 需要进行样本外验证。",
        score=1.0,
        content_preview="momentum_breakout_v1 需要进行样本外验证。",
    )

    assert _focus_rag_hits([guide, evidence], query="momentum_breakout_v1") == [evidence]
