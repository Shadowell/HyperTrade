"""Tests for global market data sources."""

from unittest.mock import patch

import pandas as pd
from hypertrade.global_market.sources.yfinance_source import YFinanceSource


class TestYFinanceSource:
    """Test yfinance data source adapter."""

    def test_get_ticker_success(self):
        """Test successful ticker fetch."""
        source = YFinanceSource(retry_attempts=1)

        # Mock yfinance Ticker and history
        mock_hist = pd.DataFrame(
            {
                "Close": [4500.0, 4550.0],
                "Volume": [1000000, 1100000],
            },
            index=[
                pd.Timestamp("2024-01-01"),
                pd.Timestamp("2024-01-02"),
            ],
        )

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = mock_hist

            quote = source.get_ticker("^GSPC")

            assert quote.symbol == "^GSPC"
            assert quote.price == 4550.0
            assert abs(quote.change_pct - 1.11) < 0.01  # (4550-4500)/4500 * 100
            assert quote.source == "yfinance"
            assert quote.error is None

    def test_get_ticker_no_data(self):
        """Test ticker with no data."""
        source = YFinanceSource(retry_attempts=1)

        # Mock empty history
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = pd.DataFrame()

            quote = source.get_ticker("^INVALID")

            assert quote.symbol == "^INVALID"
            assert quote.error == "no_data"
            assert quote.price is None

    def test_get_ticker_with_retry(self):
        """Test retry logic on transient errors."""
        source = YFinanceSource(retry_attempts=2, retry_delay=0.1)

        mock_hist = pd.DataFrame(
            {
                "Close": [100.0, 101.0],
                "Volume": [1000, 1100],
            },
            index=[
                pd.Timestamp("2024-01-01"),
                pd.Timestamp("2024-01-02"),
            ],
        )

        with patch("yfinance.Ticker") as mock_ticker:
            # First call fails, second succeeds
            mock_ticker.return_value.history.side_effect = [
                Exception("Transient error"),
                mock_hist,
            ]

            with patch("time.sleep"):  # Skip actual sleep
                quote = source.get_ticker("^VIX")

            assert quote.price == 101.0
            assert quote.error is None

    def test_get_ticker_max_retries_exceeded(self):
        """Test failure after max retries."""
        source = YFinanceSource(retry_attempts=2, retry_delay=0.1)

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.side_effect = Exception("Persistent error")

            with patch("time.sleep"):
                quote = source.get_ticker("^GSPC")

            assert quote.error is not None
            assert "Persistent error" in quote.error

    def test_get_batch(self):
        """Test batch ticker fetch."""
        source = YFinanceSource(retry_attempts=1)

        mock_hist = pd.DataFrame(
            {
                "Close": [4500.0, 4550.0],
                "Volume": [1000000, 1100000],
            },
            index=[
                pd.Timestamp("2024-01-01"),
                pd.Timestamp("2024-01-02"),
            ],
        )

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.history.return_value = mock_hist

            quotes = source.get_batch(["^GSPC", "^IXIC", "^VIX"])

            assert len(quotes) == 3
            assert all(q.symbol in ["^GSPC", "^IXIC", "^VIX"] for q in quotes)
            assert all(q.price == 4550.0 for q in quotes if q.error is None)
