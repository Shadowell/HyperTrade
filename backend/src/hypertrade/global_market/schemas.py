"""Global market data schemas and types."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Regime types
RiskRegime = Literal["risk_on", "risk_off", "stress", "mixed", "unknown"]
VolatilityRegime = Literal["calm", "elevated", "stressed", "unknown"]
DollarPressure = Literal["strong", "weak", "neutral", "unknown"]
RatesPressure = Literal["rising", "falling", "neutral", "unknown"]
CrossAssetSignal = Literal["supportive", "conflicting", "hostile", "unknown"]

# Asset classes
AssetClass = Literal["equity", "volatility", "fx", "commodity", "rates"]


class TickerQuote(BaseModel):
    """Single ticker quote with change metrics."""

    symbol: str = Field(description="Ticker symbol")
    price: float | None = Field(default=None, description="Latest price")
    change_pct: float | None = Field(default=None, description="Percent change from prior close")
    volume: int | None = Field(default=None, description="Trading volume")
    timestamp: str | None = Field(default=None, description="Quote timestamp")
    source: str = Field(description="Data source vendor")
    error: str | None = Field(default=None, description="Error message if fetch failed")


class GlobalMarketSnapshot(BaseModel):
    """Aggregated global market state with regime classifications."""

    # Regime classifications
    risk_regime: RiskRegime = Field(description="Overall risk appetite")
    volatility_regime: VolatilityRegime = Field(description="Volatility level")
    dollar_pressure: DollarPressure = Field(description="USD strength")
    rates_pressure: RatesPressure = Field(description="Interest rate direction")
    cross_asset_signal: CrossAssetSignal = Field(description="Cross-asset coordination")

    # Raw ticker data
    tickers: list[TickerQuote] = Field(default_factory=list, description="Individual ticker quotes")

    # Metadata
    timestamp: str = Field(description="Snapshot timestamp")
    missing_data: list[str] = Field(
        default_factory=list, description="Symbols with missing/failed data"
    )
    source_refs: list[dict[str, Any]] = Field(
        default_factory=list, description="Source references for audit"
    )

    @classmethod
    def create_unknown(cls, missing_symbols: list[str]) -> GlobalMarketSnapshot:
        """Create snapshot with all regimes unknown due to missing data."""
        return cls(
            risk_regime="unknown",
            volatility_regime="unknown",
            dollar_pressure="unknown",
            rates_pressure="unknown",
            cross_asset_signal="unknown",
            timestamp=datetime.now(UTC).isoformat(),
            missing_data=missing_symbols,
            source_refs=[],
        )


class TickerConfig(BaseModel):
    """Configuration for a supported ticker."""

    symbol: str = Field(description="Ticker symbol (e.g., ^GSPC)")
    asset_class: AssetClass = Field(description="Asset class category")
    description: str = Field(description="Human-readable description")
    yfinance_supported: bool = Field(default=True, description="Available via yfinance")
    alpha_vantage_supported: bool = Field(default=True, description="Available via Alpha Vantage")


# Supported tickers configuration
SUPPORTED_TICKERS: list[TickerConfig] = [
    # US Equities
    TickerConfig(
        symbol="^GSPC",
        asset_class="equity",
        description="S&P 500 Index",
        yfinance_supported=True,
        alpha_vantage_supported=True,
    ),
    TickerConfig(
        symbol="^IXIC",
        asset_class="equity",
        description="Nasdaq Composite",
        yfinance_supported=True,
        alpha_vantage_supported=True,
    ),
    TickerConfig(
        symbol="^RUT",
        asset_class="equity",
        description="Russell 2000 Index",
        yfinance_supported=True,
        alpha_vantage_supported=True,
    ),
    # Volatility
    TickerConfig(
        symbol="^VIX",
        asset_class="volatility",
        description="CBOE Volatility Index",
        yfinance_supported=True,
        alpha_vantage_supported=True,
    ),
    # FX
    TickerConfig(
        symbol="DX-Y.NYB",
        asset_class="fx",
        description="US Dollar Index",
        yfinance_supported=True,
        alpha_vantage_supported=False,
    ),
    # Commodities
    TickerConfig(
        symbol="GC=F",
        asset_class="commodity",
        description="Gold Futures",
        yfinance_supported=True,
        alpha_vantage_supported=True,
    ),
    TickerConfig(
        symbol="CL=F",
        asset_class="commodity",
        description="Crude Oil Futures",
        yfinance_supported=True,
        alpha_vantage_supported=True,
    ),
    # Rates
    TickerConfig(
        symbol="^TNX",
        asset_class="rates",
        description="10-Year Treasury Yield",
        yfinance_supported=True,
        alpha_vantage_supported=False,
    ),
    TickerConfig(
        symbol="^FVX",
        asset_class="rates",
        description="5-Year Treasury Yield",
        yfinance_supported=True,
        alpha_vantage_supported=False,
    ),
]
