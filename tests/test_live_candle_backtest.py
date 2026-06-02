from decimal import Decimal

from hypertrade.backtest.service import BacktestService
from hypertrade.db import Database
from hypertrade.market.okx import parse_okx_candle


def test_backtest_service_can_use_okx_candles(monkeypatch) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = BacktestService(db)
    captured: dict[str, object] = {}

    def fake_fetch(inst_id: str, bar: str, limit: int):
        captured["inst_id"] = inst_id
        captured["bar"] = bar
        captured["limit"] = limit
        return [
            parse_okx_candle(
                [
                    str(1764200000000 + index * 3600000),
                    str(100 + index),
                    str(101 + index),
                    str(99 + index),
                    str(100 + index),
                    "1000",
                    "1000",
                    "100000",
                    "1",
                ]
            )
            for index in range(24)
        ]

    monkeypatch.setattr(service, "_fetch_okx_candles", fake_fetch)

    result = service.run(
        strategy_key="momentum_breakout_v1",
        use_live_candles=True,
        symbol="eth",
        bar="1h",
        candle_limit=24,
    )

    assert captured == {"inst_id": "ETH-USDT-SWAP", "bar": "1H", "limit": 24}
    assert result["status"] == "completed"
    assert result["report_json"]["data_source"] == "okx_rest_candles"
    assert result["report_json"]["inst_id"] == "ETH-USDT-SWAP"
    assert result["report_json"]["bar"] == "1H"
    assert result["report_json"]["candle_count"] == 24
    assert Decimal(result["metrics"]["total_return_pct"]) > Decimal("0")
