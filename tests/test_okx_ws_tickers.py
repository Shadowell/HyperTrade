"""The OKX public websocket stream: what it subscribes to, how it batches, and how it recovers.

Background: in production `worker.okx_ws` never succeeded. The stream subscribed with
`{"channel": "tickers", "instType": "SWAP"}`, but OKX documents the `tickers` channel with an
`instId` per subscription and no `instType` (API v5 WebSocket overview and "WS / Tickers channel",
snapshot of 2026-11-09). A subscription that is not established gets the connection closed after
30 s (close code 4004), which is the `ConnectionClosedError` the worker kept journaling. The
default URL also still named port 8443, which OKX stopped accepting on 2026-10-31.

The dev machine cannot reach OKX, so these tests run against `FakeOkx`: a real local websocket
server that enforces only what the documentation promises. What OKX really answers to the old
`instType` form is NOT verified here; what is pinned is that the client never sends it.
"""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
import websockets
from hypertrade.config import Settings
from hypertrade.market import client as market_client
from hypertrade.market.client import (
    MarketIngestor,
    OkxWsError,
    OkxWsSubscriptionLimitError,
    OkxWsTickerStream,
    _backoff_seconds,
)
from hypertrade.market.okx import (
    OkxTicker,
    normalize_okx_ws_url,
    parse_okx_ws_frame,
    rank_swap_inst_ids,
    ticker_subscribe_requests,
)
from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosedError

_REAL_SLEEP = asyncio.sleep  # several tests patch timing constants; the fake server must not
_CONN_ID = "a4d3ae55"
_PUSH_INTERVAL = 0.005


# --- a stand-in for wss://ws.okx.com/ws/v5/public --------------------------------------------


def _ticker_frame(inst_id: str, last: int) -> str:
    """A push in the documented shape of the tickers channel."""
    item = {
        "instType": "SWAP",
        "instId": inst_id,
        "last": str(last),
        "lastSz": "1",
        "askPx": str(last + 1),
        "askSz": "11",
        "bidPx": str(last - 1),
        "bidSz": "5",
        "open24h": "90",
        "high24h": "120",
        "low24h": "80",
        "volCcy24h": "2222",
        "vol24h": "2222",
        "sodUtc0": "100",
        "sodUtc8": "100",
        "ts": "1597026383085",
    }
    return json.dumps({"arg": {"channel": "tickers", "instId": inst_id}, "data": [item]})


@dataclass
class Behavior:
    """What the fake does on one connection; the last entry repeats for later connections."""

    push: bool = True  # push tickers for what was subscribed
    push_delay: float = 0.0  # wait this long after the subscription before the first push
    push_frames: int | None = None  # go silent (connection stays open) after this many pushes
    answer_pings: bool = True  # answer the text `ping` with `pong`, as OKX documents
    refuse_everything: bool = False  # answer every subscription argument with an error event
    max_channels: int | None = None  # close above this many subscribed channels...
    limit_code: int = 4009  # ...with this status (OKX documents 4008 and 4009)
    notice_after: int | None = None  # announce a service upgrade (64008) after this many pushes
    close_after: int | None = None  # close the connection after this many pushes (0: at once)
    close_code: int = 1011
    close_reason: str = "server closed"
    junk_first: bool = False  # send frames a client must tolerate before the first push


@dataclass
class Connection:
    path: str = ""
    started: float = field(default_factory=time.monotonic)
    texts: list[str] = field(default_factory=list)  # frames that are not JSON (the `ping`s)
    requests: list[dict[str, Any]] = field(default_factory=list)
    subscribed: list[str] = field(default_factory=list)  # instIds acknowledged, in order
    refused: list[dict[str, Any]] = field(default_factory=list)  # arguments that were refused


