from decimal import Decimal

from hypertrade.market.okx import parse_okx_ticker


def test_parse_okx_ticker_normalizes_swap_payload():
    ticker = parse_okx_ticker(
        {
            "instType": "SWAP",
            "instId": "BTC-USDT-SWAP",
            "last": "68500.5",
            "volCcy24h": "18000.25",
            "vol24h": "25000",
            "sodUtc0": "67000",
            "ts": "1764200000000",
        }
    )

    assert ticker.inst_type == "SWAP"
    assert ticker.inst_id == "BTC-USDT-SWAP"
    assert ticker.last == Decimal("68500.5")
    assert ticker.volume_ccy_24h == Decimal("18000.25")
    assert ticker.change_utc0_pct == Decimal("2.239")
