"""Real-time news sentiment and event categorization engine.

Extracts structured trading sentiment:
- Sentiment score: [-1.0, 1.0] (bullish/bearish)
- Affected symbols: ['BTC', 'ETH', etc.]
- Event category: regulatory, exploit_hack, macro_rates, etc.
- Urgency: breaking, high, normal, low
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from hypertrade.market.news import NewsArticle
from hypertrade.providers.chat import ChatProvider

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
    }
)

BULLISH_KEYWORDS: tuple[str, ...] = (
    "surge",
    "rally",
    "all-time high",
    "ath",
    "breakout",
    "bullish",
    "approval",
    "etf approved",
    "inflow",
    "adoption",
    "partnership",
    "listing",
    "listed on",
    "upgrade",
    "mainnet launch",
    "accumulate",
    "buyback",
    "rate cut",
    "soar",
    "gain",
    "暴涨",
    "大涨",
    "突破",
    "利好",
    "获批",
    "通过",
    "流入",
    "上线",
    "主网上线",
    "降息",
)

BEARISH_KEYWORDS: tuple[str, ...] = (
    "plunge",
    "crash",
    "selloff",
    "bearish",
    "hack",
    "hacked",
    "exploit",
    "drained",
    "stolen",
    "investigation",
    "lawsuit",
    "sec charges",
    "ban",
    "banned",
    "delisting",
    "outflow",
    "insolvency",
    "bankruptcy",
    "rate hike",
    "subpoena",
    "dump",
    "暴跌",
    "大跌",
    "崩盘",
    "利空",
    "被盗",
    "攻击",
    "起诉",
    "封禁",
    "下架",
    "流出",
    "破产",
    "加息",
)

CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "exploit_hack",
        ("hack", "exploit", "stolen", "vulnerability", "drain", "attack", "被盗", "漏洞", "攻击"),
    ),
    (
        "regulatory",
        ("sec", "cftc", "fbi", "lawsuit", "charges", "ban", "court", "监管", "起诉", "罚款"),
    ),
    (
        "macro_rates",
        (
            "fed",
            "interest rate",
            "cpi",
            "inflation",
            "rate hike",
            "rate cut",
            "加息",
            "降息",
            "美联储",
        ),
    ),
    (
        "partnership_listing",
        ("listing", "listed", "binance lists", "coinbase lists", "partnership", "上线", "挂牌"),
    ),
    (
        "whale_movement",
        (
            "whale",
            "transferred to exchange",
            "moved to coinbase",
            "large transfer",
            "巨鲸",
            "大额转账",
        ),
    ),
)


@dataclass(frozen=True)
class NewsSentiment:
    article_id: str
    title: str
    affected_symbols: list[str]
    sentiment_score: float  # [-1.0, 1.0]
    event_category: str
    urgency: str  # "breaking", "high", "normal", "low"
    confidence: float  # [0.0, 1.0]
    summary: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "affected_symbols": self.affected_symbols,
            "sentiment_score": round(self.sentiment_score, 3),
            "event_category": self.event_category,
            "urgency": self.urgency,
            "confidence": round(self.confidence, 3),
            "summary": self.summary,
            "created_at": self.created_at.isoformat(),
        }


class NewsSentimentAnalyzer:
    """Extracts sentiment and event dimensions from news articles."""

    def __init__(self, provider: ChatProvider | None = None) -> None:
        self._provider = provider

    def analyze(self, article: NewsArticle) -> NewsSentiment:
        """Analyze one article. Falls back gracefully to rule-based analysis."""
        text = f"{article.title} {article.content}".strip()
        lower_text = text.lower()

        symbols = self._extract_symbols(text, article.symbols)

        bull_hits = sum(1 for kw in BULLISH_KEYWORDS if kw in lower_text)
        bear_hits = sum(1 for kw in BEARISH_KEYWORDS if kw in lower_text)

        total_hits = bull_hits + bear_hits
        if total_hits > 0:
            raw_score = (bull_hits - bear_hits) / total_hits
            confidence = min(1.0, 0.4 + 0.15 * total_hits)
        else:
            raw_score = 0.0
            confidence = 0.2

        category = "general_market"
        for cat_name, kw_list in CATEGORY_RULES:
            if any(kw in lower_text for kw in kw_list):
                category = cat_name
                break

        urgency = "normal"
        has_breaking = "breaking" in lower_text or "突发" in text
        if category in {"exploit_hack", "regulatory"} and (bear_hits >= 2 or has_breaking):
            urgency = "breaking"
        elif has_breaking or abs(raw_score) >= 0.7:
            urgency = "high"
        elif total_hits == 0:
            urgency = "low"

        score = max(-1.0, min(1.0, raw_score))

        return NewsSentiment(
            article_id=article.id,
            title=article.title,
            affected_symbols=symbols,
            sentiment_score=score,
            event_category=category,
            urgency=urgency,
            confidence=confidence,
            summary=article.title[:200],
        )

    def analyze_batch(self, articles: Sequence[NewsArticle]) -> list[NewsSentiment]:
        return [self.analyze(art) for art in articles]

    def aggregate_symbol_sentiment(
        self,
        symbol: str,
        sentiments: Sequence[NewsSentiment],
    ) -> dict[str, Any]:
        """Aggregate sentiment for a specific symbol."""
        norm_sym = symbol.strip().upper().split("-")[0]
        matched = [
            s for s in sentiments
            if norm_sym in s.affected_symbols or "*" in s.affected_symbols
        ]
        if not matched:
            return {
                "symbol": symbol,
                "sentiment_score": 0.0,
                "label": "neutral",
                "sample_count": 0,
                "urgency": "low",
                "breaking_events": [],
                "confidence": 0.0,
            }

        weighted_scores: list[float] = []
        breaking: list[str] = []
        for s in matched:
            weight = s.confidence * (2.0 if s.urgency in {"breaking", "high"} else 1.0)
            weighted_scores.append(s.sentiment_score * weight)
            if s.urgency == "breaking":
                breaking.append(f"[{s.event_category}] {s.title}")

        avg_score = sum(weighted_scores) / max(1.0, sum(s.confidence for s in matched))
        bounded_score = max(-1.0, min(1.0, avg_score))

        if bounded_score >= 0.25:
            label = "bullish"
        elif bounded_score <= -0.25:
            label = "bearish"
        else:
            label = "neutral"

        max_urgency = "low"
        urgency_ranks = {"low": 1, "normal": 2, "high": 3, "breaking": 4}
        for s in matched:
            if urgency_ranks.get(s.urgency, 1) > urgency_ranks.get(max_urgency, 1):
                max_urgency = s.urgency

        return {
            "symbol": symbol,
            "sentiment_score": round(bounded_score, 3),
            "label": label,
            "sample_count": len(matched),
            "urgency": max_urgency,
            "breaking_events": breaking[:3],
            "confidence": round(sum(s.confidence for s in matched) / len(matched), 3),
        }

    def _extract_symbols(self, text: str, explicit_symbols: Sequence[str]) -> list[str]:
        found: set[str] = {s.upper() for s in explicit_symbols if s}
        tokens = re.findall(r"\b[A-Z]{2,10}\b", text)
        for token in tokens:
            if token in KNOWN_CRYPTO_SYMBOLS:
                found.add(token)
        macro_terms = ("crypto", "all markets", "macro", "fed", "大盘", "全市场")
        if any(term in text.lower() for term in macro_terms):
            found.add("*")
        return sorted(found)
