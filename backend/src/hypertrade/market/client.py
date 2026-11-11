import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedOK

from hypertrade.config import Settings
from hypertrade.market.okx import (
    OkxCandle,
    OkxTicker,
    normalize_okx_ws_url,
    parse_okx_candle,
    parse_okx_ticker,
    parse_okx_ws_frame,
    rank_swap_inst_ids,
    ticker_subscribe_requests,
)
from hypertrade.market.repository import MarketRepository

logger = logging.getLogger("hypertrade.market")

# `(component, exception)`: where the worker plugs in its runtime-error journal.
ErrorHook = Callable[[str, Exception], Awaitable[None]]
InstId = str  # e.g. "BTC-USDT-SWAP"
# `(component)`: called while ingestion works, so a failure streak can end. Throttled below.
OkHook = Callable[[str], None]
# Where the websocket takes its contract list from: a REST snapshot of the SWAP tickers.
UniverseProvider = Callable[[], Awaitable[Sequence[OkxTicker]]]

_OK_REPORT_INTERVAL_SECONDS = 5.0
# Websocket tickers are buffered (newest per instrument) and written as one batch this often.
_WS_FLUSH_INTERVAL_SECONDS = 1.0

# Websocket subscription. OKX limits a connection to 480 subscribe/unsubscribe/login requests per
# hour and one request to 64 KB, so the batch size is about request count, not message size.
_SUBSCRIBE_BATCH_SIZE = 50
# OKX closes a connection whose subscription is not established, or that has received no data, for
# 30 s (close code 4004), and asks for a text `ping` after N < 30 s of silence. A first ticker is
# expected well before that, so a dead subscription is named here instead of as a bare close.
_PING_AFTER_SECONDS = 15.0
_FIRST_DATA_TIMEOUT_SECONDS = 20.0
_IDLE_TIMEOUT_SECONDS = 30.0
# Close codes 4008/4009: too many subscribed channels on this connection. OKX does not publish the
# number, so the subscription is halved when it happens (never below this many instruments).
_SUBSCRIPTION_LIMIT_CLOSE_CODES = frozenset({4008, 4009})
_MIN_WS_INSTRUMENTS = 10
# Websocket reconnects wait 15 s, 30 s, then 60 s while they keep failing; a session that streamed
# for `_HEALTHY_SESSION_SECONDS` starts the backoff over. A stream that ends without an error (a
# server restart, a 1000/1001 close) reconnects after a short pause, never in a tight loop: OKX
# allows 3 new connections per second per IP.
_BACKOFF_BASE_SECONDS = 15.0
_BACKOFF_MAX_SECONDS = 60.0
_HEALTHY_SESSION_SECONDS = 30.0
_RECONNECT_PAUSE_SECONDS = 1.0
# A REST list of SWAP tickers this recent (typically the REST fallback right before a reconnect)
# is reused as the contract list instead of fetching another one.
_UNIVERSE_CACHE_SECONDS = 300.0


def _now() -> float:
    return time.monotonic()


def _backoff_seconds(failures: int) -> float:
    """How long to wait after the `failures`-th failure in a row (the first is 1)."""
    doublings = min(max(failures - 1, 0), 6)  # the cap is reached long before this saturates
    return min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * (1 << doublings))


class OkxWsError(RuntimeError):
    """The websocket is up but not delivering tickers, or OKX said why it will not."""


class OkxWsSubscriptionLimitError(OkxWsError):
    """OKX closed the connection because it carries too many subscribed channels."""


def _ok(on_ok: OkHook | None, component: str) -> None:
    if on_ok is None:
        return
    try:
        on_ok(component)
    except Exception:
        logger.warning("could not report the %s success", component, exc_info=True)


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


def _silence_message(*, first: bool, seconds: float, refusals: Sequence[str]) -> str:
    """Name a subscription that delivers nothing, with whatever OKX said about refusing it."""
    when = f"within {seconds:g}s of subscribing" if first else f"for {seconds:g}s"
    said = f"; OKX said: {'; '.join(refusals)}" if refusals else ""
    return f"OKX websocket delivered no ticker {when}{said}"


