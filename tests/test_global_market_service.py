"""Tests for global market service."""

from unittest.mock import patch

from hypertrade.global_market.schemas import TickerQuote
from hypertrade.global_market.service import GlobalMarketService


class TestGlobalMarketService:
    """Test global market data collection service."""

    def test_get_snapshot_success(self):
        """Test successful snapshot with all tickers."""
        service = GlobalMarketService()

        # Mock successful ticker data
        mock_tickers = [
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
                symbol="CL=F", price=75, change_pct=0.3, source="yfinance", timestamp="2024-01-02"
            ),
            TickerQuote(
                symbol="^TNX", price=4.2, change_pct=0.1, source="yfinance", timestamp="2024-01-02"
            ),
            TickerQuote(
                symbol="^FVX", price=3.8, change_pct=0.05, source="yfinance", timestamp="2024-01-02"
            ),
        ]

        with patch.object(service.primary_source, "get_batch", return_value=mock_tickers):
            snapshot = service.get_snapshot()

            assert snapshot.risk_regime == "risk_on"
            assert snapshot.volatility_regime == "calm"
            assert len(snapshot.tickers) == 9
            assert len(snapshot.missing_data) == 0
            assert snapshot.timestamp is not None
        """Test successful snapshot with all tickers."""
        service = GlobalMarketService()

        # Mock successful ticker data
        mock_tickers = [
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
                symbol="CL=F", price=75, change_pct=0.3, source="yfinance", timestamp="2024-01-02"
            ),
            TickerQuote(
                symbol="^TNX", price=4.2, change_pct=0.1, source="yfinance", timestamp="2024-01-02"
            ),
            TickerQuote(
                symbol="^FVX", price=3.8, change_pct=0.05, source="yfinance", timestamp="2024-01-02"
            ),
        ]

        with patch.object(service.primary_source, "get_batch", return_value=mock_tickers):
            snapshot = service.get_snapshot()

            assert snapshot.risk_regime == "risk_on"
            assert snapshot.volatility_regime == "calm"
            assert len(snapshot.tickers) == 9
            assert len(snapshot.missing_data) == 0
            assert snapshot.timestamp is not None

    def test_get_snapshot_partial_failures(self):
        """Test snapshot with some ticker failures."""
        service = GlobalMarketService()

        mock_tickers = [
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
            TickerQuote(symbol="DX-Y.NYB", source="yfinance", error="no_data"),
            TickerQuote(
                symbol="GC=F",
                price=2050,
                change_pct=-0.5,
                source="yfinance",
                timestamp="2024-01-02",
            ),
            TickerQuote(symbol="CL=F", source="yfinance", error="timeout"),
            TickerQuote(
                symbol="^TNX", price=4.2, change_pct=0.1, source="yfinance", timestamp="2024-01-02"
            ),
            TickerQuote(
                symbol="^FVX", price=3.8, change_pct=0.05, source="yfinance", timestamp="2024-01-02"
            ),
        ]

        with patch.object(service.primary_source, "get_batch", return_value=mock_tickers):
            snapshot = service.get_snapshot()

            assert snapshot.risk_regime == "risk_on"
            assert len(snapshot.missing_data) == 2
            assert "DX-Y.NYB" in snapshot.missing_data
            assert "CL=F" in snapshot.missing_data
            assert len([t for t in snapshot.tickers if t.error is None]) == 7

    def test_get_snapshot_insufficient_data(self):
        """Test snapshot with too many failures."""
        service = GlobalMarketService()

        # Only 2 successful tickers (< 3 minimum)
        mock_tickers = [
            TickerQuote(
                symbol="^GSPC",
                price=4550,
                change_pct=1.2,
                source="yfinance",
                timestamp="2024-01-02",
            ),
            TickerQuote(
                symbol="^VIX",
                price=13.5,
                change_pct=-3.0,
                source="yfinance",
                timestamp="2024-01-02",
            ),
            TickerQuote(symbol="^IXIC", source="yfinance", error="no_data"),
            TickerQuote(symbol="^RUT", source="yfinance", error="no_data"),
            TickerQuote(symbol="DX-Y.NYB", source="yfinance", error="no_data"),
            TickerQuote(symbol="GC=F", source="yfinance", error="no_data"),
            TickerQuote(symbol="CL=F", source="yfinance", error="no_data"),
            TickerQuote(symbol="^TNX", source="yfinance", error="no_data"),
            TickerQuote(symbol="^FVX", source="yfinance", error="no_data"),
        ]

        with patch.object(service.primary_source, "get_batch", return_value=mock_tickers):
            snapshot = service.get_snapshot()

            assert snapshot.risk_regime == "unknown"
            assert snapshot.volatility_regime == "unknown"
            assert len(snapshot.missing_data) > 0

    def test_get_supported_tickers(self):
        """Test getting supported ticker list."""
        service = GlobalMarketService()

        tickers = service.get_supported_tickers()

        assert len(tickers) == 20  # Sprint 76: Expanded from 9 to 20
        assert any(t["symbol"] == "^GSPC" for t in tickers)
        assert any(t["symbol"] == "^VIX" for t in tickers)
        assert any(t["symbol"] == "^HSI" for t in tickers)  # Asia
        assert any(t["symbol"] == "^STOXX50E" for t in tickers)  # Europe
        assert any(t["asset_class"] == "equity" for t in tickers)
        assert any(t["asset_class"] == "volatility" for t in tickers)
