"""Real-time market news ingestion and management.

Provides normalized news article models, deduplication, multiple source adapters,
and a unified query interface for the Perception Layer.
"""

import email.utils
import hashlib
import json
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

logger = logging.getLogger(__name__)

KNOWN_CRYPTO_SYMBOLS: frozenset[str] = frozenset(
    {
        "BTC",
        "ETH",
        "SOL",
        "XRP",
        "DOGE",
        "ADA",
        "AVAX",
        "DOT",
        "LINK",
        "NEAR",
        "SUI",
        "APT",
        "PEPE",
        "SHIB",
        "OP",
        "ARB",
        "BNB",
        "LTC",
        "BCH",
        "TRX",
        "TON",
    }
)


def extract_symbols_from_text(text: str) -> list[str]:
    """Detect common crypto coin symbols from headline and description text."""
    if not text:
        return []
    found: set[str] = set()
    for sym in KNOWN_CRYPTO_SYMBOLS:
        pattern = rf"\b{sym}\b"
        if re.search(pattern, text, re.IGNORECASE):
            found.add(sym)
    if re.search(r"\bbitcoin\b", text, re.IGNORECASE):
        found.add("BTC")
    if re.search(r"\bethereum\b", text, re.IGNORECASE):
        found.add("ETH")
    if re.search(r"\bsolana\b", text, re.IGNORECASE):
        found.add("SOL")
    if re.search(r"\bdogecoin\b", text, re.IGNORECASE):
        found.add("DOGE")
    if re.search(r"\bripple\b", text, re.IGNORECASE):
        found.add("XRP")
    return sorted(found)


