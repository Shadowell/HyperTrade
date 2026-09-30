"""Remote, bounded K-line reads with verified, short-lived page caching."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from hypertrade.strategy.sdk import Candle


class KlineDataProvider(Protocol):
    def read_candles(
        self, *, symbol: str, bar: str, limit: int, exchange: str = "okx"
    ) -> list[Candle]: ...


class HistoryClient(Protocol):
    def market_history_page(self, **parameters: Any) -> dict[str, Any]: ...


class RemoteKlineProvider:
    def __init__(
        self,
        client: HistoryClient,
        *,
        cache_dir: Path | None = None,
        now: Callable[[], float] = time.time,
        cache_namespace: str = "",
    ) -> None:
        self.client = client
        self.cache_dir = cache_dir
        self.now = now
        self.cache_namespace = cache_namespace

    def _page(self, params: dict[str, Any]) -> dict[str, Any]:
        key = hashlib.sha256(
            json.dumps([self.cache_namespace, params], sort_keys=True).encode()
        ).hexdigest()
        path = self.cache_dir / f"{key}.json" if self.cache_dir else None
        if path and path.exists():
            try:
                saved = json.loads(path.read_text())
                if 0 <= self.now() - saved["cached_at"] < 60:
                    self._verify(saved["page"])
                    return dict(saved["page"])
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Bad/expired cache is never a fallback when the source fails.
        page = self.client.market_history_page(**params)
        self._verify(page)
        if path:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as tmp:
                    json.dump({"cached_at": self.now(), "page": page}, tmp, allow_nan=False)
                    temporary = Path(tmp.name)
                temporary.replace(path)
                managed = [
                    item
                    for item in path.parent.glob("*.json")
                    if re.fullmatch(r"[0-9a-f]{64}\.json", item.name)
                ]
                for expired in sorted(managed, key=lambda item: item.stat().st_mtime)[:-256]:
                    expired.unlink(missing_ok=True)
            except OSError:
                pass  # Cache is optional; the verified remote response is sufficient.
        return page

    @staticmethod
    def _verify(page: dict[str, Any]) -> None:
        if not isinstance(page, dict) or page.get("version") != "market_history_page.v1":
            raise ValueError("history_page_contract_mismatch")
        body = {key: value for key, value in page.items() if key != "content_sha256"}
        digest = hashlib.sha256(
            json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ).encode()
        ).hexdigest()
        if digest != page.get("content_sha256"):
            raise ValueError("history_page_hash_mismatch")

    def read_candles(
        self, *, symbol: str, bar: str, limit: int, exchange: str = "okx"
    ) -> list[Candle]:
        from hypertrade.bitpro.mcp import _normalize_bitpro_symbol, _normalize_bitpro_timeframe

        if isinstance(limit, bool) or not 1 <= limit <= 20000:
            raise ValueError("history_limit_outside_1_20000")
        timeframe = _normalize_bitpro_timeframe(bar)
        if not re.fullmatch(r"(?:1|3|5|15|30)m|(?:1|2|4|6|8|12)h|1d", timeframe):
            raise ValueError("history_timeframe_unsupported")
        symbol = _normalize_bitpro_symbol(symbol)
        period = int(timeframe[:-1]) * {"m": 60000, "h": 3600000, "d": 86400000}[timeframe[-1]]
        anchor = int(self.now() * 1000) // 60000 * 60000
        upper = anchor - period
        result: list[Candle] = []
        while len(result) < limit:
            size = min(5000, limit - len(result))
            params = {
                "symbol": symbol,
                "exchange": exchange,
                "timeframe": timeframe,
                "limit": size,
                "as_of_ms": anchor,
                "end_ms": upper,
            }
            page = self._page(params)
            if any(
                page.get(key) != params[key]
                for key in ("symbol", "exchange", "timeframe", "as_of_ms")
            ):
                raise ValueError("history_page_identity_mismatch")
            rows = page.get("candles")
            if not isinstance(rows, list) or len(rows) != size:
                raise ValueError("history_window_incomplete")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("history_invalid_row")
            latest = rows[-1].get("timestamp")
            if (
                isinstance(latest, bool)
                or not isinstance(latest, int)
                or not upper - period < latest <= upper
                or (result and latest != upper)
            ):
                raise ValueError("history_window_stale_or_discontinuous")
            batch = []
            for index, row in enumerate(rows):
                expected = latest - (size - 1 - index) * period
                if row.get("timestamp") != expected:
                    raise ValueError("history_window_stale_or_discontinuous")
                try:
                    prices = {
                        key: Decimal(str(row[key]))
                        for key in ("open", "high", "low", "close", "volume")
                    }
                except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
                    raise ValueError("history_invalid_values") from exc
                if not all(value.is_finite() for value in prices.values()) or prices["volume"] < 0:
                    raise ValueError("history_invalid_values")
                if (
                    not 0
                    < prices["low"]
                    <= min(prices["open"], prices["close"])
                    <= max(prices["open"], prices["close"])
                    <= prices["high"]
                ):
                    raise ValueError("history_invalid_ohlc")
                batch.append(
                    Candle(
                        timestamp=datetime.fromtimestamp(expected / 1000, UTC).isoformat(), **prices
                    )
                )
            result = batch + result
            upper = latest - size * period
            if len(result) < limit and page.get("next_end_ms") != upper:
                raise ValueError("history_pagination_cursor_mismatch")
        return result