class FakeOkx:
    """Enforces the documented subscription form: `tickers` takes `channel` and `instId` only."""

    def __init__(self, *behaviors: Behavior) -> None:
        self.behaviors = list(behaviors) or [Behavior()]
        self.connections: list[Connection] = []

    async def handler(self, ws: ServerConnection) -> None:
        conn = Connection(path=ws.request.path if ws.request else "")
        behavior = self.behaviors[min(len(self.connections), len(self.behaviors) - 1)]
        self.connections.append(conn)
        pusher: asyncio.Task[None] | None = None
        try:
            async for message in ws:
                if message == "ping":
                    conn.texts.append("ping")
                    if behavior.answer_pings:
                        await ws.send("pong")
                    continue
                request = json.loads(message)
                conn.requests.append(request)
                for arg in request["args"]:
                    documented = set(arg) == {"channel", "instId"} and arg["channel"] == "tickers"
                    if behavior.refuse_everything or not documented or not arg["instId"]:
                        conn.refused.append(arg)
                        refusal = {
                            "id": request.get("id"),
                            "event": "error",
                            "code": "60018",
                            "msg": f"Wrong URL or channel:{arg.get('channel')} doesn't exist.",
                            "connId": _CONN_ID,
                        }
                        await ws.send(json.dumps(refusal))
                        continue
                    conn.subscribed.append(arg["instId"])
                    ack = {"id": request.get("id"), "event": "subscribe", "arg": arg}
                    await ws.send(json.dumps({**ack, "connId": _CONN_ID}))
                if (
                    behavior.max_channels is not None
                    and len(conn.subscribed) > behavior.max_channels
                ):
                    await ws.close(
                        behavior.limit_code, "The number of subscribed channels exceeds the limit"
                    )
                    return
                if conn.subscribed and behavior.push and pusher is None:
                    pusher = asyncio.create_task(self._push(ws, conn, behavior))
        except websockets.ConnectionClosed:
            pass
        finally:
            if pusher is not None:
                pusher.cancel()

    async def _push(self, ws: ServerConnection, conn: Connection, behavior: Behavior) -> None:
        with contextlib.suppress(websockets.ConnectionClosed):
            await _REAL_SLEEP(behavior.push_delay)
            if behavior.junk_first:
                await ws.send("this is not json")
                await ws.send(b"\x00\x01")
                await ws.send("[]")
            frames = 0
            while True:
                if behavior.close_after is not None and frames >= behavior.close_after:
                    await ws.close(behavior.close_code, behavior.close_reason)
                    return
                if behavior.push_frames is not None and frames >= behavior.push_frames:
                    return  # silent from here on, but the connection stays open
                inst_id = conn.subscribed[frames % len(conn.subscribed)]
                await ws.send(_ticker_frame(inst_id, 100 + frames))
                frames += 1
                if behavior.notice_after is not None and frames == behavior.notice_after:
                    notice = {
                        "event": "notice",
                        "code": "64008",
                        "msg": "The connection will soon be closed for a service upgrade.",
                        "connId": _CONN_ID,
                    }
                    await ws.send(json.dumps(notice))
                await _REAL_SLEEP(_PUSH_INTERVAL)


@contextlib.asynccontextmanager
async def serving(okx: FakeOkx) -> AsyncIterator[str]:
    async with serve(okx.handler, "127.0.0.1", 0) as server:
        yield f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/ws/v5/public"


def _run(scenario: Coroutine[Any, Any, Any]) -> Any:
    async def guarded() -> Any:
        return await asyncio.wait_for(scenario, timeout=20)

    return asyncio.run(guarded())


# --- fixtures --------------------------------------------------------------------------------


def _swap_tickers(count: int) -> list[OkxTicker]:
    """`count` contracts; a higher number means more 24h turnover, so COIN{count-1} is busiest."""
    return [
        OkxTicker(
            inst_id=f"COIN{i:03d}-USDT-SWAP",
            inst_type="SWAP",
            last=Decimal(1),
            volume_ccy_24h=Decimal(i + 1),
            change_utc0_pct=Decimal(0),
            raw={},
        )
        for i in range(count)
    ]


def _busiest(count: int, universe: int = 120) -> list[str]:
    return [f"COIN{i:03d}-USDT-SWAP" for i in range(universe - 1, universe - 1 - count, -1)]


def _settings(url: str, **extra: Any) -> Settings:
    return Settings(DEEPSEEK_API_KEY="", OKX_PUBLIC_WS_URL=url, **extra)


def _universe_of(tickers: list[OkxTicker]) -> Callable[[], Awaitable[list[OkxTicker]]]:
    async def universe() -> list[OkxTicker]:
        return tickers

    return universe


