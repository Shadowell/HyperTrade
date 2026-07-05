"""Global market data collection service."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from hypertrade.global_market.analyzers import RegimeAnalyzer
from hypertrade.global_market.cache import GlobalMarketCache
from hypertrade.global_market.schemas import (
    SUPPORTED_TICKERS,
    GlobalMarketSnapshot,
)
from hypertrade.global_market.sources.alpha_vantage_source import AlphaVantageSource
from hypertrade.global_market.sources.yfinance_source import YFinanceSource

logger = logging.getLogger(__name__)


class GlobalMarketService:
    """Service for collecting and analyzing global market data.

    Uses yfinance as primary free data source with Alpha Vantage fallback.
    Collects cross-asset data (equities, volatility, FX, commodities, rates)
    and classifies market regimes for world model integration.

    Data source strategy:
    - Primary: yfinance (free, unlimited, no API key)
    - Fallback: Alpha Vantage (free tier: 25 requests/day, requires API key)
    - Cache: 5-minute TTL to reduce API calls
    """

    def __init__(self, *, cache_ttl_seconds: int = 300) -> None:
        """Initialize global market service with dual data sources.

        Args:
            cache_ttl_seconds: Cache TTL in seconds (default 300 = 5 minutes)
        """
        self.primary_source = YFinanceSource()
        self.fallback_source = AlphaVantageSource()
        self.analyzer = RegimeAnalyzer()
        self.cache = GlobalMarketCache(ttl_seconds=cache_ttl_seconds)

        # Check if Alpha Vantage is available
        has_av_key = bool(os.getenv("ALPHA_VANTAGE_API_KEY"))
        if has_av_key:
            logger.info("Alpha Vantage fallback enabled")
        else:
            logger.info(
                "Alpha Vantage fallback disabled (no API key). "
                "Only yfinance will be used."
            )

        logger.info(f"Global market cache enabled (TTL: {cache_ttl_seconds}s)")

    def get_snapshot(self, *, use_cache: bool = True) -> GlobalMarketSnapshot:
        """Get current global market state snapshot.

        Uses dual data source strategy with caching:
        1. Check cache (5-minute TTL)
        2. If cache miss, try yfinance (primary, unlimited)
        3. Fallback to Alpha Vantage for failed tickers (25/day limit)
        4. Cache result

        Args:
            use_cache: Whether to use cached data (default True)

        Returns:
            GlobalMarketSnapshot with regime classifications and ticker data
        """
        # Try cache first
        if use_cache:
            cached = self.cache.get()
            if cached:
                return GlobalMarketSnapshot(**cached)

        # Cache miss - fetch live data
        snapshot = self._fetch_live_snapshot()

        # Cache result
        if use_cache:
            self.cache.set(snapshot.model_dump())

        return snapshot

    def _fetch_live_snapshot(self) -> GlobalMarketSnapshot:
        """Fetch live global market snapshot (bypassing cache).

        Returns:
            GlobalMarketSnapshot with fresh data
        """
        # Collect all supported tickers
        symbols = [t.symbol for t in SUPPORTED_TICKERS]

        logger.info(f"Fetching {len(symbols)} global market tickers...")

        # Step 1: Try yfinance for all tickers
        tickers = self.primary_source.get_batch(symbols)

        # Step 2: Retry failed tickers with Alpha Vantage fallback
        failed_indices = [i for i, t in enumerate(tickers) if t.error is not None]

        if failed_indices:
            failed_symbols = [symbols[i] for i in failed_indices]
            logger.warning(
                f"{len(failed_indices)} tickers failed on yfinance: {failed_symbols}. "
                "Trying Alpha Vantage fallback..."
            )

            # Retry with Alpha Vantage
            fallback_results = self.fallback_source.get_batch(failed_symbols)

            # Replace failed tickers with fallback results
            for idx, fallback_result in zip(failed_indices, fallback_results, strict=True):
                if fallback_result.error is None:
                    logger.info(
                        f"Alpha Vantage fallback succeeded for {fallback_result.symbol}"
                    )
                    tickers[idx] = fallback_result
                else:
                    logger.warning(
                        f"Alpha Vantage fallback also failed for {fallback_result.symbol}: "
                        f"{fallback_result.error}"
                    )

        # Separate successful vs failed tickers
        successful = [t for t in tickers if t.error is None]
        failed = [t for t in tickers if t.error is not None]

        if failed:
            logger.warning(
                f"{len(failed)} tickers remain failed after fallback: "
                f"{[t.symbol for t in failed]}"
            )

        # If too many failures, return unknown snapshot
        if len(successful) < 3:
            logger.error(
                f"Insufficient data: only {len(successful)}/{len(symbols)} "
                "tickers succeeded"
            )
            return GlobalMarketSnapshot.create_unknown([t.symbol for t in failed])

        # Analyze regimes
        regimes = self.analyzer.analyze(tickers)

        # Build source references
        source_refs: list[dict[str, Any]] = [
            {
                "symbol": t.symbol,
                "source": t.source,
                "timestamp": t.timestamp,
                "price": t.price,
                "change_pct": t.change_pct,
            }
            for t in successful
        ]

        return GlobalMarketSnapshot(
            risk_regime=regimes["risk_regime"],
            volatility_regime=regimes["volatility_regime"],
            dollar_pressure=regimes["dollar_pressure"],
            rates_pressure=regimes["rates_pressure"],
            cross_asset_signal=regimes["cross_asset_signal"],
            tickers=tickers,
            timestamp=datetime.now(UTC).isoformat(),
            missing_data=[t.symbol for t in failed],
            source_refs=source_refs,
        )

    def get_supported_tickers(self) -> list[dict[str, Any]]:
        """Get list of supported ticker configurations.

        Returns:
            List of ticker config dicts
        """
        return [t.model_dump() for t in SUPPORTED_TICKERS]
