"""Audited long-term memory for Agent runs.

Memory is different from RAG: RAG reads curated documents, while Memory stores
runtime observations and preferences produced by Agent/tool activity. Every item
keeps source run/tool metadata so the harness can explain where a memory came
from and let an operator disable it.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import select

from hypertrade.db import Database, MemoryItem, utc_now


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
        tags: list[str] | None = None,
        importance: float | Decimal | str = Decimal("0.50"),
        confidence: float | Decimal | str = Decimal("0.70"),
    ) -> MemoryItem:
        normalized_content = content.strip()
        normalized_kind = _normalize_kind(kind)
        normalized_tags = _normalize_tags(tags or [], normalized_kind)
        with self.db.session() as session:
            # Exact dedupe keeps the Agent from writing the same observation on
            # every run. Reuse is still audited through usage_count/last_used_at.
            existing = session.scalar(
                select(MemoryItem)
                .where(MemoryItem.disabled.is_(False))
                .where(MemoryItem.kind == normalized_kind)
                .where(MemoryItem.content == normalized_content)
            )
            if existing is not None:
                existing.tags = sorted({*existing.tags, *normalized_tags})
                existing.usage_count += 1
                existing.last_used_at = utc_now()
                session.flush()
                session.expunge(existing)
                return existing
            item = MemoryItem(
                content=normalized_content,
                kind=normalized_kind,
                source_run_id=source_run_id,
                source_tool=source_tool,
                tags=normalized_tags,
                importance=_decimal(importance),
                confidence=_decimal(confidence),
                usage_count=1,
                last_used_at=utc_now(),
            )
            session.add(item)
            session.flush()
            session.expunge(item)
            return item

    def list_active(self) -> list[MemoryItem]:
        self._refresh_governed_assertions()
        with self.db.session() as session:
            items = session.scalars(
                select(MemoryItem)
                .where(MemoryItem.disabled.is_(False))
                .order_by(MemoryItem.created_at)
            ).all()
            for item in items:
                session.expunge(item)
            return list(items)

    def search(
        self,
        *,
        query: str = "",
        kind: str = "",
        tag: str = "",
        limit: int = 20,
    ) -> list[MemoryItem]:
        self._refresh_governed_assertions()
        normalized_query = query.casefold().strip()
        normalized_kind = kind.strip()
        normalized_tag = tag.casefold().strip()

        # Equality filters are pushed into SQL so the Python-side substring
        # scan only sees the relevant partition; ranking layers can replace it
        # later without changing the audit semantics of usage tracking.
        statement = select(MemoryItem).where(MemoryItem.disabled.is_(False))
        if normalized_kind:
            statement = statement.where(MemoryItem.kind == normalized_kind)
        statement = statement.order_by(MemoryItem.created_at.desc())

        with self.db.session() as session:
            candidates = session.scalars(statement).all()
            filtered: list[MemoryItem] = []
            for item in candidates:
                tags = [str(value).casefold() for value in item.tags]
                if normalized_tag and normalized_tag not in tags:
                    continue
                if normalized_query:
                    haystack = " ".join([item.kind, item.content, *tags]).casefold()
                    if normalized_query not in haystack:
                        continue
                session.expunge(item)
                filtered.append(item)
            result = filtered[: max(1, min(limit, 100))]
            # Usage is audited only for items actually returned to the Agent;
            # scanning a row must not count as remembering it.
            for item in result:
                self._mark_used(session, item.id)
            return list(result)

    @staticmethod
    def _mark_used(session: Any, memory_id: str) -> None:
        item = session.get(MemoryItem, memory_id)
        if item is not None:
            item.usage_count += 1
            item.last_used_at = utc_now()

    def prompt_context(self, *, limit: int = 5) -> list[MemoryItem]:
        """Deterministic top-K recall for system-prompt injection.

        Ordered by importance then recency so the same DB state always yields
        the same context window; bounded to keep prompt cost predictable.
        """
        with self.db.session() as session:
            items = session.scalars(
                select(MemoryItem)
                .where(MemoryItem.disabled.is_(False))
                .order_by(MemoryItem.importance.desc(), MemoryItem.created_at.desc())
                .limit(max(1, min(limit, 20)))
            ).all()
            for item in items:
                session.expunge(item)
            return list(items)

    def _refresh_governed_assertions(self) -> None:
        # Governed assertions fail closed before every read. Governance owns
        # assertion lifecycle only and never expands Agent permissions.
        from hypertrade.memory.governance import MemoryAssertionService

        MemoryAssertionService(self.db).refresh_lifecycle()

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


def _normalize_kind(kind: str) -> str:
    value = kind.strip().casefold().replace("-", "_").replace(" ", "_")
    return value or "observation"


def _normalize_tags(tags: list[str], kind: str) -> list[str]:
    values = {kind}
    for tag in tags:
        cleaned = tag.strip().casefold().replace(" ", "_")
        if cleaned:
            values.add(cleaned)
    return sorted(values)


def _decimal(value: float | Decimal | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))
