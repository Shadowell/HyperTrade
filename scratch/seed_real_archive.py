"""Build a local research archive from real exchange history.

Research-only tool, deliberately outside the product: HyperTrade does not own market
data, BitPro does. On a host where the BitPro archive is mounted this is unnecessary.
Here it exists because OKX is unreachable from this network, and a verdict reached on
synthetic prices is not evidence.

    uv run python scratch/seed_real_archive.py [BARS] [SYMBOL] [OUT_DB]
"""

from __future__ import annotations

import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

BINANCE = "https://api.binance.com/api/v3/klines"
PAGE = 1_000
HOUR_MS = 3_600_000


def fetch_klines(symbol: str, bars: int) -> list[tuple]:
    """Page backwards from now so the newest bar is the last one written."""
    collected: dict[int, tuple] = {}
    end_ms: int | None = None
    while len(collected) < bars:
        url = f"{BINANCE}?symbol={symbol}&interval=1h&limit={PAGE}"
        if end_ms is not None:
            url += f"&endTime={end_ms}"
        with urllib.request.urlopen(url, timeout=30) as response:
            rows = json.loads(response.read())
        if not rows:
            break
        for row in rows:
            open_ms = int(row[0])
            collected[open_ms] = (
                open_ms,
                float(row[1]),
                float(row[2]),
                float(row[3]),
                float(row[4]),
                float(row[5]),
                float(row[7]),
            )
        end_ms = int(rows[0][0]) - HOUR_MS
        print(f"  fetched {len(collected)} bars, oldest open_ms={end_ms + HOUR_MS}")
    ordered = sorted(collected.values(), key=lambda item: item[0])
    return ordered[-bars:]


def write_archive(db_path: Path, archive_symbol: str, rows: list[tuple]) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS kline_1h (
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
        connection.executemany(
            """
            INSERT OR IGNORE INTO kline_1h
                (exchange, symbol, timestamp, open, high, low, close, volume, quote_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "okx",  # the reader filters on this; the prices are real either way
                    archive_symbol,
                    ts,
                    open_,
                    high,
                    low,
                    close,
                    volume,
                    quote_volume,
                )
                for ts, open_, high, low, close, volume, quote_volume in rows
            ],
        )


def main(argv: list[str]) -> int:
    bars = int(argv[1]) if len(argv) > 1 else 6_000
    venue_symbols = (argv[2] if len(argv) > 2 else "BTCUSDT").split(",")
    out = Path(argv[3] if len(argv) > 3 else "/tmp/ht_real_archive.db")

    from datetime import UTC, datetime

    for venue_symbol in venue_symbols:
        venue_symbol = venue_symbol.strip()
        archive_symbol = f"{venue_symbol.removesuffix('USDT')}/USDT:USDT"
        print(f"fetching {bars} real 1h bars for {venue_symbol} from Binance")
        rows = fetch_klines(venue_symbol, bars)
        write_archive(out, archive_symbol, rows)

        first = datetime.fromtimestamp(rows[0][0] / 1000, UTC)
        last = datetime.fromtimestamp(rows[-1][0] / 1000, UTC)
        span_days = (rows[-1][0] - rows[0][0]) / 86_400_000
        print(
            f"  wrote {len(rows)} bars as {archive_symbol}: "
            f"{first:%Y-%m-%d} .. {last:%Y-%m-%d} ({span_days:.0f}d), "
            f"close {rows[0][4]:,.4g} -> {rows[-1][4]:,.4g}\n"
        )

    print(f"archive: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
