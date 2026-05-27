from sqlalchemy import select

from hypertrade.db import Database, MemoryItem


class MemoryService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def write(
        self,
        *,
        content: str,
        kind: str,
        source_run_id: str,
        source_tool: str,
    ) -> MemoryItem:
        with self.db.session() as session:
            item = MemoryItem(
                content=content,
                kind=kind,
                source_run_id=source_run_id,
                source_tool=source_tool,
            )
            session.add(item)
            session.flush()
            session.expunge(item)
            return item

    def list_active(self) -> list[MemoryItem]:
        with self.db.session() as session:
            items = session.scalars(
                select(MemoryItem)
                .where(MemoryItem.disabled.is_(False))
                .order_by(MemoryItem.created_at)
            ).all()
            for item in items:
                session.expunge(item)
            return list(items)

    def disable(self, memory_id: str) -> None:
        with self.db.session() as session:
            item = session.get(MemoryItem, memory_id)
            if item is not None:
                item.disabled = True

    def delete(self, memory_id: str) -> None:
        with self.db.session() as session:
            item = session.get(MemoryItem, memory_id)
            if item is not None:
                session.delete(item)