class OkxWsTickerStream:
    """The public `tickers` channel for the busiest SWAP contracts, subscribed one `instId` each.

    The channel takes an `instId` per subscription and has no `instType` form, so the contract
    list comes from `universe` (a REST snapshot) and goes out in batches. Failures are raised, never
    swallowed, so the caller can report them and fall back to REST: a connection that dies
    (`ConnectionClosedError`), a subscription that delivers nothing (`OkxWsError`, carrying what OKX
    answered) and a connection that carries too many channels (`OkxWsSubscriptionLimitError`).
    A clean close, or OKX announcing a restart, ends the stream without an error.
    """

    def __init__(self, settings: Settings, *, universe: UniverseProvider | None = None) -> None:
        self.settings = settings
        self.url = normalize_okx_ws_url(settings.okx_public_ws_url)
        if self.url != settings.okx_public_ws_url:
            logger.warning(
                "OKX_PUBLIC_WS_URL uses the retired port 8443; connecting to %s instead", self.url
            )
        self.universe: UniverseProvider = universe or OkxRestClient(settings).fetch_swap_tickers
        # Lowered for the rest of the process when OKX closes the connection with 4008/4009.
        self.max_instruments = settings.okx_ws_max_instruments
        self.batch_size = _SUBSCRIBE_BATCH_SIZE
        self.ping_after = _PING_AFTER_SECONDS
        self.first_data_timeout = _FIRST_DATA_TIMEOUT_SECONDS
        self.idle_timeout = _IDLE_TIMEOUT_SECONDS

    async def stream(self) -> AsyncIterator[OkxTicker]:
        inst_ids = rank_swap_inst_ids(await self.universe(), self.max_instruments)
        if not inst_ids:
            raise OkxWsError("the REST snapshot listed no SWAP instrument to subscribe to")
        requests = ticker_subscribe_requests(inst_ids, self.batch_size)
        refusals: deque[str] = deque(maxlen=5)  # what OKX said when it refused something
        try:
            # No protocol-level pings: OKX's keepalive is the text `ping`/`pong` sent below.
            async with websockets.connect(self.url, ping_interval=None) as websocket:
                for request in requests:
                    await websocket.send(json.dumps(request))
                logger.info(
                    "OKX websocket: subscribing to %d instruments in %d requests",
                    len(inst_ids),
                    len(requests),
                )
                started = _now()
                last_data: float | None = None
                ping_sent = False
                malformed_logged = False
                while True:
                    # The deadline for the next ticker: the first one is awaited from the moment
                    # of subscribing, later ones from the previous ticker. Pongs and
                    # acknowledgements do not extend it, so a dead subscription cannot hide
                    # behind the keepalive.
                    first = last_data is None
                    patience = self.first_data_timeout if first else self.idle_timeout
                    deadline = (started if last_data is None else last_data) + patience
                    wait = max(min(self.ping_after, deadline - _now()), 0.0)
                    try:
                        async with asyncio.timeout(wait):
                            raw = await websocket.recv()
                    except TimeoutError:
                        if _now() >= deadline:
                            raise OkxWsError(
                                _silence_message(first=first, seconds=patience, refusals=refusals)
                            ) from None
                        if ping_sent:
                            raise OkxWsError(
                                f"OKX websocket did not answer a ping within {self.ping_after:g}s"
                            ) from None
                        await websocket.send("ping")
                        ping_sent = True
                        continue
                    ping_sent = False  # any frame shows the connection is alive
                    frame = parse_okx_ws_frame(raw)
                    if frame.kind == "tickers":
                        if frame.tickers:
                            last_data = _now()
                        for ticker in frame.tickers:
                            yield ticker
                    elif frame.kind == "error":
                        refusals.append(f"{frame.code} {frame.message}".strip())
                        logger.warning(
                            "OKX websocket refused a request: %s %s", frame.code, frame.message
                        )
                    elif frame.kind == "notice":
                        if frame.code == "64008":  # a service upgrade: OKX will close us soon
                            logger.info("OKX websocket announced a restart; reconnecting")
                            return
                        logger.warning("OKX websocket notice %s: %s", frame.code, frame.message)
                    elif frame.kind == "malformed" and not malformed_logged:
                        malformed_logged = True
                        logger.warning(
                            "OKX websocket sent a frame that is not JSON: %r", frame.message
                        )
        except ConnectionClosedOK:
            return
        except ConnectionClosed as exc:
            closed = exc.rcvd
            if closed is not None and closed.code in _SUBSCRIPTION_LIMIT_CLOSE_CODES:
                self.max_instruments = max(
                    _MIN_WS_INSTRUMENTS, min(self.max_instruments, len(inst_ids)) // 2
                )
                raise OkxWsSubscriptionLimitError(
                    f"OKX closed the websocket with {closed.code} ({closed.reason}) while "
                    f"{len(inst_ids)} instruments were subscribed; subscribing to "
                    f"{self.max_instruments} instead"
                ) from exc
            raise