def _stream(url: str, *, limit: int = 100, **tuning: float) -> OkxWsTickerStream:
    stream = OkxWsTickerStream(
        _settings(url, OKX_WS_MAX_INSTRUMENTS=limit), universe=_universe_of(_swap_tickers(120))
    )
    stream.first_data_timeout = 2.0
    stream.idle_timeout = 2.0
    stream.ping_after = 1.0
    for name, value in tuning.items():
        setattr(stream, name, value)
    return stream


async def _take(stream: OkxWsTickerStream, count: int) -> list[OkxTicker]:
    taken: list[OkxTicker] = []
    async with contextlib.aclosing(stream.stream()) as source:
        async for ticker in source:
            taken.append(ticker)
            if len(taken) >= count:
                break
    return taken


async def _drain(stream: OkxWsTickerStream) -> list[OkxTicker]:
    async with contextlib.aclosing(stream.stream()) as source:
        return [ticker async for ticker in source]


# --- what is sent ----------------------------------------------------------------------------


def test_subscriptions_name_each_instrument_by_inst_id_in_the_documented_shape() -> None:
    requests = ticker_subscribe_requests(_busiest(120), batch_size=50)

    assert [len(request["args"]) for request in requests] == [50, 50, 20]
    for request in requests:
        assert set(request) == {"id", "op", "args"} and request["op"] == "subscribe"
        for arg in request["args"]:
            assert set(arg) == {"channel", "instId"}, (
                "tickers takes instId; instType is no parameter"
            )
            assert arg["channel"] == "tickers"
        # the id is echoed back by OKX: alphanumeric, at most 32 characters
        assert request["id"].isalnum() and len(request["id"]) <= 32
        assert len(json.dumps(request)) < 64 * 1024, "one request may not exceed 64 KB"
    assert len({request["id"] for request in requests}) == len(requests)
    flat = [arg["instId"] for request in requests for arg in request["args"]]
    assert flat == _busiest(120), "every instrument exactly once, in the order given"


def test_the_contract_list_is_ranked_by_turnover_and_capped() -> None:
    shuffled = list(reversed(_swap_tickers(120)))

    assert rank_swap_inst_ids(shuffled, 3) == _busiest(3)
    assert rank_swap_inst_ids(shuffled, 500) == _busiest(120)
    assert rank_swap_inst_ids(shuffled, 0) == []


def test_ranking_uses_turnover_not_volume_and_is_deterministic_on_ties() -> None:
    def ticker(inst_id: str, last: str, volume: str) -> OkxTicker:
        return OkxTicker(inst_id, "SWAP", Decimal(last), Decimal(volume), Decimal(0), {})

    tickers = [
        ticker("A-USDT-SWAP", "1", "1000"),  # turnover 1000
        ticker("B-USDT-SWAP", "50000", "1"),  # turnover 50000: few contracts, big notional
        ticker("D-USDT-SWAP", "1", "0"),  # never traded
        ticker("C-USDT-SWAP", "10", "100"),  # turnover 1000, ties with A
        ticker("", "9", "9"),  # no instrument id: never subscribed
        ticker("A-USDT-SWAP", "1", "1000"),  # a duplicate row
    ]

    assert rank_swap_inst_ids(tickers, 10) == [
        "B-USDT-SWAP",
        "A-USDT-SWAP",
        "C-USDT-SWAP",
        "D-USDT-SWAP",
    ]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("wss://ws.okx.com:8443/ws/v5/public", "wss://ws.okx.com/ws/v5/public"),
        ("wss://wspap.okx.com:8443/ws/v5/public", "wss://wspap.okx.com/ws/v5/public"),
        ("wss://WS.OKX.COM:8443/ws/v5/public", "wss://ws.okx.com/ws/v5/public"),
        ("wss://ws.okx.com/ws/v5/public", "wss://ws.okx.com/ws/v5/public"),
        ("wss://ws.okx.com:443/ws/v5/public", "wss://ws.okx.com:443/ws/v5/public"),
        ("ws://127.0.0.1:8443/ws/v5/public", "ws://127.0.0.1:8443/ws/v5/public"),
        ("wss://proxy.example.com:8443/ws/v5/public", "wss://proxy.example.com:8443/ws/v5/public"),
        ("wss://notokx.com:8443/ws/v5/public", "wss://notokx.com:8443/ws/v5/public"),
        ("wss://ws.okx.com:notaport/ws/v5/public", "wss://ws.okx.com:notaport/ws/v5/public"),
    ],
)
def test_the_retired_port_8443_is_dropped_from_okx_urls_only(url: str, expected: str) -> None:
    assert normalize_okx_ws_url(url) == expected


