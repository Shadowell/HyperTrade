"""Alpha Vantage data source adapter - free tier fallback."""

from __future__ import annotations

import logging
import os
import time

import requests

from hypertrade.global_market.schemas import TickerQuote

logger = logging.getLogger(__name__)


class AlphaVantageRateLimitError(Exception):
    """Raised when Alpha Vantage rate limit is hit."""

    pass


class AlphaVantageSource:
    """Free Alpha Vantage data source (25 requests/day).

    Alpha Vantage provides free market data with rate limits:
    - Free tier: 25 requests/day, 5 requests/minute
    - Requires API key (free registration)

    Used as fallback when yfinance fails.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        retry_attempts: int = 2,
        retry_delay: float = 2.0,
    ):
        """Initialize Alpha Vantage source.

        Args:
            api_key: Alpha Vantage API key. If None, reads from ALPHA_VANTAGE_API_KEY env var.
            retry_attempts: Max retry attempts on transient errors
            retry_delay: Base delay in seconds for exponential backoff
        """
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_API_KEY")
        self.base_url = "https://www.alphavantage.co/query"
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay

        if not self.api_key:
            logger.warning(
                "Alpha Vantage API key not set. "
                "Get free key at https://www.alphavantage.co/support/#api-key"
            )

    def get_ticker(self, symbol: str) -> TickerQuote:
        """Fetch latest quote for a ticker symbol.

        Args:
            symbol: Ticker symbol (e.g., IBM, MSFT)
                   Note: Alpha Vantage doesn't support Yahoo-style symbols like ^GSPC

        Returns:
            TickerQuote with price/change data or error message
        """
        if not self.api_key:
            return TickerQuote(
                symbol=symbol,
                source="alpha_vantage",
                error="no_api_key",
            )

        # Convert Yahoo Finance symbols to Alpha Vantage compatible
        av_symbol = self._convert_symbol(symbol)
        if av_symbol is None:
            return TickerQuote(
                symbol=symbol,
                source="alpha_vantage",
                error="symbol_not_supported",
            )

        for attempt in range(self.retry_attempts):
            try:
                params = {
                    "function": "GLOBAL_QUOTE",
                    "symbol": av_symbol,
                    "apikey": self.api_key,
                }

                response = requests.get(
                    self.base_url,
                    params=params,
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                # Check for rate limit
                if "Note" in data:
                    error_msg = data.get("Note", "")
                    if "rate limit" in error_msg.lower() or "api call" in error_msg.lower():
                        raise AlphaVantageRateLimitError(error_msg)

                if "Information" in data:
                    error_msg = data.get("Information", "")
                    if "rate limit" in error_msg.lower() or "api key" in error_msg.lower():
                        raise AlphaVantageRateLimitError(error_msg)

                # Parse quote data
                quote = data.get("Global Quote", {})
                if not quote:
                    return TickerQuote(
                        symbol=symbol,
                        source="alpha_vantage",
                        error="no_data",
                    )

                price_str = quote.get("05. price", "0")
                change_pct_str = quote.get("10. change percent", "0%").rstrip("%")
                volume_str = quote.get("06. volume", "0")
                trading_day = quote.get("07. latest trading day")

                return TickerQuote(
                    symbol=symbol,
                    price=float(price_str) if price_str else None,
                    change_pct=float(change_pct_str) if change_pct_str else None,
                    volume=int(volume_str) if volume_str and volume_str != "0" else None,
                    timestamp=trading_day,
                    source="alpha_vantage",
                )

            except AlphaVantageRateLimitError as e:
                logger.warning(f"Alpha Vantage rate limit hit: {e}")
                return TickerQuote(
                    symbol=symbol,
                    source="alpha_vantage",
                    error="rate_limit",
                )

            except Exception as e:
                if attempt < self.retry_attempts - 1:
                    delay = self.retry_delay * (2**attempt)
                    logger.warning(
                        f"Alpha Vantage error for {symbol} "
                        f"(attempt {attempt + 1}/{self.retry_attempts}): {e}. "
                        f"Retrying in {delay:.0f}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        f"Alpha Vantage failed for {symbol} "
                        f"after {self.retry_attempts} attempts: {e}"
                    )
                    return TickerQuote(
                        symbol=symbol,
                        source="alpha_vantage",
                        error=str(e),
                    )

        # Should not reach here, but safety fallback
        return TickerQuote(
            symbol=symbol,
            source="alpha_vantage",
            error="max_retries_exceeded",
        )

    def _convert_symbol(self, yahoo_symbol: str) -> str | None:
        """Convert Yahoo Finance symbol to Alpha Vantage symbol.

        Alpha Vantage uses different symbols for indices and futures.

        Args:
            yahoo_symbol: Yahoo Finance symbol (e.g., ^GSPC, GC=F)

        Returns:
            Alpha Vantage symbol or None if not supported
        """
        # Map Yahoo Finance symbols to Alpha Vantage equivalents
        symbol_map: dict[str, str | None] = {
            # Indices - Alpha Vantage doesn't support index quotes directly
            "^GSPC": None,  # S&P 500 - not available via GLOBAL_QUOTE
            "^IXIC": None,  # Nasdaq - not available
            "^RUT": None,  # Russell 2000 - not available
            "^VIX": None,  # VIX - not available
            # FX - Alpha Vantage uses different endpoint
            "DX-Y.NYB": None,  # Dollar Index - not in GLOBAL_QUOTE
            # Futures - Alpha Vantage doesn't support futures quotes
            "GC=F": None,  # Gold futures - not available
            "CL=F": None,  # Oil futures - not available
            # Bonds - Alpha Vantage doesn't support bond quotes
            "^TNX": None,  # 10Y Treasury - not available
            "^FVX": None,  # 5Y Treasury - not available
        }

        # Check if symbol is in map
        if yahoo_symbol in symbol_map:
            return symbol_map[yahoo_symbol]

        # For regular stocks, use as-is
        if not yahoo_symbol.startswith("^") and "=" not in yahoo_symbol:
            return yahoo_symbol

        # Unknown format
        return None

    def get_batch(self, symbols: list[str]) -> list[TickerQuote]:
        """Fetch quotes for multiple symbols sequentially.

        Note: Alpha Vantage free tier has strict rate limits (5/minute).
        This method respects the limits with delays between requests.

        Args:
            symbols: List of ticker symbols

        Returns:
            List of TickerQuote objects
        """
        results = []
        for i, symbol in enumerate(symbols):
            result = self.get_ticker(symbol)
            results.append(result)

            # Rate limit: 5 requests/minute for free tier
            # Add delay between requests (except last one)
            if i < len(symbols) - 1 and self.api_key:
                time.sleep(12)  # 60s / 5 requests = 12s per request

        return results