def _clean_domain(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain.split(".")[0] or "rss"
    except Exception:
        return "rss"


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


class RssCryptoNewsSource:
    """Ingest public crypto RSS feeds (CoinDesk, Cointelegraph, Decrypt, etc.)."""

    DEFAULT_FEEDS: tuple[str, ...] = (
        "https://cointelegraph.com/rss",
        "https://decrypt.co/feed",
    )

    def __init__(
        self,
        feed_urls: Sequence[str] | None = None,
        *,
        timeout_seconds: float = 5.0,
        user_agent: str = "HyperTrade-Perception/1.0",
    ) -> None:
        self.feed_urls = list(feed_urls) if feed_urls else list(self.DEFAULT_FEEDS)
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent

    def fetch_latest(self, limit: int = 50) -> list[NewsArticle]:
        articles: list[NewsArticle] = []
        for url in self.feed_urls:
            try:
                articles.extend(self._fetch_feed(url, limit=limit))
            except Exception as exc:
                logger.warning("Failed to fetch RSS feed %s: %s", url, exc)
                continue
        articles.sort(key=lambda a: a.published_at, reverse=True)
        return articles[:limit]

    def _fetch_feed(self, url: str, limit: int) -> list[NewsArticle]:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/rss+xml, application/xml, text/xml",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            content = resp.read()
        return self._parse_rss_xml(content, source_name=_clean_domain(url), limit=limit)

    def _parse_rss_xml(self, xml_bytes: bytes, source_name: str, limit: int) -> list[NewsArticle]:
        try:
            root = ET.fromstring(xml_bytes)
        except Exception:
            return []
        items = root.findall(".//item")
        parsed: list[NewsArticle] = []
        for item in items[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub_date_str = (item.findtext("pubDate") or "").strip()
            if not title:
                continue
            published_at: datetime | None = None
            if pub_date_str:
                try:
                    dt = email.utils.parsedate_to_datetime(pub_date_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    published_at = dt.astimezone(UTC)
                except Exception:
                    pass
            clean_desc = re.sub(r"<[^>]+>", "", desc).strip()
            symbols = extract_symbols_from_text(f"{title} {clean_desc}")
            parsed.append(
                NewsArticle.create(
                    title=title,
                    content=clean_desc,
                    url=link,
                    source=source_name,
                    published_at=published_at,
                    symbols=symbols,
                    metadata={"feed_type": "rss"},
                )
            )
        return parsed


class CryptoPanicNewsSource:
    """Ingest curated news from CryptoPanic API."""

    def __init__(
        self,
        api_key: str = "",
        *,
        timeout_seconds: float = 5.0,
        base_url: str = "https://cryptopanic.com/api/v1/posts/",
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url

    def fetch_latest(self, limit: int = 50) -> list[NewsArticle]:
        if not self.api_key:
            return []
        try:
            url = f"{self.base_url}?auth_token={self.api_key}&public=true&limit={min(limit, 50)}"
            req = urllib.request.Request(url, headers={"User-Agent": "HyperTrade/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            articles: list[NewsArticle] = []
            for item in results:
                title = str(item.get("title", "")).strip()
                link = str(item.get("url", "")).strip()
                currencies = [
                    c.get("code", "").upper()
                    for c in item.get("currencies", [])
                    if isinstance(c, dict)
                ]
                published_at_str = item.get("published_at")
                published_at: datetime | None = None
                if published_at_str:
                    try:
                        published_at = datetime.fromisoformat(
                            published_at_str.replace("Z", "+00:00")
                        )
                    except Exception:
                        pass
                votes = item.get("votes", {})
                articles.append(
                    NewsArticle.create(
                        title=title,
                        url=link,
                        source="cryptopanic",
                        published_at=published_at,
                        symbols=currencies or extract_symbols_from_text(title),
                        metadata={"votes": votes, "domain": item.get("domain", "")},
                    )
                )
            return articles
        except Exception as exc:
            logger.warning("Failed to fetch CryptoPanic news: %s", exc)
            return []


class OkxAnnouncementsSource:
    """Fetch official announcements from OKX public notices."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        base_url: str = "https://www.okx.com/api/v5/support/announcements",
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url

    def fetch_latest(self, limit: int = 20) -> list[NewsArticle]:
        try:
            req = urllib.request.Request(self.base_url, headers={"User-Agent": "HyperTrade/1.0"})
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            items = data.get("data", [])
            if (
                isinstance(items, list)
                and items
                and isinstance(items[0], dict)
                and "details" in items[0]
            ):
                items = items[0].get("details", [])
            articles: list[NewsArticle] = []
            for item in items[:limit]:
                title = str(item.get("title", "")).strip()
                link = str(item.get("link", "") or item.get("url", "")).strip()
                ptime = item.get("pTime")
                published_at: datetime | None = None
                if ptime:
                    try:
                        published_at = datetime.fromtimestamp(int(ptime) / 1000, tz=UTC)
                    except Exception:
                        pass
                symbols = extract_symbols_from_text(title)
                category = (
                    "partnership_listing"
                    if any(w in title.lower() for w in ("list", "launch", "delist", "support"))
                    else "general_market"
                )
                articles.append(
                    NewsArticle.create(
                        title=title,
                        url=link,
                        source="okx_notice",
                        published_at=published_at,
                        symbols=symbols,
                        metadata={
                            "event_category": category,
                            "okx_type": item.get("annType", ""),
                        },
                    )
                )
            return articles
        except Exception as exc:
            logger.debug("Failed to fetch OKX announcements: %s", exc)
            return []


class WhaleMovementSource:
    """Source for on-chain whale transaction alerts and large liquidation spikes."""

    def __init__(self, initial_alerts: Sequence[NewsArticle] | None = None) -> None:
        self._alerts: list[NewsArticle] = list(initial_alerts or [])

    def record_alert(
        self,
        *,
        symbol: str,
        amount_usd: float,
        from_wallet: str,
        to_wallet: str,
        tx_hash: str = "",
        headline: str | None = None,
    ) -> NewsArticle:
        sym = symbol.strip().upper().split("-")[0]
        title = (
            headline
            or f"Whale Alert: ${amount_usd:,.0f} of {sym} transferred ({from_wallet[:6]}... -> {to_wallet[:6]}...)"
        )
        article = NewsArticle.create(
            title=title,
            content=f"On-chain large transfer of ${amount_usd:,.0f} {sym}. From: {from_wallet} To: {to_wallet}. Tx: {tx_hash}",
            url=f"https://etherscan.io/tx/{tx_hash}" if tx_hash else "",
            source="whale_alert",
            published_at=datetime.now(UTC),
            symbols=[sym],
            metadata={
                "event_category": "whale_movement",
                "urgency": "breaking" if amount_usd >= 50_000_000 else "high",
                "amount_usd": amount_usd,
            },
        )
        self._alerts.insert(0, article)
        return article

    def fetch_latest(self, limit: int = 50) -> list[NewsArticle]:
        return self._alerts[:limit]


def build_default_news_service(
    *,
    cryptopanic_key: str = "",
    enable_external: bool = True,
) -> NewsIngestionService:
    """Factory creating a NewsIngestionService wired with live or mock-safe sources."""
    sources: list[NewsSourceProtocol] = [InMemoryNewsFeed(), WhaleMovementSource()]
    if enable_external:
        sources.append(RssCryptoNewsSource())
        sources.append(OkxAnnouncementsSource())
        if cryptopanic_key:
            sources.append(CryptoPanicNewsSource(api_key=cryptopanic_key))
    return NewsIngestionService(sources)