def test_the_stream_connects_to_the_normalized_url_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="hypertrade.market"):
        stream = OkxWsTickerStream(_settings("wss://ws.okx.com:8443/ws/v5/public"))

    assert stream.url == "wss://ws.okx.com/ws/v5/public"
    assert "retired port 8443" in caplog.text


def test_settings_default_to_port_443_and_a_bounded_subscription() -> None:
    settings = Settings(DEEPSEEK_API_KEY="")

    assert settings.okx_public_ws_url == "wss://ws.okx.com/ws/v5/public"
    assert settings.okx_ws_max_instruments == 100
    with pytest.raises(ValidationError):
        Settings(DEEPSEEK_API_KEY="", OKX_WS_MAX_INSTRUMENTS=0)


# --- frames ----------------------------------------------------------------------------------


def test_frames_are_classified_the_way_okx_documents_them() -> None:
    push = _ticker_frame("BTC-USDT-SWAP", 7)
    frame = parse_okx_ws_frame(push)
    assert frame.kind == "tickers" and frame.tickers[0].inst_id == "BTC-USDT-SWAP"
    assert frame.tickers[0].last == Decimal(7) and frame.tickers[0].change_utc0_pct == Decimal(
        "-93"
    )

    assert parse_okx_ws_frame("pong").kind == "pong"
    ack = json.dumps({"event": "subscribe", "arg": {"channel": "tickers", "instId": "X"}})
    assert parse_okx_ws_frame(ack).kind == "ack"
    error = parse_okx_ws_frame(json.dumps({"event": "error", "code": "60012", "msg": "bad"}))
    assert (error.kind, error.code, error.message) == ("error", "60012", "bad")
    notice = parse_okx_ws_frame(json.dumps({"event": "notice", "code": "64008", "msg": "soon"}))
    assert (notice.kind, notice.code) == ("notice", "64008")


def test_frames_that_are_not_tickers_never_raise() -> None:
    assert parse_okx_ws_frame("not json").kind == "malformed"
    assert parse_okx_ws_frame("[1, 2]").kind == "malformed"
    assert parse_okx_ws_frame(b"\x00").kind == "ignored"
    other = json.dumps({"arg": {"channel": "trades", "instId": "X"}, "data": [{"instId": "X"}]})
    assert parse_okx_ws_frame(other).kind == "ignored"
    assert parse_okx_ws_frame(json.dumps({"data": "nope"})).kind == "ignored"
    # items without an instrument id are dropped instead of being stored under ""
    partial = json.dumps({"arg": {"channel": "tickers"}, "data": [{"last": "1"}, {"instId": "A"}]})
    assert [t.inst_id for t in parse_okx_ws_frame(partial).tickers] == ["A"]


# --- the stream against the fake server ------------------------------------------------------


def test_it_subscribes_per_instrument_in_batches_and_yields_the_pushed_tickers() -> None:
    okx = FakeOkx()

    async def scenario() -> list[OkxTicker]:
        async with serving(okx) as url:
            return await _take(_stream(url), 5)

    tickers = _run(scenario())

    (conn,) = okx.connections
    assert conn.path == "/ws/v5/public"
    assert [len(request["args"]) for request in conn.requests] == [50, 50]
    assert conn.refused == [], "the server only accepts channel + instId"
    assert conn.subscribed == _busiest(100), "the 100 busiest contracts, busiest first"
    assert [ticker.inst_id for ticker in tickers] == conn.subscribed[:5]
    assert [ticker.last for ticker in tickers] == [Decimal(100 + i) for i in range(5)]
    assert all(ticker.inst_type == "SWAP" for ticker in tickers)


