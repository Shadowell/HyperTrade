"""
Unit & Integration Tests for Phase 6: Macro Event Causal Factor Engine
"""

from hypertrade.strategy.macro_event import (
    FreeMacroNewsProvider,
    MacroEventCausalExtractor,
    MacroEventPayload,
)


def test_hawkish_fed_causal_extraction():
    extractor = MacroEventCausalExtractor()
    payload = MacroEventPayload(
        event_id="evt_fed_01",
        raw_text="The Federal Reserve announced a rate hike of 50 bps today due to inflation.",
    )
    factor = extractor.extract_causal_factor(payload)

    assert factor.regime_type == "FED_HAWKISH"
    assert factor.sentiment_bias == -0.7
    assert factor.confidence_score >= 0.85
    assert factor.position_multiplier == 0.70


def test_geopolitical_risk_off_extraction():
    extractor = MacroEventCausalExtractor()
    payload = MacroEventPayload(
        event_id="evt_geo_01",
        raw_text="Military escalation and new trade sanctions trigger sudden geopolitical crisis.",
    )
    factor = extractor.extract_causal_factor(payload)

    assert factor.regime_type == "GEOPOLITICAL_RISK_OFF"
    assert factor.sentiment_bias == -0.9
    assert factor.position_multiplier == 0.50  # Risk sizing cut in half


def test_neutral_news_extraction():
    extractor = MacroEventCausalExtractor()
    payload = MacroEventPayload(
        event_id="evt_neutral_01",
        raw_text="Weekly market summary: prices remained bound in a quiet consolidation range.",
    )
    factor = extractor.extract_causal_factor(payload)

    assert factor.regime_type == "NEUTRAL"
    assert factor.sentiment_bias == 0.0
    assert factor.position_multiplier == 1.0


def test_free_macro_news_provider_integration():
    provider = FreeMacroNewsProvider()
    factors = provider.fetch_and_extract_latest_causal_factors(symbol="CL=F")

    assert len(factors) == 3
    regimes = {f.regime_type for f in factors}
    assert "FED_HAWKISH" in regimes
    assert "OPEC_CUT" in regimes
    assert "GEOPOLITICAL_RISK_OFF" in regimes
