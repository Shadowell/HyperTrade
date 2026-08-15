from __future__ import annotations

import csv
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from hypertrade.strategy.sdk import Candle

# BitPro migrated klines out of SQLite into month-partitioned files laid out as
# `{root}/{exchange}/{symbol}/{timeframe}/YYYYMM.parquet`. The `kline_*` tables were
# left behind and still answer queries, so reading SQLite first silently returned a
# stale remnant: on production `kline_1h` held 385 bars ending three months earlier
# while the file store held 11128 covering the same symbol to the current hour. Every
# ARC evidence verdict was therefore judged on a window too short to carry one.
_KLINE_STORE_DIRNAME = "klines"


class BitProKlineArchive:
    """Reads BitPro's kline archive: the file store first, SQLite only as fallback."""

    def __init__(self, db_path: str | Path, store_root: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.store_root = (
            Path(store_root) if store_root else self.db_path.parent / _KLINE_STORE_DIRNAME
        )

    def read_candles(
        self,
        *,
        symbol: str,
        bar: str,
        limit: int,
        exchange: str = "okx",
    ) -> list[Candle]:
        timeframe = _bitpro_timeframe(bar)
        symbols = _bitpro_symbol_candidates(symbol)
        safe_limit = max(6, min(limit, 20_000))

        rows = _read_file_store(
            root=self.store_root,
            exchange=exchange,
            symbols=symbols,
            timeframe=timeframe,
            limit=safe_limit,
        )
        if rows is None:
            if not self.db_path.exists():
                raise FileNotFoundError(str(self.db_path))
            with sqlite3.connect(self.db_path) as connection:
                connection.row_factory = sqlite3.Row
                found = _query_timeframe_table(
                    connection,
                    table=_table_for_bar(bar),
                    exchange=exchange,
                    symbols=symbols,
                    limit=safe_limit,
                )
                if not found:
                    found = _query_history_table(
                        connection,
                        exchange=exchange,
                        symbols=symbols,
                        timeframe=timeframe,
                        limit=safe_limit,
                    )
            rows = [dict(row) for row in found]

        candles = [_row_to_candle(row) for row in rows]
        candles.sort(key=lambda candle: candle.timestamp)
        return candles


def _read_file_store(
    *,
    root: Path,
    exchange: str,
    symbols: list[str],
    timeframe: str,
    limit: int,
) -> list[dict[str, Any]] | None:
    """Newest `limit` bars from the file store, or None when this symbol has no store.

    None means "not stored here, ask SQLite"; an empty list would mean "stored here and
    genuinely empty", and collapsing the two is what let a stale table stand in for a
    live archive.
    """
    partitions = _store_partitions(
        root=root, exchange=exchange, symbols=symbols, timeframe=timeframe
    )
    if not partitions:
        return None

    collected: list[dict[str, Any]] = []
    # Partition names are YYYYMM, so newest-first is plain reverse lexicographic order.
    for path in sorted(partitions, key=lambda item: item.name, reverse=True):
        collected.extend(_read_partition(path))
        if len(collected) >= limit:
            break
    collected.sort(key=lambda row: int(row["timestamp"]))
    return collected[-limit:]


def _store_partitions(
    *,
    root: Path,
    exchange: str,
    symbols: list[str],
    timeframe: str,
) -> list[Path]:
    if not root.is_dir():
        return []
    for candidate in _store_symbol_dirs(symbols):
        directory = root / exchange / candidate / timeframe
        if not directory.is_dir():
            continue
        files = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix in (".parquet", ".csv")
        ]
        if files:
            return files
    return []


def _store_symbol_dirs(symbols: list[str]) -> list[str]:
    """Directory spellings for the same instrument, e.g. `BTC/USDT:USDT` -> `BTC-USDT_USDT`."""
    seen: dict[str, None] = {}
    for symbol in symbols:
        seen.setdefault(symbol.replace("/", "-").replace(":", "_"), None)
    return list(seen)


def _read_partition(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:  # pragma: no cover - depends on the deployed image
        raise RuntimeError(
            f"BitPro stores klines at {path.parent} but pyarrow is unavailable, so the "
            "archive cannot be read. Refusing to fall back to the legacy SQLite tables: "
            "they are stale and would silently shorten every evidence window."
        ) from exc
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    rows: list[dict[str, Any]] = parquet.read_table(path, columns=columns).to_pylist()
    return rows


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