def test_the_subscription_follows_the_configured_cap() -> None:
    okx = FakeOkx()

    async def scenario() -> None:
        async with serving(okx) as url:
            stream = _stream(url, limit=7)
            stream.batch_size = 3
            await _take(stream, 1)

    _run(scenario())

    (conn,) = okx.connections
    assert [len(request["args"]) for request in conn.requests] == [3, 3, 1]
    assert conn.subscribed == _busiest(7)


def test_the_server_here_refuses_anything_but_the_documented_form() -> None:
    # Guards the fake itself: the tests above only mean something if it rejects the old form.
    okx = FakeOkx()

    async def scenario() -> list[Any]:
        async with serving(okx) as url, websockets.connect(url) as ws:
            await ws.send(
                json.dumps(
                    {"op": "subscribe", "args": [{"channel": "tickers", "instType": "SWAP"}]}
                )
            )
            reply = json.loads(await ws.recv())
            await ws.send(
                json.dumps({"op": "subscribe", "args": [{"channel": "tickers", "instId": "A"}]})
            )
            ack = json.loads(await ws.recv())
            return [reply, ack]

    reply, ack = _run(scenario())

    assert reply["event"] == "error" and ack["event"] == "subscribe"
    assert okx.connections[0].refused == [{"channel": "tickers", "instType": "SWAP"}]


def test_a_subscription_that_delivers_nothing_is_named_before_okx_closes_the_connection() -> None:
    okx = FakeOkx(Behavior(push=False))

    async def scenario() -> None:
        async with serving(okx) as url:
            await _drain(_stream(url, first_data_timeout=0.3, ping_after=0.1))

    with pytest.raises(OkxWsError, match=r"no ticker within 0\.3s of subscribing"):
        _run(scenario())


def test_what_okx_answered_is_part_of_the_failure() -> None:
    okx = FakeOkx(Behavior(refuse_everything=True))

    async def scenario() -> None:
        async with serving(okx) as url:
            await _drain(_stream(url, first_data_timeout=0.3, ping_after=0.1))

    with pytest.raises(OkxWsError) as excinfo:
        _run(scenario())

    assert "60018" in str(excinfo.value) and "doesn't exist" in str(excinfo.value)


def test_a_refused_request_does_not_drop_a_connection_that_streams() -> None:
    # Only part of a subscription is refused here (not every OKX answer is known); as long as
    # tickers arrive the connection is kept, and the refusal is logged.
    okx = FakeOkx(Behavior(junk_first=True))

    async def scenario() -> list[OkxTicker]:
        async with serving(okx) as url:
            return await _take(_stream(url), 3)

    assert len(_run(scenario())) == 3, "junk frames before the data must not end the stream"


def test_it_keeps_the_connection_alive_with_the_text_ping_okx_documents() -> None:
    # Silence for 0.35 s: OKX wants a text `ping` after N < 30 s without a message, and answers
    # with the bare text `pong`, which is not JSON and must not break the reader.
    okx = FakeOkx(Behavior(push_delay=0.35))

    async def scenario() -> list[OkxTicker]:
        async with serving(okx) as url:
            return await _take(_stream(url, ping_after=0.1, first_data_timeout=3.0), 1)

    assert len(_run(scenario())) == 1
    assert okx.connections[0].texts.count("ping") >= 2


def test_an_unanswered_ping_is_a_dead_connection() -> None:
    okx = FakeOkx(Behavior(push=False, answer_pings=False))

    async def scenario() -> None:
        async with serving(okx) as url:
            await _drain(_stream(url, ping_after=0.1, first_data_timeout=5.0))

    with pytest.raises(OkxWsError, match="did not answer a ping"):
        _run(scenario())


def test_a_keepalive_cannot_hide_a_subscription_that_stopped_delivering() -> None:
    # Two tickers, then silence; the server keeps answering pings. Pongs prove the socket is
    # alive, not that the subscription is, so the idle deadline still runs.
    okx = FakeOkx(Behavior(push_frames=2))

    async def scenario() -> list[OkxTicker]:
        async with serving(okx) as url:
            return await _drain(_stream(url, idle_timeout=0.3, ping_after=0.1))

    with pytest.raises(OkxWsError, match=r"no ticker for 0\.3s"):
        _run(scenario())


