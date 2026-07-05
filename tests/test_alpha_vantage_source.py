"""Tests for Alpha Vantage data source."""

from unittest.mock import patch

from hypertrade.global_market.sources.alpha_vantage_source import (
    AlphaVantageSource,
)


class TestAlphaVantageSource:
    """Test Alpha Vantage data source adapter."""

    def test_no_api_key(self):
        """Test behavior when API key is not set."""
        source = AlphaVantageSource(api_key=None)

        quote = source.get_ticker("IBM")

        assert quote.symbol == "IBM"
        assert quote.error == "no_api_key"
        assert quote.source == "alpha_vantage"

    def test_symbol_conversion_indices_not_supported(self):
        """Test that index symbols are not supported."""
        source = AlphaVantageSource(api_key="test_key")

        # Indices not supported in Alpha Vantage GLOBAL_QUOTE
        assert source._convert_symbol("^GSPC") is None
        assert source._convert_symbol("^VIX") is None
        assert source._convert_symbol("^IXIC") is None

    def test_symbol_conversion_futures_not_supported(self):
        """Test that futures symbols are not supported."""
        source = AlphaVantageSource(api_key="test_key")

        # Futures not supported
        assert source._convert_symbol("GC=F") is None
        assert source._convert_symbol("CL=F") is None

    def test_symbol_conversion_regular_stocks(self):
        """Test that regular stock symbols pass through."""
        source = AlphaVantageSource(api_key="test_key")

        # Regular stocks work
        assert source._convert_symbol("IBM") == "IBM"
        assert source._convert_symbol("MSFT") == "MSFT"

    def test_get_ticker_success(self):
        """Test successful ticker fetch."""
        source = AlphaVantageSource(api_key="test_key", retry_attempts=1)

        mock_response = {
            "Global Quote": {
                "01. symbol": "IBM",
                "05. price": "150.25",
                "10. change percent": "1.25%",
                "06. volume": "5000000",
                "07. latest trading day": "2024-01-02",
            }
        }

        with patch("requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            quote = source.get_ticker("IBM")

            assert quote.symbol == "IBM"
            assert quote.price == 150.25
            assert quote.change_pct == 1.25
            assert quote.volume == 5000000
            assert quote.timestamp == "2024-01-02"
            assert quote.source == "alpha_vantage"
            assert quote.error is None

    def test_get_ticker_rate_limit(self):
        """Test rate limit handling."""
        source = AlphaVantageSource(api_key="test_key", retry_attempts=1)

        mock_response = {
            "Note": "Thank you for using Alpha Vantage! Our standard API call "
            "frequency is 5 calls per minute and 25 calls per day."
        }

        with patch("requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            quote = source.get_ticker("IBM")

            assert quote.symbol == "IBM"
            assert quote.error == "rate_limit"
            assert quote.source == "alpha_vantage"

    def test_get_ticker_no_data(self):
        """Test when API returns no quote data."""
        source = AlphaVantageSource(api_key="test_key", retry_attempts=1)

        mock_response = {"Global Quote": {}}

        with patch("requests.get") as mock_get:
            mock_get.return_value.json.return_value = mock_response
            mock_get.return_value.raise_for_status.return_value = None

            quote = source.get_ticker("INVALID")

            assert quote.symbol == "INVALID"
            assert quote.error == "no_data"
            assert quote.source == "alpha_vantage"

    def test_get_ticker_unsupported_symbol(self):
        """Test unsupported symbol (e.g., index)."""
        source = AlphaVantageSource(api_key="test_key")

        quote = source.get_ticker("^GSPC")

        assert quote.symbol == "^GSPC"
        assert quote.error == "symbol_not_supported"
        assert quote.source == "alpha_vantage"

    def test_get_ticker_with_retry(self):
        """Test retry logic on transient errors."""
        source = AlphaVantageSource(api_key="test_key", retry_attempts=2, retry_delay=0.1)

        mock_success = {
            "Global Quote": {
                "05. price": "100.0",
                "10. change percent": "0.5%",
                "07. latest trading day": "2024-01-02",
            }
        }

        with patch("requests.get") as mock_get:
            # First call fails, second succeeds
            mock_get.return_value.json.side_effect = [
                Exception("Transient error"),
                mock_success,
            ]
            mock_get.return_value.raise_for_status.return_value = None

            with patch("time.sleep"):  # Skip actual sleep
                quote = source.get_ticker("IBM")

            # Should eventually succeed
            assert quote.price == 100.0
            assert quote.error is None
