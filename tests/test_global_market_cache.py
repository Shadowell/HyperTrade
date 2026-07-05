"""Tests for global market cache."""

import time

from hypertrade.global_market.cache import GlobalMarketCache


class TestGlobalMarketCache:
    """Test global market data caching."""

    def test_cache_miss_on_empty(self):
        """Test cache returns None when empty."""
        cache = GlobalMarketCache(ttl_seconds=300)

        assert cache.get() is None
        assert cache.get_age() is None

    def test_cache_hit_within_ttl(self):
        """Test cache returns data within TTL."""
        cache = GlobalMarketCache(ttl_seconds=300)

        data = {"risk_regime": "risk_on", "timestamp": "2024-01-01"}
        cache.set(data)

        # Should hit cache
        cached = cache.get()
        assert cached == data
        assert cache.get_age() is not None
        assert cache.get_age() < 1  # Just set, age < 1 second

    def test_cache_expires_after_ttl(self):
        """Test cache expires after TTL."""
        cache = GlobalMarketCache(ttl_seconds=1)  # 1 second TTL

        data = {"risk_regime": "risk_on"}
        cache.set(data)

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        cached = cache.get()
        assert cached is None

    def test_cache_clear(self):
        """Test cache can be manually cleared."""
        cache = GlobalMarketCache(ttl_seconds=300)

        data = {"risk_regime": "risk_on"}
        cache.set(data)

        # Clear cache
        cache.clear()

        # Should be empty
        assert cache.get() is None
        assert cache.get_age() is None

    def test_cache_age(self):
        """Test cache age tracking."""
        cache = GlobalMarketCache(ttl_seconds=300)

        # Empty cache has no age
        assert cache.get_age() is None

        # Set data
        cache.set({"test": "data"})
        age1 = cache.get_age()
        assert age1 is not None
        assert age1 >= 0

        # Age increases over time
        time.sleep(0.1)
        age2 = cache.get_age()
        assert age2 > age1
