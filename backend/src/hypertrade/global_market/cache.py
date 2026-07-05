"""In-memory cache for global market data with TTL."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class GlobalMarketCache:
    """Simple in-memory cache with TTL for global market snapshots.

    Reduces API calls to yfinance/Alpha Vantage by caching results
    for a configurable TTL (default 5 minutes).
    """

    def __init__(self, ttl_seconds: int = 300):
        """Initialize cache.

        Args:
            ttl_seconds: Time-to-live in seconds (default 300 = 5 minutes)
        """
        self.ttl_seconds = ttl_seconds
        self._cache: dict[str, Any] = {}
        self._cache_time: float | None = None

    def get(self) -> dict[str, Any] | None:
        """Get cached snapshot if not expired.

        Returns:
            Cached snapshot dict or None if expired/empty
        """
        if not self._cache or self._cache_time is None:
            return None

        age = time.time() - self._cache_time

        if age > self.ttl_seconds:
            logger.info(f"Cache expired (age: {age:.0f}s > TTL: {self.ttl_seconds}s)")
            self._cache = {}
            self._cache_time = None
            return None

        logger.info(f"Cache hit (age: {age:.0f}s, TTL: {self.ttl_seconds}s)")
        return self._cache

    def set(self, snapshot: dict[str, Any]) -> None:
        """Store snapshot in cache.

        Args:
            snapshot: Snapshot dict to cache
        """
        self._cache = snapshot
        self._cache_time = time.time()
        logger.info("Cache updated")

    def clear(self) -> None:
        """Clear cache."""
        self._cache = {}
        self._cache_time = None
        logger.info("Cache cleared")

    def get_age(self) -> float | None:
        """Get cache age in seconds.

        Returns:
            Age in seconds or None if cache is empty
        """
        if self._cache_time is None:
            return None
        return time.time() - self._cache_time
