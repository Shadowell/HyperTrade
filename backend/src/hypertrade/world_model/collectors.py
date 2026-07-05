"""Collector utilities for read-only WorldState assembly."""

from __future__ import annotations

import logging
from typing import Any

from hypertrade.global_market.service import GlobalMarketService

logger = logging.getLogger(__name__)

# Deprecated: replaced by live global market data
GLOBAL_MARKET_MISSING_DATA: list[str] = []


def collect_global_market() -> dict[str, Any]:
    """Collect cross-asset global market state.

    Replaces fixture data with live yfinance data.
    Returns regime classifications and ticker quotes.
    """
    try:
        service = GlobalMarketService()
        snapshot = service.get_snapshot()

        return {
            "risk_regime": snapshot.risk_regime,
            "volatility_regime": snapshot.volatility_regime,
            "dollar_pressure": snapshot.dollar_pressure,
            "rates_pressure": snapshot.rates_pressure,
            "cross_asset_signal": snapshot.cross_asset_signal,
            "tickers": [t.model_dump() for t in snapshot.tickers],
            "missing_data": snapshot.missing_data,
            "source_refs": snapshot.source_refs,
            "as_of": snapshot.timestamp,
        }
    except Exception as e:
        logger.error(f"Failed to collect global market data: {e}")
        # Return unknown state on failure to not block world model
        return {
            "risk_regime": "unknown",
            "volatility_regime": "unknown",
            "dollar_pressure": "unknown",
            "rates_pressure": "unknown",
            "cross_asset_signal": "unknown",
            "tickers": [],
            "missing_data": ["all"],
            "source_refs": [],
            "as_of": None,
            "error": str(e),
        }
