import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import websockets

from hypertrade.config import Settings
from hypertrade.market.okx import OkxCandle, OkxTicker, parse_okx_candle, parse_okx_ticker
from hypertrade.market.repository import MarketRepository


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

    async def ingest_ws_forever(self) -> None:
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
            except Exception:
                await self.ingest_rest_once()
                await asyncio.sleep(15)
