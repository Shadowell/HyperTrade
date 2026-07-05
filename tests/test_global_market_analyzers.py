"""Tests for global market regime analyzer."""

from hypertrade.global_market.analyzers import RegimeAnalyzer
from hypertrade.global_market.schemas import TickerQuote


class TestRegimeAnalyzer:
    """Test market regime classification logic."""

    def test_classify_risk_regime_stress(self):
        """Test stress regime classification."""
        analyzer = RegimeAnalyzer()

        # Sharp decline
        regime = analyzer.classify_risk_regime(sp500_change=-2.5, vix_level=30, russell_change=-3.0)
        assert regime == "stress"

        # Extreme volatility
        regime = analyzer.classify_risk_regime(sp500_change=-0.5, vix_level=40, russell_change=-1.0)
        assert regime == "stress"

    def test_classify_risk_regime_risk_off(self):
        """Test risk-off regime classification."""
        analyzer = RegimeAnalyzer()

        regime = analyzer.classify_risk_regime(sp500_change=-1.5, vix_level=20, russell_change=-2.0)
        assert regime == "risk_off"

        regime = analyzer.classify_risk_regime(sp500_change=-0.5, vix_level=27, russell_change=-1.0)
        assert regime == "risk_off"

    def test_classify_risk_regime_risk_on(self):
        """Test risk-on regime classification."""
        analyzer = RegimeAnalyzer()

        regime = analyzer.classify_risk_regime(sp500_change=1.5, vix_level=12, russell_change=2.0)
        assert regime == "risk_on"

    def test_classify_risk_regime_mixed(self):
        """Test mixed regime classification."""
        analyzer = RegimeAnalyzer()

        regime = analyzer.classify_risk_regime(sp500_change=0.5, vix_level=18, russell_change=0.3)
        assert regime == "mixed"

    def test_classify_risk_regime_unknown(self):
        """Test unknown regime with missing data."""
        analyzer = RegimeAnalyzer()

        regime = analyzer.classify_risk_regime(sp500_change=None, vix_level=15, russell_change=1.0)
        assert regime == "unknown"

    def test_classify_volatility_regime(self):
        """Test volatility regime classification."""
        analyzer = RegimeAnalyzer()

        assert analyzer.classify_volatility_regime(12.0) == "calm"
        assert analyzer.classify_volatility_regime(18.0) == "elevated"
        assert analyzer.classify_volatility_regime(30.0) == "stressed"
        assert analyzer.classify_volatility_regime(None) == "unknown"

    def test_classify_dollar_pressure(self):
        """Test dollar pressure classification."""
        analyzer = RegimeAnalyzer()

        assert analyzer.classify_dollar_pressure(dxy_level=106, dxy_change=0.5) == "strong"
        assert analyzer.classify_dollar_pressure(dxy_level=103, dxy_change=1.5) == "strong"
        assert analyzer.classify_dollar_pressure(dxy_level=98, dxy_change=-0.5) == "weak"
        assert analyzer.classify_dollar_pressure(dxy_level=102, dxy_change=-1.5) == "weak"
        assert analyzer.classify_dollar_pressure(dxy_level=103, dxy_change=0.2) == "neutral"
        assert analyzer.classify_dollar_pressure(dxy_level=None, dxy_change=0.5) == "unknown"

    def test_classify_rates_pressure(self):
        """Test rates pressure classification."""
        analyzer = RegimeAnalyzer()

        assert analyzer.classify_rates_pressure(0.3) == "rising"
        assert analyzer.classify_rates_pressure(-0.3) == "falling"
        assert analyzer.classify_rates_pressure(0.1) == "neutral"
        assert analyzer.classify_rates_pressure(None) == "unknown"

    def test_classify_cross_asset_signal_supportive(self):
        """Test supportive cross-asset signal."""
        analyzer = RegimeAnalyzer()

        signal = analyzer.classify_cross_asset_signal(
            sp500_change=1.0,
            vix_change=-5.0,
            gold_change=-0.5,
            dxy_change=-0.3,
        )
        assert signal == "supportive"

    def test_classify_cross_asset_signal_hostile(self):
        """Test hostile cross-asset signal."""
        analyzer = RegimeAnalyzer()

        signal = analyzer.classify_cross_asset_signal(
            sp500_change=-1.5,
            vix_change=10.0,
            gold_change=1.0,
            dxy_change=0.8,
        )
        assert signal == "hostile"

    def test_classify_cross_asset_signal_conflicting(self):
        """Test conflicting cross-asset signal."""
        analyzer = RegimeAnalyzer()

        signal = analyzer.classify_cross_asset_signal(
            sp500_change=0.5,
            vix_change=2.0,
            gold_change=-0.5,
            dxy_change=0.5,
        )
        assert signal == "conflicting"

    def test_classify_cross_asset_signal_unknown(self):
        """Test unknown signal with insufficient data."""
        analyzer = RegimeAnalyzer()

        signal = analyzer.classify_cross_asset_signal(
            sp500_change=1.0,
            vix_change=None,
            gold_change=None,
            dxy_change=None,
        )
        assert signal == "unknown"

    def test_analyze_complete_snapshot(self):
        """Test full analysis with all tickers."""
        analyzer = RegimeAnalyzer()

        tickers = [
            TickerQuote(
                symbol="^GSPC",
                price=4550,
                change_pct=1.2,
                source="yfinance",
                timestamp="2024-01-02",
            ),
            TickerQuote(
                symbol="^IXIC",
                price=14200,
                change_pct=1.5,
                source="yfinance",
                timestamp="2024-01-02",
            ),
            TickerQuote(
                symbol="^RUT", price=2000, change_pct=1.8, source="yfinance", timestamp="2024-01-02"
            ),
            TickerQuote(
                symbol="^VIX",
                price=13.5,
                change_pct=-3.0,
                source="yfinance",
                timestamp="2024-01-02",
            ),
            TickerQuote(
                symbol="DX-Y.NYB",
                price=102,
                change_pct=-0.2,
                source="yfinance",
                timestamp="2024-01-02",
            ),
            TickerQuote(
                symbol="GC=F",
                price=2050,
                change_pct=-0.5,
                source="yfinance",
                timestamp="2024-01-02",
            ),
            TickerQuote(
                symbol="^TNX", price=4.2, change_pct=0.1, source="yfinance", timestamp="2024-01-02"
            ),
        ]

        result = analyzer.analyze(tickers)

        assert result["risk_regime"] == "risk_on"
        assert result["volatility_regime"] == "calm"
        assert result["dollar_pressure"] == "neutral"
        assert result["rates_pressure"] == "neutral"
        assert result["cross_asset_signal"] == "supportive"