def test_a_restart_notice_ends_the_stream_without_an_error() -> None:
    okx = FakeOkx(Behavior(notice_after=3))

    async def scenario() -> list[OkxTicker]:
        async with serving(okx) as url:
            return await _drain(_stream(url))

    assert len(_run(scenario())) == 3


def test_a_clean_close_ends_the_stream_without_an_error() -> None:
    okx = FakeOkx(Behavior(close_after=2, close_code=1000, close_reason=""))

    async def scenario() -> list[OkxTicker]:
        async with serving(okx) as url:
            return await _drain(_stream(url))

    assert len(_run(scenario())) == 2


def test_an_abnormal_close_keeps_raising_connection_closed_error() -> None:
    # The type the worker already journals; the close code and reason stay in its message.
    okx = FakeOkx(Behavior(close_after=1, close_code=4004, close_reason="No data received in 30s"))

    async def scenario() -> None:
        async with serving(okx) as url:
            await _drain(_stream(url))

    with pytest.raises(ConnectionClosedError, match="4004"):
        _run(scenario())


@pytest.mark.parametrize("code", [4008, 4009])
def test_close_codes_4008_and_4009_halve_the_subscription_until_it_fits(code: int) -> None:
    # OKX does not publish its per-connection cap, so the client finds it: 100 -> 50 -> 25 here.
    okx = FakeOkx(Behavior(max_channels=30, limit_code=code))
    limits: list[int] = []

    async def scenario() -> list[OkxTicker]:
        async with serving(okx) as url:
            stream = _stream(url, limit=100, batch_size=100)
            for _ in range(2):
                with pytest.raises(OkxWsSubscriptionLimitError, match=str(code)):
                    await _drain(stream)
                limits.append(stream.max_instruments)
            return await _take(stream, 2)

    tickers = _run(scenario())

    assert limits == [50, 25]
    assert [len(conn.subscribed) for conn in okx.connections] == [100, 50, 25]
    assert len(tickers) == 2


def test_the_halving_stops_at_a_floor() -> None:
    okx = FakeOkx(Behavior(max_channels=1))

    async def scenario() -> int:
        async with serving(okx) as url:
            stream = _stream(url, limit=12, batch_size=100)
            for _ in range(3):
                with pytest.raises(OkxWsSubscriptionLimitError):
                    await _drain(stream)
            return stream.max_instruments

    assert _run(scenario()) == 10, "a stream never shrinks below 10 instruments"


def test_other_close_codes_do_not_shrink_the_subscription() -> None:
    okx = FakeOkx(Behavior(close_after=0, close_code=1011))

    async def scenario() -> int:
        async with serving(okx) as url:
            stream = _stream(url, limit=100)
            with pytest.raises(ConnectionClosedError):
                await _drain(stream)
            return stream.max_instruments

    assert _run(scenario()) == 100


def test_an_empty_contract_list_fails_before_connecting() -> None:
    okx = FakeOkx()

    async def scenario() -> None:
        async with serving(okx) as url:
            stream = OkxWsTickerStream(_settings(url), universe=_universe_of([]))
            await _drain(stream)

    with pytest.raises(OkxWsError, match="no SWAP instrument"):
        _run(scenario())
    assert okx.connections == []


# --- reconnects, backoff and the REST fallback -----------------------------------------------


class _Halt(BaseException):
    """Escapes `except Exception`, like a shutdown signal, so it can stop the forever-loop."""


class _Rest:
    def __init__(self, tickers: list[OkxTicker]) -> None:
        self.tickers = tickers
        self.calls = 0

    async def fetch_swap_tickers(self) -> list[OkxTicker]:
        self.calls += 1
        return self.tickers


class _Repository:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def upsert_ticker_snapshots(self, tickers: Any) -> int:
        self.batches.append([ticker.inst_id for ticker in tickers])
        return len(self.batches)


def _ingestor(
    url: str, repository: _Repository, rest: _Rest, *, limit: int = 100
) -> MarketIngestor:
    ingestor = MarketIngestor(
        _settings(url, OKX_WS_MAX_INSTRUMENTS=limit),
        repository,  # type: ignore[arg-type]
    )
    ingestor.rest = rest  # type: ignore[assignment]
    ingestor.ws.first_data_timeout = 2.0
    ingestor.ws.idle_timeout = 2.0
    ingestor.ws.ping_after = 1.0
    return ingestor


