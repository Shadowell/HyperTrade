from __future__ import annotations

import sqlite3
from decimal import Decimal

from hypertrade.backtest.bitpro import BitProKlineArchive
from hypertrade.backtest.service import BacktestService
from hypertrade.config import Settings
from hypertrade.db import Database


def test_bitpro_archive_reads_timeframe_table(tmp_path) -> None:
    db_path = tmp_path / "bitpro.db"
    _seed_bitpro_kline_table(db_path, table="kline_1h", symbol="ETH/USDT:USDT")

    candles = BitProKlineArchive(db_path).read_candles(
        symbol="ETH",
        bar="1H",
        limit=24,
    )

    assert len(candles) == 24
    assert candles[0].timestamp == "2026-06-01T00:00:00+00:00"
    assert candles[0].open == Decimal("100")
    assert candles[-1].close == Decimal("123")


def test_backtest_service_can_use_bitpro_archive_candles(tmp_path) -> None:
    bitpro_db = tmp_path / "bitpro.db"
    _seed_bitpro_kline_table(bitpro_db, table="kline_1h", symbol="ETH/USDT:USDT")
    db = Database("sqlite:///:memory:")
    db.create_all()

    result = BacktestService(
        db,
        settings=Settings(BITPRO_SQLITE_PATH=bitpro_db),
    ).run(
        strategy_key="momentum_breakout_v1",
        candle_source="bitpro",
        symbol="ETH",
        bar="1H",
        candle_limit=24,
    )

    assert result["status"] == "completed"
    assert result["report_json"]["data_source"] == "bitpro_sqlite_candles"
    assert result["report_json"]["inst_id"] == "ETH-USDT-SWAP"
    assert result["report_json"]["bar"] == "1H"
    assert result["report_json"]["candle_count"] == 24


def _seed_bitpro_kline_table(db_path, *, table: str, symbol: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"""
            CREATE TABLE {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exchange TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                quote_volume REAL,
                UNIQUE(exchange, symbol, timestamp)
            )
            """
        )
        base_ts = 1780272000000
        rows = [
            (
                "okx",
                symbol,
                base_ts + index * 3_600_000,
                100 + index,
                101 + index,
                99 + index,
                100 + index,
                1000 + index,
                100000 + index,
            )
            for index in range(24)
        ]
        connection.executemany(
            f"""
            INSERT INTO {table}
                (exchange, symbol, timestamp, open, high, low, close, volume, quote_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
