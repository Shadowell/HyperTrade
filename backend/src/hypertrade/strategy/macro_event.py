"""
Macro & Unstructured Event Causal Factor Extraction Engine & Free Provider Adapters

FROZEN (2026-08-23): not wired to any runtime path and has no live news source.
Revisit only with a reviewed, source-bound news contract; an autonomous loop
fetching unvetted external feeds on its own initiative is a side effect no
research verdict should require.
"""

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field


class MacroEventPayload(BaseModel):
    event_id: str
    source: str = "news_feed"
    raw_text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MacroCausalFactor(BaseModel):
    event_id: str
    regime_type: str
    sentiment_bias: float = Field(
        ..., description="Sentiment bias in [-1.0, 1.0]"
    )
    confidence_score: float = Field(
        ..., description="Confidence score in [0.0, 1.0]"
    )
    position_multiplier: float = Field(
        ..., description="Dynamic risk position scaling factor"
    )
    summary: str
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MacroEventCausalExtractor:
    """
    Parses raw unstructured macroeconomic & market news feeds into structured
    quantitative causal factors that modulate MCTS search descriptors.
    """

    HAWKISH_KEYWORDS = [
        "raise rate", "rate hike", "inflation surge", "tightening", "hawkish", "加息", "通胀"
    ]
    DOVISH_KEYWORDS = [
        "cut rate", "rate cut", "easing", "dovish", "stimulus", "降息", "宽松"
    ]
    OPEC_KEYWORDS = [
        "opec", "oil cut", "production reduction", "eia inventory", "减产", "原油库存"
    ]
    GEOPOLITICAL_KEYWORDS = [
        "war", "conflict", "sanctions", "strike", "escalation", "制裁", "冲突"
    ]

    def extract_causal_factor(self, payload: MacroEventPayload) -> MacroCausalFactor:
        text = payload.raw_text.lower()

        is_hawkish = any(kw in text for kw in self.HAWKISH_KEYWORDS)
        is_dovish = any(kw in text for kw in self.DOVISH_KEYWORDS)
        is_opec = any(kw in text for kw in self.OPEC_KEYWORDS)
        is_geopolitical = any(kw in text for kw in self.GEOPOLITICAL_KEYWORDS)

        if is_hawkish:
            regime = "FED_HAWKISH"
            sentiment = -0.7
            confidence = 0.85
            pos_mult = 0.7  # Reduce position sizing during hawkish volatility
            summary = "Hawkish macro signal: tightening expectations increase market friction"
        elif is_dovish:
            regime = "FED_DOVISH"
            sentiment = 0.8
            confidence = 0.90
            pos_mult = 1.25  # Increase position sizing during dovish expansion
            summary = "Dovish macro signal: liquidity expansion favors risk asset momentum"
        elif is_opec:
            regime = "OPEC_CUT"
            sentiment = 0.6
            confidence = 0.80
            pos_mult = 1.10
            summary = "OPEC supply constraint: oil & energy commodity momentum favored"
        elif is_geopolitical:
            regime = "GEOPOLITICAL_RISK_OFF"
            sentiment = -0.9
            confidence = 0.95
            pos_mult = 0.50  # Strongly cut position sizes to 50% during risk-off events
            summary = "High-risk geopolitical tension: defensive risk-off mode enforced"
        else:
            regime = "NEUTRAL"
            sentiment = 0.0
            confidence = 0.50
            pos_mult = 1.0
            summary = "Neutral macroeconomic news flow"

        return MacroCausalFactor(
            event_id=payload.event_id,
            regime_type=regime,
            sentiment_bias=sentiment,
            confidence_score=confidence,
            position_multiplier=pos_mult,
            summary=summary,
        )


class FreeMacroNewsProvider:
    """
    Adapter interfacing zero-cost / free-tier news sources (yfinance, RSS feeds, Finnhub free API)
    popularized by open-source Trading Agents (e.g. TradingAgents, Lumibot, FinRobot).
    """

    def __init__(self, extractor: MacroEventCausalExtractor | None = None) -> None:
        self.extractor = extractor or MacroEventCausalExtractor()

    def fetch_rss_feed(self, rss_url: str, source_name: str = "rss") -> list[MacroEventPayload]:
        """
        Parses free RSS news feeds (e.g. Reuters, WallStreetCN, MarketWatch RSS).
        """
        payloads: list[MacroEventPayload] = []
        try:
            req = Request(rss_url, headers={"User-Agent": "HyperTrade-MacroBot/1.0"})
            with urlopen(req, timeout=5) as response:
                content = response.read()
                root = ET.fromstring(content)
                for idx, item in enumerate(root.findall(".//item")[:10]):
                    title = item.findtext("title", default="")
                    description = item.findtext("description", default="")
                    text = f"{title} - {description}".strip()
                    if text:
                        payloads.append(
                            MacroEventPayload(
                                event_id=f"rss_{source_name}_{idx}_{int(datetime.now(UTC).timestamp())}",
                                source=source_name,
                                raw_text=text,
                            )
                        )
        except Exception:
            # Fallback for network timeouts or isolated environments
            pass
        return payloads

    def fetch_simulated_yfinance_news(self, symbol: str = "CL=F") -> list[MacroEventPayload]:
        """
        Simulates yfinance.Ticker(symbol).news response format without external network dependency.
        """
        mock_headlines = [
            f"{symbol}: Federal Reserve signals potential rate hike amidst inflation surge",
            f"{symbol}: OPEC+ announces surprise production reduction to stabilize oil prices",
            f"{symbol}: Geopolitical conflict escalates in key shipping corridor",
        ]
        return [
            MacroEventPayload(
                event_id=f"yf_{symbol}_{idx}",
                source="yfinance_news",
                raw_text=headline,
            )
            for idx, headline in enumerate(mock_headlines)
        ]

    def fetch_and_extract_latest_causal_factors(
        self, symbol: str = "CL=F"
    ) -> list[MacroCausalFactor]:
        """
        Fetches free news items and extracts quantitative causal factors.
        """
        payloads = self.fetch_simulated_yfinance_news(symbol)
        return [self.extractor.extract_causal_factor(p) for p in payloads]