class MarketIngestor:
    def __init__(self, settings: Settings, repository: MarketRepository) -> None:
        self.settings = settings
        self.repository = repository
        self.rest = OkxRestClient(settings)
        # The newest REST list of SWAP tickers and when it arrived: the websocket picks the
        # contracts it subscribes to from it.
        self._swap_tickers: tuple[float, list[OkxTicker]] | None = None
        self.ws = OkxWsTickerStream(settings, universe=self._universe)

    async def _fetch_swap_tickers(self) -> list[OkxTicker]:
        tickers = await self.rest.fetch_swap_tickers()
        self._swap_tickers = (_now(), tickers)
        return tickers

    async def _universe(self) -> list[OkxTicker]:
        """The SWAP tickers the websocket chooses its subscriptions from.

        After a failure the REST fallback has just fetched a full list, which is reused instead of
        asking OKX for a second one a few seconds later.
        """
        cached = self._swap_tickers
        if cached is not None and _now() - cached[0] < _UNIVERSE_CACHE_SECONDS:
            return cached[1]
        return await self._fetch_swap_tickers()

    async def ingest_rest_once(self) -> int:
        tickers = await self._fetch_swap_tickers()
        # One batched transaction on a worker thread. This used to be a loop of per-ticker
        # upserts right here on the event-loop thread: ~700 tickers x 3 database round trips held
        # the whole worker (heartbeat, paper trading, every ARC loop) for ~9 s at a 2.6 ms round
        # trip and for over a minute while the database was busy after a deploy.
        await asyncio.to_thread(self.repository.upsert_ticker_snapshots, tickers)
        return len(tickers)

    async def _store(self, pending: dict[InstId, OkxTicker]) -> bool:
        """Write the buffered websocket tickers as one batch off the event loop.

        Returns whether anything was written, so an empty buffer is never reported as success.
        """
        if not pending:
            return False
        batch = list(pending.values())
        pending.clear()
        await asyncio.to_thread(self.repository.upsert_ticker_snapshots, batch)
        return True

    async def ingest_ws_forever(
        self, on_error: ErrorHook | None = None, on_ok: OkHook | None = None
    ) -> None:
        """Stream tickers forever; a dropped websocket falls back to one REST snapshot.

        Nothing in here may raise: this is one task of the worker's single `asyncio.gather`, so an
        escaping exception ends the whole worker process. The REST fallback runs inside the
        `except` block, which is exactly where it used to escape: an upstream outage that closes
        the websocket usually takes the REST endpoint down with it. Failures go to
        `on_error(component, exc)`, which the worker points at its runtime-error journal; `on_ok`
        says it is working again (at most every few seconds), which ends a failure streak.

        Tickers are buffered (newest per instrument wins) and written as one batch off the event
        loop about once a second, instead of one blocking write per message. A stream that goes
        quiet flushes when the next message arrives or when it ends; the tickers channel is
        never quiet for long.

        Reconnects back off 15 s, 30 s, then 60 s while the stream keeps failing, and start over
        once a connection has streamed for 30 s. A stream that ends without an error (OKX closing
        cleanly or announcing a restart) is reconnected after a one-second pause.
        """
        pending: dict[InstId, OkxTicker] = {}
        last_flush = _now()
        last_ok = float("-inf")
        failures = 0  # failed sessions in a row; drives the backoff
        healthy_since: float | None = None  # when the current session delivered its first ticker

        async def flush() -> None:
            nonlocal last_flush, last_ok
            wrote = await self._store(pending)
            last_flush = _now()
            if wrote and last_flush - last_ok >= _OK_REPORT_INTERVAL_SECONDS:
                last_ok = last_flush
                _ok(on_ok, "worker.okx_ws")

        while True:
            healthy_since = None
            try:
                async for ticker in self.ws.stream():
                    if healthy_since is None:
                        healthy_since = _now()
                    pending[ticker.inst_id] = ticker
                    if _now() - last_flush >= _WS_FLUSH_INTERVAL_SECONDS:
                        await flush()
                await flush()  # the stream ended normally: write what is still buffered
            except Exception as exc:
                # The REST snapshot below refreshes every instrument, so whatever was buffered
                # is superseded; dropping it keeps a failing database from being hit twice.
                pending.clear()
                if healthy_since is not None and _now() - healthy_since >= _HEALTHY_SESSION_SECONDS:
                    failures = 0  # it ran for a while: this is a new outage, not the old one
                failures += 1
                logger.warning("OKX websocket stream failed; falling back to REST", exc_info=True)
                await _report(on_error, "worker.okx_ws", exc)
                try:
                    await self.ingest_rest_once()
                except Exception as rest_exc:
                    logger.warning("OKX REST fallback failed; retrying after pause", exc_info=True)
                    await _report(on_error, "worker.okx_rest_fallback", rest_exc)
                else:
                    _ok(on_ok, "worker.okx_rest_fallback")
                await asyncio.sleep(_backoff_seconds(failures))
            else:
                if healthy_since is not None and _now() - healthy_since >= _HEALTHY_SESSION_SECONDS:
                    failures = 0
                await asyncio.sleep(_RECONNECT_PAUSE_SECONDS)
