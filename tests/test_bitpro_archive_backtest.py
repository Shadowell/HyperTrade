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


def test_file_store_wins_over_the_stale_sqlite_remnant(tmp_path) -> None:
    """Production had 385 stale bars in `kline_1h` and 11128 live ones in the file store.

    Reading SQLite first shortened every evidence window without reporting anything, so
    the file store has to win whenever it holds the symbol.
    """
    db_path = tmp_path / "bitpro.db"
    _seed_bitpro_kline_table(db_path, table="kline_1h", symbol="ETH/USDT:USDT")
    _seed_kline_file_store(tmp_path / "klines", symbol_dir="ETH-USDT", bars=200)

    candles = BitProKlineArchive(db_path).read_candles(symbol="ETH", bar="1H", limit=500)

    assert len(candles) == 200
    assert candles[0].open == Decimal("500")


def test_file_store_limit_returns_the_newest_bars(tmp_path) -> None:
    db_path = tmp_path / "bitpro.db"
    _seed_kline_file_store(tmp_path / "klines", symbol_dir="ETH-USDT", bars=200)

    candles = BitProKlineArchive(db_path).read_candles(symbol="ETH", bar="1H", limit=50)

    assert len(candles) == 50
    assert candles[-1].close == Decimal("699")
    assert candles[0].close == Decimal("650")


def test_reads_parquet_partitions(tmp_path) -> None:
    """Parquet is the production format; CSV is only the store's fallback spelling."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    directory = tmp_path / "klines" / "okx" / "ETH-USDT" / "1h"
    directory.mkdir(parents=True)
    base_ts = 1780272000000
    table = pa.table(
        {
            "timestamp": [base_ts + index * 3_600_000 for index in range(30)],
            "open": [float(700 + index) for index in range(30)],
            "high": [float(701 + index) for index in range(30)],
            "low": [float(699 + index) for index in range(30)],
            "close": [float(700 + index) for index in range(30)],
            "volume": [float(10 + index) for index in range(30)],
            "quote_volume": [float(1000 + index) for index in range(30)],
        }
    )
    pq.write_table(table, directory / "202606.parquet")

    candles = BitProKlineArchive(tmp_path / "bitpro.db").read_candles(
        symbol="ETH-USDT-SWAP", bar="1H", limit=500
    )

    assert len(candles) == 30
    assert candles[0].open == Decimal("700.0")
    assert candles[-1].close == Decimal("729.0")


def test_sqlite_still_answers_when_the_symbol_has_no_file_store(tmp_path) -> None:
    db_path = tmp_path / "bitpro.db"
    _seed_bitpro_kline_table(db_path, table="kline_1h", symbol="ETH/USDT:USDT")
    _seed_kline_file_store(tmp_path / "klines", symbol_dir="BTC-USDT", bars=10)

    candles = BitProKlineArchive(db_path).read_candles(symbol="ETH", bar="1H", limit=24)

    assert len(candles) == 24
    assert candles[0].open == Decimal("100")


def _seed_kline_file_store(root, *, symbol_dir: str, bars: int) -> None:
    import csv as _csv

    directory = root / "okx" / symbol_dir / "1h"
    directory.mkdir(parents=True, exist_ok=True)
    base_ts = 1780272000000
    rows = [
        {
            "timestamp": base_ts + index * 3_600_000,
            "open": 500 + index,
            "high": 501 + index,
            "low": 499 + index,
            "close": 500 + index,
            "volume": 10 + index,
        }
        for index in range(bars)
    ]
    # Two partitions so the newest-first partition walk is exercised, not just one file.
    for name, chunk in (("202606", rows[: bars // 2]), ("202607", rows[bars // 2 :])):
        if not chunk:
            continue
        with (directory / f"{name}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = _csv.DictWriter(handle, fieldnames=list(chunk[0]))
            writer.writeheader()
            writer.writerows(chunk)


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
