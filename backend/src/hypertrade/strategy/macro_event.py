"""
Macro & Unstructured Event Causal Factor Extraction Engine
"""

from datetime import UTC, datetime

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
