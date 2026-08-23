from pathlib import Path

from hypertrade.db import Database, MemoryItem
from hypertrade.memory.service import MemoryService
from hypertrade.rag.service import RagHit, RagService
from hypertrade.runtime.adapters.tool_runtime import _focus_rag_hits
from sqlalchemy import select


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


def test_rag_public_projection_rejects_vector_only_single_term_matches():
    unrelated = RagHit(
        source_path="docs/knowledge/tool-usage-guide.md",
        title="HyperTrade 工具运维指南",
        chunk_index=0,
        content="仅包含运维命令。",
        score=0.8,
        content_preview="仅包含运维命令。",
    )

    assert _focus_rag_hits([unrelated], query="火星套利") == []


def test_memory_search_pushes_kind_filter_down_and_audits_only_returned_usage(tmp_path):
    """kind 过滤在 SQL 侧生效；usage 只为真正返回的条目计数。"""
    db = Database(f"sqlite:///{tmp_path}/mem.db")
    db.create_all()
    service = MemoryService(db)
    risk_id = service.write(
        content="Risk budget stays conservative.",
        kind="risk_note",
        source_run_id="run_1",
        source_tool="fixture",
    ).id
    service.write(
        content="Risk of double counting remains.",
        kind="market_summary",
        source_run_id="run_1",
        source_tool="fixture",
    )

    items = service.search(kind="risk_note", limit=10)

    assert [item.id for item in items] == [risk_id]
    with db.session() as session:
        # Write seeds usage_count=1; a returned search hit increments to 2,
        # while rows that were only scanned stay untouched.
        hit = session.get(MemoryItem, risk_id)
        assert hit.usage_count == 2
        other = session.scalars(
            select(MemoryItem).where(MemoryItem.kind == "market_summary")
        ).one()
        assert other.usage_count == 1


def test_prompt_context_orders_by_importance_then_recency(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/mem.db")
    db.create_all()
    service = MemoryService(db)
    low = service.write(
        content="low weight",
        kind="note",
        source_run_id="r",
        source_tool="t",
        importance=0.1,
    ).id
    high = service.write(
        content="high weight",
        kind="note",
        source_run_id="r",
        source_tool="t",
        importance=0.9,
    ).id

    context = service.prompt_context(limit=2)

    assert [item.id for item in context] == [high, low]


def test_kernel_injects_governed_memory_into_system_prompt(monkeypatch, tmp_path):
    """write→recall 闭环：高重要性记忆自动出现在 planner 的 system prompt。"""
    from unittest.mock import MagicMock

    from hypertrade.agent.kernel import AgentKernel
    from hypertrade.config import Settings
    from hypertrade.providers.chat import ChatResponse

    db = Database(f"sqlite:///{tmp_path}/mem.db")
    db.create_all()
    MemoryService(db).write(
        content="Risk budget stays conservative.",
        kind="risk_note",
        source_run_id="prior",
        source_tool="fixture",
        importance=0.9,
    )

    captured: dict[str, str] = {}

    def fake_chat(messages, tools=None):
        captured["system"] = messages[0]["content"]
        return ChatResponse(content="done")

    llm = MagicMock()
    llm.name = "replay"
    llm.model = "test"
    llm.chat.side_effect = fake_chat
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda self, selected=None, selected_model=None: llm,
    )

    from hypertrade.config import Settings as _S  # noqa: F401  (already imported)

    kernel = AgentKernel(
        db,
        knowledge_dir=tmp_path,
        settings=Settings(DEEPSEEK_API_KEY="k", KNOWLEDGE_DIR=tmp_path),
    )
    kernel.run_chat("review memory")

    assert "[memory" in captured["system"]
    assert "Risk budget stays conservative." in captured["system"]


def test_kernel_memory_injection_can_be_disabled(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from hypertrade.agent.kernel import AgentKernel
    from hypertrade.config import Settings
    from hypertrade.memory.service import MemoryService
    from hypertrade.providers.chat import ChatResponse

    db = Database(f"sqlite:///{tmp_path}/mem.db")
    db.create_all()
    MemoryService(db).write(
        content="Risk budget stays conservative.",
        kind="risk_note",
        source_run_id="prior",
        source_tool="fixture",
        importance=0.9,
    )

    captured: dict[str, str] = {}

    def fake_chat(messages, tools=None):
        captured["system"] = messages[0]["content"]
        return ChatResponse(content="done")

    llm = MagicMock()
    llm.name = "replay"
    llm.model = "test"
    llm.chat.side_effect = fake_chat
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda self, selected=None, selected_model=None: llm,
    )

    kernel = AgentKernel(
        db,
        knowledge_dir=tmp_path,
        settings=Settings(
            DEEPSEEK_API_KEY="k",
            KNOWLEDGE_DIR=tmp_path,
            AGENT_MEMORY_PROMPT_INJECTION=False,
        ),
    )
    kernel.run_chat("review memory")

    assert "[memory" not in captured["system"]


def test_rag_scan_is_gated_by_file_metadata(tmp_path: Path):
    """目录签名未变时 scan_once 不再全盘重读文件。"""
    db = Database(f"sqlite:///{tmp_path}/rag.db")
    db.create_all()
    knowledge_dir = tmp_path / "knowledge"
    knowledge_dir.mkdir()
    (knowledge_dir / "a.md").write_text("# A\nfirst", encoding="utf-8")

    rag = RagService(db, knowledge_dir=knowledge_dir)
    first = rag.scan_once()
    assert first.ingested_files == 1

    # No metadata change -> skip re-ingest without reading file contents.
    skipped = rag.scan_once()
    assert skipped.ingested_files == 0

    # Content edit changes mtime/size -> rescan picks it up.
    (knowledge_dir / "a.md").write_text("# A\nsecond revision", encoding="utf-8")
    updated = rag.scan_once()
    assert updated.ingested_files == 1
