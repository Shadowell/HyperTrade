import hashlib
import json
from datetime import UTC, datetime

import pytest
from hypertrade.backtest.remote import RemoteKlineProvider


def seal(page):
    page["content_sha256"] = hashlib.sha256(
        json.dumps(
            page, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()
    return page


class Client:
    def __init__(self, mode="ok"):
        self.calls = []
        self.mode = mode

    def market_history_page(self, **params):
        self.calls.append(params)
        upper = params.get("end_ms", 5999 * 60000)
        if upper is None:
            upper = 5999 * 60000
        n = params["limit"]
        if self.mode == "stale":
            upper -= 600000
        rows = [
            {"timestamp": t, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1}
            for t in range(upper - (n - 1) * 60000, upper + 1, 60000)
        ]
        if self.mode == "gap":
            rows.pop(n // 2)
        if self.mode == "bad_price":
            rows[0]["close"] = -1
        page = seal(
            {
                "version": "market_history_page.v1",
                "exchange": "okx",
                "symbol": "BTC/USDT:USDT",
                "timeframe": "1m",
                "as_of_ms": 6000 * 60000,
                "candles": rows,
                "next_end_ms": rows[0]["timestamp"] - 60000,
            }
        )
        if self.mode == "tamper":
            page["candles"][0]["close"] = 900
        if self.mode == "identity":
            page.pop("content_sha256")
            page["symbol"] = "ETH/USDT:USDT"
            seal(page)
        return page


def test_remote_provider_pages_complete_closed_window_and_reuses_verified_cache(tmp_path):
    client = Client()
    provider = RemoteKlineProvider(client, cache_dir=tmp_path, now=lambda: 6000 * 60)
    rows = provider.read_candles(symbol="BTC-USDT-SWAP", bar="1m", limit=6000)
    assert len(rows) == 6000
    assert rows[0].timestamp == datetime.fromtimestamp(0, UTC).isoformat()
    assert rows[-1].timestamp == datetime.fromtimestamp(5999 * 60, UTC).isoformat()
    assert [c["limit"] for c in client.calls] == [5000, 1000]
    assert provider.read_candles(symbol="BTC-USDT-SWAP", bar="1m", limit=6000) == rows
    assert len(client.calls) == 2


@pytest.mark.parametrize("mode", ["stale", "gap", "bad_price", "tamper", "identity"])
def test_remote_provider_fails_closed_on_invalid_data(mode):
    with pytest.raises(ValueError):
        RemoteKlineProvider(Client(mode), now=lambda: 6000 * 60).read_candles(
            symbol="BTC-USDT-SWAP", bar="1m", limit=10
        )


def test_remote_provider_does_not_use_cache_from_previous_closed_bar(tmp_path):
    clock = [6000 * 60]
    client = Client()
    provider = RemoteKlineProvider(client, cache_dir=tmp_path, now=lambda: clock[0])
    provider.read_candles(symbol="BTC-USDT-SWAP", bar="1m", limit=10)
    clock[0] += 600
    with pytest.raises(ValueError):
        provider.read_candles(symbol="BTC-USDT-SWAP", bar="1m", limit=10)
    assert len(client.calls) == 2


def test_remote_provider_accepts_real_daily_open_offset():
    day, hour = 86400000, 3600000

    class OffsetClient:
        def market_history_page(self, **params):
            rows = [
                {
                    "timestamp": d * day + 16 * hour,
                    "open": 10,
                    "high": 12,
                    "low": 9,
                    "close": 11,
                    "volume": 1,
                }
                for d in (6, 7, 8)
            ]
            return seal(
                {
                    "version": "market_history_page.v1",
                    "exchange": "okx",
                    "symbol": "BTC/USDT:USDT",
                    "timeframe": "1d",
                    "as_of_ms": params["as_of_ms"],
                    "candles": rows,
                    "next_end_ms": 5 * day + 16 * hour,
                }
            )

    rows = RemoteKlineProvider(
        OffsetClient(), now=lambda: (10 * day + 12 * hour) / 1000
    ).read_candles(symbol="BTC-USDT-SWAP", bar="1d", limit=3)
    assert len(rows) == 3
    assert (
        rows[-1].timestamp == datetime.fromtimestamp((8 * day + 16 * hour) / 1000, UTC).isoformat()
    )


def test_adapter_preflights_once_and_keeps_all_page_receipts(tmp_path, monkeypatch):
    from pathlib import Path

    from hypertrade.bitpro.mcp import BitProToolAdapter

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    calls = []

    class Transport:
        base_url, auth_header, auth_token = "http://fixture-history", "test", "test-only"

        def call_tool(self, name, params):
            calls.append(name)
            if name == "bitpro_capabilities":
                return {"contract_version": "bitpro-mcp-v1"}
            if name == "bitpro_health":
                return {"status": "healthy"}
            assert name == "market_history_page"
            n, end = params["limit"], params["end_ms"]
            rows = [
                {"timestamp": t, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1}
                for t in range(end - (n - 1) * 60000, end + 1, 60000)
            ]
            return seal(
                {
                    "version": "market_history_page.v1",
                    "exchange": params["exchange"],
                    "symbol": params["symbol"],
                    "timeframe": params["timeframe"],
                    "as_of_ms": params["as_of_ms"],
                    "candles": rows,
                    "next_end_ms": rows[0]["timestamp"] - 60000,
                }
            )

    adapter = BitProToolAdapter(Transport())
    assert len(adapter.fetch_candles(symbol="BTC-USDT-SWAP", timeframe="1m", limit=5001)) == 5001
    assert calls == [
        "bitpro_capabilities",
        "bitpro_health",
        "market_history_page",
        "market_history_page",
    ]
    assert [entry["tool"] for entry in adapter.last_tool_calls] == calls
