"""Real-time market news ingestion and management.

Provides normalized news article models, deduplication, multiple source adapters,
and a unified query interface for the Perception Layer.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol


@dataclass(frozen=True)
class NewsArticle:
    id: str
    title: str
    content: str
    url: str
    source: str
    published_at: datetime
    symbols: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        title: str,
        content: str = "",
        url: str = "",
        source: str = "general",
        published_at: datetime | None = None,
        symbols: Sequence[str] | None = None,
        metadata: dict[str, Any] | None = None,
        article_id: str | None = None,
    ) -> NewsArticle:
        dt = published_at or datetime.now(UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        norm_symbols = [s.strip().upper() for s in (symbols or []) if s.strip()]
        if not article_id:
            digest_src = f"{title.strip()}:{source.strip()}:{url.strip()}"
            article_id = "news_" + hashlib.sha256(digest_src.encode("utf-8")).hexdigest()[:16]
        return cls(
            id=article_id,
            title=title.strip(),
            content=content.strip(),
            url=url.strip(),
            source=source.strip().lower(),
            published_at=dt,
            symbols=norm_symbols,
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at.isoformat(),
            "symbols": self.symbols,
            "metadata": self.metadata,
        }


class NewsSourceProtocol(Protocol):
    """Protocol for pluggable news feed sources."""

    def fetch_latest(self, limit: int = 50) -> list[NewsArticle]:
        ...


class InMemoryNewsFeed:
    """In-memory news source useful for testing and local perception injection."""

    def __init__(self, initial_articles: Sequence[NewsArticle] | None = None) -> None:
        self._articles: list[NewsArticle] = list(initial_articles or [])

    def add(self, article: NewsArticle) -> None:
        self._articles.insert(0, article)

    def fetch_latest(self, limit: int = 50) -> list[NewsArticle]:
        return self._articles[:limit]


class NewsIngestionService:
    """Central store and query coordinator for news articles."""

    def __init__(self, sources: Sequence[NewsSourceProtocol] | None = None) -> None:
        self._sources: list[NewsSourceProtocol] = list(sources or [])
        self._store: dict[str, NewsArticle] = {}

    def register_source(self, source: NewsSourceProtocol) -> None:
        self._sources.append(source)

    def ingest(self, articles: Sequence[NewsArticle]) -> int:
        added = 0
        for article in articles:
            if article.id not in self._store:
                self._store[article.id] = article
                added += 1
            else:
                existing = self._store[article.id]
                merged_symbols = sorted(set(existing.symbols + article.symbols))
                if merged_symbols != existing.symbols:
                    self._store[article.id] = NewsArticle(
                        id=existing.id,
                        title=existing.title,
                        content=existing.content,
                        url=existing.url,
                        source=existing.source,
                        published_at=existing.published_at,
                        symbols=merged_symbols,
                        metadata={**existing.metadata, **article.metadata},
                    )
        return added

    def sync_sources(self, limit_per_source: int = 50) -> int:
        total_added = 0
        for src in self._sources:
            try:
                fetched = src.fetch_latest(limit=limit_per_source)
                total_added += self.ingest(fetched)
            except Exception:
                continue
        return total_added

    def get_latest(
        self,
        *,
        limit: int = 20,
        symbol: str | None = None,
        max_age_hours: int = 48,
    ) -> list[NewsArticle]:
        now = datetime.now(UTC)
        cutoff = now - timedelta(hours=max_age_hours)
        norm_sym = symbol.strip().upper() if symbol else None

        filtered: list[NewsArticle] = []
        for art in self._store.values():
            if art.published_at < cutoff:
                continue
            if norm_sym:
                clean_sym = norm_sym.split("-")[0]
                if not any(clean_sym in s or s in norm_sym for s in art.symbols):
                    continue
            filtered.append(art)

        filtered.sort(key=lambda a: a.published_at, reverse=True)
        return filtered[:limit]

    def search(self, query: str, limit: int = 10) -> list[NewsArticle]:
        q = query.strip().lower()
        if not q:
            return self.get_latest(limit=limit)
        results: list[NewsArticle] = []
        for art in self._store.values():
            if q in art.title.lower() or q in art.content.lower():
                results.append(art)
        results.sort(key=lambda a: a.published_at, reverse=True)
        return results[:limit]
