"""Base protocol for global market data sources."""

from __future__ import annotations

from typing import Protocol

from hypertrade.global_market.schemas import TickerQuote


class GlobalMarketSource(Protocol):
    """Protocol for global market data sources."""

    def get_ticker(self, symbol: str) -> TickerQuote:
        """Fetch latest quote for a ticker symbol.

        Args:
            symbol: Ticker symbol (e.g., ^GSPC, ^VIX)

        Returns:
            TickerQuote with price, change, volume, timestamp, and source
        """
        ...

    def get_batch(self, symbols: list[str]) -> list[TickerQuote]:
        """Fetch quotes for multiple symbols.

        Default implementation calls get_ticker sequentially.
        Sources can override for parallel/batch fetching.

        Args:
            symbols: List of ticker symbols

        Returns:
            List of TickerQuote objects
        """
        return [self.get_ticker(symbol) for symbol in symbols]
