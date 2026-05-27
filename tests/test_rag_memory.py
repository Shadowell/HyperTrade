from pathlib import Path

from hypertrade.db import Database
from hypertrade.memory.service import MemoryService
from hypertrade.rag.service import RagService


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
    assert memory.list_active() == []
