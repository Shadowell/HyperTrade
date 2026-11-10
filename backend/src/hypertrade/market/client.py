import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
import websockets

from hypertrade.config import Settings
from hypertrade.market.okx import OkxCandle, OkxTicker, parse_okx_candle, parse_okx_ticker
from hypertrade.market.repository import MarketRepository

logger = logging.getLogger("hypertrade.market")

# `(component, exception)`: where the worker plugs in its runtime-error journal.
ErrorHook = Callable[[str, Exception], Awaitable[None]]


async def _report(on_error: ErrorHook | None, component: str, exc: Exception) -> None:
    """Hand a failure to the caller's journal; the hook itself must never break ingestion."""
    if on_error is None:
        return
    try:
        await on_error(component, exc)
    except Exception:
        logger.warning("could not report the %s failure", component, exc_info=True)


class OkxRestClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def fetch_swap_tickers(self) -> list[OkxTicker]:
        async with httpx.AsyncClient(base_url=self.settings.okx_rest_url, timeout=15) as client:
            response = await client.get("/api/v5/market/tickers", params={"instType": "SWAP"})
            response.raise_for_status()
            payload = response.json()
        return [parse_okx_ticker(item) for item in payload.get("data", [])]

    async def fetch_swap_instruments(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(base_url=self.settings.okx_rest_url, timeout=15) as client:
            response = await client.get("/api/v5/public/instruments", params={"instType": "SWAP"})
            response.raise_for_status()
            payload = response.json()
        return list(payload.get("data", []))

    async def fetch_candles(
        self,
        *,
        inst_id: str,
        bar: str = "1H",
        limit: int = 100,
    ) -> list[OkxCandle]:
        async with httpx.AsyncClient(base_url=self.settings.okx_rest_url, timeout=15) as client:
            response = await client.get(
                "/api/v5/market/candles",
                params={"instId": inst_id, "bar": bar, "limit": str(limit)},
            )
            response.raise_for_status()
            payload = response.json()
        return [parse_okx_candle(item) for item in payload.get("data", [])]

    async def fetch_funding_rate(self, *, inst_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.settings.okx_rest_url, timeout=15) as client:
            response = await client.get("/api/v5/public/funding-rate", params={"instId": inst_id})
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", [])
        return dict(data[0]) if data else {}

    async def fetch_open_interest(self, *, inst_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.settings.okx_rest_url, timeout=15) as client:
            response = await client.get(
                "/api/v5/public/open-interest",
                params={"instType": "SWAP", "instId": inst_id},
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", [])
        return dict(data[0]) if data else {}


class OkxWsTickerStream:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def stream(self) -> AsyncIterator[OkxTicker]:
        subscribe = {
            "op": "subscribe",
            "args": [{"channel": "tickers", "instType": "SWAP"}],
        }
        async with websockets.connect(
            self.settings.okx_public_ws_url,
            ping_interval=20,
        ) as websocket:
            await websocket.send(json.dumps(subscribe))
            async for message in websocket:
                payload = json.loads(message)
                if "data" not in payload:
                    continue
                for item in payload["data"]:
                    yield parse_okx_ticker(item)


class MarketIngestor:
    def __init__(self, settings: Settings, repository: MarketRepository) -> None:
        self.settings = settings
        self.repository = repository
        self.rest = OkxRestClient(settings)
        self.ws = OkxWsTickerStream(settings)

    async def ingest_rest_once(self) -> int:
        tickers = await self.rest.fetch_swap_tickers()
        for ticker in tickers:
            self.repository.upsert_ticker_snapshot(
                inst_id=ticker.inst_id,
                inst_type=ticker.inst_type,
                last=ticker.last,
                volume_ccy_24h=ticker.volume_ccy_24h,
                change_utc0_pct=ticker.change_utc0_pct,
                raw=ticker.raw,
            )
        return len(tickers)

    async def ingest_ws_forever(self, on_error: ErrorHook | None = None) -> None:
        """Stream tickers forever; a dropped websocket falls back to one REST snapshot.

        Nothing in here may raise: this is one task of the worker's single `asyncio.gather`, so an
        escaping exception ends the whole worker process. The REST fallback runs inside the
        `except` block, which is exactly where it used to escape: an upstream outage that closes
        the websocket usually takes the REST endpoint down with it. Failures go to
        `on_error(component, exc)`, which the worker points at its runtime-error journal.
        """
        while True:
            try:
                async for ticker in self.ws.stream():
                    self.repository.upsert_ticker_snapshot(
                        inst_id=ticker.inst_id,
                        inst_type=ticker.inst_type,
                        last=ticker.last,
                        volume_ccy_24h=ticker.volume_ccy_24h,
                        change_utc0_pct=ticker.change_utc0_pct,
                        raw=ticker.raw,
                    )
            except Exception as exc:
                logger.warning("OKX websocket stream failed; falling back to REST", exc_info=True)
                await _report(on_error, "worker.okx_ws", exc)
                try:
                    await self.ingest_rest_once()
                except Exception as rest_exc:
                    logger.warning("OKX REST fallback failed; retrying after pause", exc_info=True)
                    await _report(on_error, "worker.okx_rest_fallback", rest_exc)
                await asyncio.sleep(15)
