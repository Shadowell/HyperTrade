"""Regime classification logic for global market state."""

from __future__ import annotations

from hypertrade.global_market.schemas import (
    CrossAssetSignal,
    DollarPressure,
    RatesPressure,
    RiskRegime,
    TickerQuote,
    VolatilityRegime,
)


class RegimeAnalyzer:
    """Classifies market regimes from raw ticker data.

    Logic follows institutional market regime frameworks:
    - Risk regime: equity performance + volatility + breadth
    - Volatility regime: VIX levels (calm < 15, elevated 15-25, stressed > 25)
    - Dollar pressure: DXY levels and change
    - Rates pressure: 10Y yield change
    - Cross-asset signal: coordination across assets
    """

    def classify_risk_regime(
        self,
        sp500_change: float | None,
        vix_level: float | None,
        russell_change: float | None,
    ) -> RiskRegime:
        """Classify overall risk appetite.

        Args:
            sp500_change: S&P 500 percent change
            vix_level: VIX absolute level
            russell_change: Russell 2000 percent change (small cap risk proxy)

        Returns:
            Risk regime classification
        """
        if sp500_change is None or vix_level is None:
            return "unknown"

        # Stress: sharp equity decline or extreme volatility
        if sp500_change < -2.0 or vix_level > 35:
            return "stress"

        # Risk off: equity weakness or elevated volatility
        if sp500_change < -1.0 or vix_level > 25:
            return "risk_off"

        # Risk on: equity strength and calm volatility
        if sp500_change > 1.0 and vix_level < 15:
            return "risk_on"

        # Mixed: conflicting signals
        return "mixed"

    def classify_volatility_regime(self, vix_level: float | None) -> VolatilityRegime:
        """Classify volatility level from VIX.

        Args:
            vix_level: VIX absolute level

        Returns:
            Volatility regime classification
        """
        if vix_level is None:
            return "unknown"

        if vix_level < 15:
            return "calm"
        elif vix_level < 25:
            return "elevated"
        else:
            return "stressed"

    def classify_dollar_pressure(
        self,
        dxy_level: float | None,
        dxy_change: float | None,
    ) -> DollarPressure:
        """Classify USD strength.

        Args:
            dxy_level: Dollar Index absolute level
            dxy_change: Dollar Index percent change

        Returns:
            Dollar pressure classification
        """
        if dxy_level is None:
            return "unknown"

        # Strong: high level or sharp intraday gain
        if dxy_level > 105 or (dxy_change is not None and dxy_change > 1.0):
            return "strong"

        # Weak: low level or sharp intraday decline
        if dxy_level < 100 or (dxy_change is not None and dxy_change < -1.0):
            return "weak"

        return "neutral"

    def classify_rates_pressure(
        self,
        tnx_change: float | None,
    ) -> RatesPressure:
        """Classify interest rate direction.

        Args:
            tnx_change: 10Y Treasury yield change in basis points (bp)

        Returns:
            Rates pressure classification
        """
        if tnx_change is None:
            return "unknown"

        # Convert percent change to basis points (1% = 100bp)
        # For yields around 4%, 0.25% change ≈ 10bp move
        bp_threshold = 0.25  # ~10bp at 4% yield

        if tnx_change > bp_threshold:
            return "rising"
        elif tnx_change < -bp_threshold:
            return "falling"
        else:
            return "neutral"

    def classify_cross_asset_signal(
        self,
        sp500_change: float | None,
        vix_change: float | None,
        gold_change: float | None,
        dxy_change: float | None,
    ) -> CrossAssetSignal:
        """Classify cross-asset coordination.

        Args:
            sp500_change: S&P 500 percent change
            vix_change: VIX percent change
            gold_change: Gold percent change
            dxy_change: Dollar Index percent change

        Returns:
            Cross-asset signal classification
        """
        # Require at least 3 signals
        available = sum(x is not None for x in [sp500_change, vix_change, gold_change, dxy_change])
        if available < 3:
            return "unknown"

        # Supportive: risk-on across assets
        # Equities up, VIX down, gold down (no safe haven), dollar neutral/weak
        supportive_signals = 0
        if sp500_change is not None and sp500_change > 0:
            supportive_signals += 1
        if vix_change is not None and vix_change < 0:
            supportive_signals += 1
        if gold_change is not None and gold_change < 0:
            supportive_signals += 1
        if dxy_change is not None and dxy_change <= 0:
            supportive_signals += 1

        if supportive_signals >= 3:
            return "supportive"

        # Hostile: risk-off across assets
        # Equities down, VIX up, gold up (safe haven), dollar strong
        hostile_signals = 0
        if sp500_change is not None and sp500_change < 0:
            hostile_signals += 1
        if vix_change is not None and vix_change > 0:
            hostile_signals += 1
        if gold_change is not None and gold_change > 0:
            hostile_signals += 1
        if dxy_change is not None and dxy_change > 0:
            hostile_signals += 1

        if hostile_signals >= 3:
            return "hostile"

        # Conflicting: mixed signals
        return "conflicting"

    def analyze(self, tickers: list[TickerQuote]) -> dict[str, str]:
        """Analyze ticker quotes and classify all regimes.

        Args:
            tickers: List of ticker quotes

        Returns:
            Dict with all regime classifications
        """
        # Extract ticker data by symbol
        ticker_map: dict[str, TickerQuote] = {
            t.symbol: t for t in tickers if t.error is None
        }

        # Get values for classification
        sp500 = ticker_map.get("^GSPC")
        vix = ticker_map.get("^VIX")
        russell = ticker_map.get("^RUT")
        dxy = ticker_map.get("DX-Y.NYB")
        gold = ticker_map.get("GC=F")
        tnx = ticker_map.get("^TNX")

        sp500_change = sp500.change_pct if sp500 else None
        vix_level = vix.price if vix else None
        vix_change = vix.change_pct if vix else None
        russell_change = russell.change_pct if russell else None
        dxy_level = dxy.price if dxy else None
        dxy_change = dxy.change_pct if dxy else None
        gold_change = gold.change_pct if gold else None
        tnx_change = tnx.change_pct if tnx else None

        return {
            "risk_regime": self.classify_risk_regime(sp500_change, vix_level, russell_change),
            "volatility_regime": self.classify_volatility_regime(vix_level),
            "dollar_pressure": self.classify_dollar_pressure(dxy_level, dxy_change),
            "rates_pressure": self.classify_rates_pressure(tnx_change),
            "cross_asset_signal": self.classify_cross_asset_signal(
                sp500_change, vix_change, gold_change, dxy_change
            ),
        }
