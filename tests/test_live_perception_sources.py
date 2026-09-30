"""Unit tests for live perception news sources and resilience."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from hypertrade.market.news import (
    CryptoPanicNewsSource,
    OkxAnnouncementsSource,
    RssCryptoNewsSource,
    WhaleMovementSource,
    build_default_news_service,
    extract_symbols_from_text,
)

SAMPLE_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Cointelegraph RSS</title>
    <link>https://cointelegraph.com</link>
    <description>Bitcoin &amp; Ethereum News</description>
    <item>
      <title>Bitcoin surges above $95,000 as institutional demand grows</title>
      <link>https://cointelegraph.com/news/btc-surges-95k</link>
      <description>&lt;p&gt;BTC surges while ETH and SOL gain.&lt;/p&gt;</description>
      <pubDate>Wed, 30 Sep 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>SEC approves new Solana ETF framework</title>
      <link>https://cointelegraph.com/news/sol-etf-approved</link>
      <description>Regulatory approval gives SOL big momentum.</description>
      <pubDate>Wed, 30 Sep 2026 11:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

SAMPLE_CRYPTOPANIC_JSON = {
    "results": [
        {
            "id": 101,
            "title": "Ethereum L2 TVL breaches new record",
            "url": "https://cryptopanic.com/news/101",
            "published_at": "2026-09-30T12:15:00Z",
            "currencies": [{"code": "ETH", "title": "Ethereum"}],
            "domain": "coindesk.com",
            "votes": {"positive": 142, "negative": 5},
        },
        {
            "id": 102,
            "title": "Dogecoin foundation announces testnet upgrade",
            "url": "https://cryptopanic.com/news/102",
            "published_at": "2026-09-30T11:45:00Z",
            "currencies": [{"code": "DOGE", "title": "Dogecoin"}],
            "domain": "decrypt.co",
            "votes": {"positive": 55, "negative": 10},
        },
    ]
}

SAMPLE_OKX_ANNOUNCEMENTS_JSON = {
    "code": "0",
    "msg": "",
    "data": [
        {
            "details": [
                {
                    "title": "OKX to list SUI and PEPE perpetual swap contracts",
                    "link": "https://www.okx.com/help/sui-pepe-swap-listing",
                    "pTime": "1759233600000",
                    "annType": "listing",
                },
                {
                    "title": "Scheduled maintenance for BTC and ETH options matching engine",
                    "link": "https://www.okx.com/help/engine-maintenance",
                    "pTime": "1759230000000",
                    "annType": "maintenance",
                },
            ]
        }
    ],
}


def test_extract_symbols_from_text() -> None:
    symbols = extract_symbols_from_text("Bitcoin surges as Solana and ETH outperform DOGE")
    assert "BTC" in symbols
    assert "SOL" in symbols
    assert "ETH" in symbols
    assert "DOGE" in symbols


def test_rss_news_source_parsing() -> None:
    source = RssCryptoNewsSource(["https://mock-crypto.news/rss"])

    mock_resp = MagicMock()
    mock_resp.read.return_value = SAMPLE_RSS_XML
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        articles = source.fetch_latest(limit=10)

    assert len(articles) == 2
    art1 = articles[0]
    assert "Bitcoin surges" in art1.title
    assert "BTC" in art1.symbols
    assert "ETH" in art1.symbols
    assert "SOL" in art1.symbols
    assert art1.source == "mock-crypto"
    assert art1.published_at.year == 2026

    art2 = articles[1]
    assert "Solana" in art2.title
    assert "SOL" in art2.symbols


def test_rss_news_source_handles_network_failure() -> None:
    source = RssCryptoNewsSource(["https://invalid-non-existent-feed.xyz/rss"])
    with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
        articles = source.fetch_latest(limit=10)
    assert articles == []


def test_cryptopanic_news_source_parsing() -> None:
    source = CryptoPanicNewsSource(api_key="test_api_key")

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(SAMPLE_CRYPTOPANIC_JSON).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        articles = source.fetch_latest(limit=10)

    assert len(articles) == 2
    assert articles[0].title == "Ethereum L2 TVL breaches new record"
    assert "ETH" in articles[0].symbols
    assert articles[0].source == "cryptopanic"
    assert articles[0].metadata.get("votes", {}).get("positive") == 142

    assert "DOGE" in articles[1].symbols


def test_cryptopanic_disabled_without_api_key() -> None:
    source = CryptoPanicNewsSource(api_key="")
    assert source.fetch_latest() == []


def test_okx_announcements_parsing() -> None:
    source = OkxAnnouncementsSource()

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(SAMPLE_OKX_ANNOUNCEMENTS_JSON).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        articles = source.fetch_latest(limit=10)

    assert len(articles) == 2
    art1 = articles[0]
    assert "SUI and PEPE" in art1.title
    assert "SUI" in art1.symbols
    assert "PEPE" in art1.symbols
    assert art1.metadata.get("event_category") == "partnership_listing"


def test_whale_movement_source() -> None:
    source = WhaleMovementSource()
    alert = source.record_alert(
        symbol="BTC-USDT-SWAP",
        amount_usd=120_000_000,
        from_wallet="1AnBiTc...Whale",
        to_wallet="1Binance...Deposit",
        tx_hash="0xabcd1234",
    )
    assert alert.symbols == ["BTC"]
    assert alert.metadata.get("event_category") == "whale_movement"
    assert alert.metadata.get("urgency") == "breaking"
    assert len(source.fetch_latest()) == 1


def test_build_default_news_service_and_sync() -> None:
    svc = build_default_news_service(cryptopanic_key="sample_key", enable_external=True)
    assert len(svc._sources) >= 4

    whale_src = next(s for s in svc._sources if isinstance(s, WhaleMovementSource))
    whale_src.record_alert(
        symbol="ETH",
        amount_usd=60_000_000,
        from_wallet="0xabc",
        to_wallet="0xdef",
    )

    with patch("urllib.request.urlopen", side_effect=OSError("Offline")):
        added = svc.sync_sources()

    assert added >= 1
    latest = svc.get_latest(symbol="ETH")
    assert len(latest) >= 1
    assert "ETH" in latest[0].symbols
