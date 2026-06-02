from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from hypertrade.strategy.sdk import Candle


class BitProKlineArchive:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def read_candles(
        self,
        *,
        symbol: str,
        bar: str,
        limit: int,
        exchange: str = "okx",
    ) -> list[Candle]:
        if not self.db_path.exists():
            raise FileNotFoundError(str(self.db_path))
        table = _table_for_bar(bar)
        symbols = _bitpro_symbol_candidates(symbol)
        safe_limit = max(6, min(limit, 20_000))
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = _query_timeframe_table(
                connection,
                table=table,
                exchange=exchange,
                symbols=symbols,
                limit=safe_limit,
            )
            if not rows:
                rows = _query_history_table(
                    connection,
                    exchange=exchange,
                    symbols=symbols,
                    timeframe=_bitpro_timeframe(bar),
                    limit=safe_limit,
                )
        candles = [_row_to_candle(dict(row)) for row in rows]
        return sorted(candles, key=lambda candle: candle.timestamp)


def _query_timeframe_table(
    connection: sqlite3.Connection,
    *,
    table: str,
    exchange: str,
    symbols: list[str],
    limit: int,
) -> list[sqlite3.Row]:
    if not _table_exists(connection, table):
        return []
    placeholders = ",".join("?" for _ in symbols)
    return list(
        connection.execute(
            f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table}
            WHERE exchange = ? AND symbol IN ({placeholders})
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            [exchange, *symbols, limit],
        )
    )


def _query_history_table(
    connection: sqlite3.Connection,
    *,
    exchange: str,
    symbols: list[str],
    timeframe: str,
    limit: int,
) -> list[sqlite3.Row]:
    if not _table_exists(connection, "kline_history"):
        return []
    placeholders = ",".join("?" for _ in symbols)
    return list(
        connection.execute(
            f"""
            SELECT timestamp, open, high, low, close, volume
            FROM kline_history
            WHERE exchange = ? AND timeframe = ? AND symbol IN ({placeholders})
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            [exchange, timeframe, *symbols, limit],
        )
    )


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        [table],
    ).fetchone()
    return row is not None


def _row_to_candle(row: dict[str, Any]) -> Candle:
    timestamp = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=UTC).isoformat()
    return Candle(
        timestamp=timestamp,
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row["volume"])),
    )


def _table_for_bar(bar: str) -> str:
    return f"kline_{_bitpro_timeframe(bar)}"


def _bitpro_timeframe(bar: str) -> str:
    value = bar.strip()
    if not value:
        return "1h"
    if value.lower().endswith("h"):
        return f"{value[:-1]}h"
    if value.lower().endswith("d"):
        return f"{value[:-1]}d"
    return value.lower()


def _bitpro_symbol_candidates(symbol: str) -> list[str]:
    value = symbol.strip().upper().replace("_", "-")
    if not value:
        value = "BTC"
    if value.endswith("-SWAP"):
        value = value.removesuffix("-SWAP")
    if value.endswith("-USDT"):
        base = value.removesuffix("-USDT")
    elif "/" in value:
        base = value.split("/", 1)[0]
    else:
        base = value
    return [
        f"{base}/USDT:USDT",
        f"{base}/USDT",
        f"{base}-USDT-SWAP",
        f"{base}-USDT",
        base,
    ]
