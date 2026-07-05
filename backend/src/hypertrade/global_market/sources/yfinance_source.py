"""yfinance data source adapter - free, no API key required."""

from __future__ import annotations

import logging
import time

import yfinance as yf

from hypertrade.global_market.schemas import TickerQuote

logger = logging.getLogger(__name__)


class YFinanceSource:
    """Free global market data source using yfinance.

    yfinance is a free library that scrapes Yahoo Finance.
    - No API key required
    - No documented rate limits
    - Supports US equities, indices, FX, commodities, rates
    - May occasionally fail due to Yahoo Finance changes
    """

    def __init__(self, *, retry_attempts: int = 3, retry_delay: float = 2.0):
        """Initialize yfinance source.

        Args:
            retry_attempts: Max retry attempts on rate limit or transient errors
            retry_delay: Base delay in seconds for exponential backoff
        """
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay

    def get_ticker(self, symbol: str) -> TickerQuote:
        """Fetch latest quote for a ticker symbol.

        Args:
            symbol: Ticker symbol (e.g., ^GSPC, ^VIX, DX-Y.NYB)

        Returns:
            TickerQuote with price/change data or error message
        """
        for attempt in range(self.retry_attempts):
            try:
                ticker = yf.Ticker(symbol)

                # Get last 2 days of history to compute change
                hist = ticker.history(period="2d")

                if hist.empty:
                    return TickerQuote(
                        symbol=symbol,
                        source="yfinance",
                        error="no_data",
                    )

                latest = hist.iloc[-1]
                prior = hist.iloc[-2] if len(hist) > 1 else latest

                price = float(latest["Close"])
                change_pct = (
                    ((latest["Close"] - prior["Close"]) / prior["Close"] * 100)
                    if prior["Close"] != 0
                    else 0.0
                )

                return TickerQuote(
                    symbol=symbol,
                    price=price,
                    change_pct=round(change_pct, 2),
                    volume=int(latest["Volume"]) if latest["Volume"] > 0 else None,
                    timestamp=latest.name.isoformat(),
                    source="yfinance",
                )

            except Exception as e:
                if attempt < self.retry_attempts - 1:
                    delay = self.retry_delay * (2**attempt)
                    logger.warning(
                        f"yfinance error for {symbol} "
                        f"(attempt {attempt + 1}/{self.retry_attempts}): {e}. "
                        f"Retrying in {delay:.0f}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"yfinance failed for {symbol} after {self.retry_attempts} attempts: {e}"
                    )
                    return TickerQuote(
                        symbol=symbol,
                        source="yfinance",
                        error=str(e),
                    )

        # Should not reach here, but safety fallback
        return TickerQuote(
            symbol=symbol,
            source="yfinance",
            error="max_retries_exceeded",
        )

    def get_batch(self, symbols: list[str]) -> list[TickerQuote]:
        """Fetch quotes for multiple symbols sequentially.

        yfinance download() can fetch multiple symbols at once, but for
        reliability we fetch sequentially with per-symbol error handling.

        Args:
            symbols: List of ticker symbols

        Returns:
            List of TickerQuote objects
        """
        return [self.get_ticker(symbol) for symbol in symbols]