@pytest.fixture
def fast_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flush on every ticker, report every success and reconnect without real waiting."""
    monkeypatch.setattr(market_client, "_WS_FLUSH_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(market_client, "_OK_REPORT_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(market_client, "_RECONNECT_PAUSE_SECONDS", 0.01)
    monkeypatch.setattr(market_client, "_BACKOFF_BASE_SECONDS", 0.01)
    monkeypatch.setattr(market_client, "_BACKOFF_MAX_SECONDS", 0.04)


def test_a_dropped_connection_is_reported_falls_back_to_rest_and_resubscribes(
    fast_timing: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(market_client, "_BACKOFF_BASE_SECONDS", 0.2)
    monkeypatch.setattr(market_client, "_BACKOFF_MAX_SECONDS", 0.4)
    okx = FakeOkx(Behavior(close_after=3, close_code=1011, close_reason="boom"), Behavior())
    repository, rest = _Repository(), _Rest(_swap_tickers(120))
    errors: list[tuple[str, BaseException]] = []
    successes: list[str] = []

    async def on_error(component: str, exc: Exception) -> None:
        errors.append((component, exc))

    def on_ok(component: str) -> None:
        successes.append(component)
        if component == "worker.okx_ws" and len(okx.connections) >= 2:
            raise _Halt  # the second connection streams and its tickers were stored

    async def scenario() -> None:
        async with serving(okx) as url:
            await _ingestor(url, repository, rest).ingest_ws_forever(on_error, on_ok)

    with pytest.raises(_Halt):
        _run(scenario())

    first, second = okx.connections[:2]
    assert first.subscribed == second.subscribed == _busiest(100), "resubscribed in full"
    assert second.started - first.started >= 0.2, "the reconnect waited out the backoff"
    assert [len(r["args"]) for r in second.requests] == [50, 50]
    assert [component for component, _ in errors] == ["worker.okx_ws"]
    assert isinstance(errors[0][1], ConnectionClosedError) and "boom" in str(errors[0][1])
    assert "worker.okx_rest_fallback" in successes, "the REST snapshot filled the gap"
    # the contract list was fetched once to subscribe and once as the fallback; the reconnect
    # reused the fallback's list instead of asking OKX again
    assert rest.calls == 2
    # Stored in order: the three tickers of the first connection (one batch each, the flush
    # interval is 0 here), the REST snapshot after the drop, then the second connection's tickers.
    snapshot = [t.inst_id for t in _swap_tickers(120)]
    position = [n for n, batch in enumerate(repository.batches) if len(batch) == 120]
    assert len(position) == 1 and repository.batches[position[0]] == snapshot
    before, after = repository.batches[: position[0]], repository.batches[position[0] + 1 :]
    assert len(before) == 3 and after
    assert all(len(batch) == 1 for batch in before + after)
    assert {batch[0] for batch in before + after} <= set(_busiest(100))


def test_a_stream_that_never_delivers_is_reported_with_what_okx_said(fast_timing: None) -> None:
    okx = FakeOkx(Behavior(refuse_everything=True))
    repository, rest = _Repository(), _Rest(_swap_tickers(120))
    errors: list[tuple[str, str]] = []

    async def on_error(component: str, exc: Exception) -> None:
        errors.append((component, str(exc)))
        if len(errors) == 2:  # two failed sessions in a row: enough to see the first one's report
            raise _Halt

    async def scenario() -> None:
        async with serving(okx) as url:
            ingestor = _ingestor(url, repository, rest)
            ingestor.ws.first_data_timeout = 0.3
            ingestor.ws.ping_after = 0.1
            await ingestor.ingest_ws_forever(on_error)

    with pytest.raises(_Halt):
        _run(scenario())

    assert [component for component, _ in errors] == ["worker.okx_ws", "worker.okx_ws"]
    assert "no ticker within 0.3s" in errors[0][1] and "60018" in errors[0][1]
    assert repository.batches, "the REST fallback still refreshed market_tickers"


def test_backoff_grows_while_it_keeps_failing_and_starts_over_after_a_healthy_session(
    fast_timing: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # sessions: closes at once, closes at once, streams two tickers then dies, closes at once
    okx = FakeOkx(
        Behavior(close_after=0),
        Behavior(close_after=0),
        Behavior(close_after=2),
        Behavior(close_after=0),
    )
    failures_seen: list[int] = []

    def recording_backoff(failures: int) -> float:
        failures_seen.append(failures)
        if len(failures_seen) == 4:
            raise _Halt
        return 0.0

    monkeypatch.setattr(market_client, "_backoff_seconds", recording_backoff)
    monkeypatch.setattr(market_client, "_HEALTHY_SESSION_SECONDS", 0.0)

    async def scenario() -> None:
        async with serving(okx) as url:
            await _ingestor(url, _Repository(), _Rest(_swap_tickers(120))).ingest_ws_forever()

    with pytest.raises(_Halt):
        _run(scenario())

    assert failures_seen == [1, 2, 1, 2]


def test_the_backoff_schedule_is_15_30_then_60_seconds() -> None:
    assert [_backoff_seconds(n) for n in (0, 1, 2, 3, 4, 10)] == [15, 15, 30, 60, 60, 60]
    assert _backoff_seconds(10**6) == 60


def test_a_stream_that_ends_cleanly_reconnects_after_a_pause_and_is_not_an_error(
    fast_timing: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(market_client, "_RECONNECT_PAUSE_SECONDS", 0.2)
    okx = FakeOkx(
        Behavior(notice_after=2),  # OKX announces a service upgrade
        Behavior(close_after=2, close_code=1000, close_reason=""),  # then closes cleanly
        Behavior(),
    )
    repository, rest = _Repository(), _Rest(_swap_tickers(120))
    errors: list[str] = []

    async def on_error(component: str, exc: Exception) -> None:
        errors.append(component)

    def on_ok(component: str) -> None:
        if len(okx.connections) >= 3:
            raise _Halt

    async def scenario() -> None:
        async with serving(okx) as url:
            await _ingestor(url, repository, rest).ingest_ws_forever(on_error, on_ok)

    with pytest.raises(_Halt):
        _run(scenario())

    assert errors == [], "a restart notice and a clean close are not failures"
    gaps = [
        b.started - a.started for a, b in zip(okx.connections, okx.connections[1:], strict=False)
    ]
    assert all(gap >= 0.2 for gap in gaps), f"reconnected in a tight loop: {gaps}"
    assert rest.calls == 1, "no REST fallback was needed: it only listed the contracts once"
    assert len(okx.connections) == 3


def test_a_subscription_limit_is_reported_then_the_next_session_subscribes_less(
    fast_timing: None,
) -> None:
    okx = FakeOkx(Behavior(max_channels=30))
    repository, rest = _Repository(), _Rest(_swap_tickers(120))
    errors: list[BaseException] = []

    async def on_error(component: str, exc: Exception) -> None:
        errors.append(exc)

    def on_ok(component: str) -> None:
        if component == "worker.okx_ws":
            raise _Halt

    async def scenario() -> None:
        async with serving(okx) as url:
            ingestor = _ingestor(url, repository, rest)
            ingestor.ws.batch_size = 100
            await ingestor.ingest_ws_forever(on_error, on_ok)

    with pytest.raises(_Halt):
        _run(scenario())

    assert [len(conn.subscribed) for conn in okx.connections] == [100, 50, 25]
    assert [type(exc) for exc in errors] == [OkxWsSubscriptionLimitError] * 2
    assert "4009" in str(errors[0]) and "subscribing to 50" in str(errors[0])


def test_the_worker_loop_still_stores_what_the_websocket_pushes(fast_timing: None) -> None:
    okx = FakeOkx(Behavior())
    repository, rest = _Repository(), _Rest(_swap_tickers(120))

    def on_ok(component: str) -> None:
        if len(repository.batches) >= 3:
            raise _Halt

    async def scenario() -> None:
        async with serving(okx) as url:
            await _ingestor(url, repository, rest).ingest_ws_forever(None, on_ok)

    with pytest.raises(_Halt):
        _run(scenario())

    assert rest.calls == 1 and len(okx.connections) == 1
    stored = [inst_id for batch in repository.batches for inst_id in batch]
    assert stored[:3] == _busiest(3), "websocket tickers reach the batch write, busiest first"
