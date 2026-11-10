import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class OkxTicker:
    inst_id: str
    inst_type: str
    last: Decimal
    volume_ccy_24h: Decimal
    change_utc0_pct: Decimal
    raw: dict[str, Any]


@dataclass(frozen=True)
class OkxCandle:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    volume_ccy: Decimal
    volume_ccy_quote: Decimal
    confirmed: bool
    raw: list[Any]


def _decimal(value: object, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _pct(last: Decimal, baseline: Decimal) -> Decimal:
    if baseline == 0:
        return Decimal("0")
    return ((last - baseline) / baseline * Decimal("100")).quantize(
        Decimal("0.001"), rounding=ROUND_DOWN
    )


def parse_okx_ticker(payload: dict[str, Any]) -> OkxTicker:
    last = _decimal(payload.get("last"))
    sod_utc0 = _decimal(payload.get("sodUtc0"))
    return OkxTicker(
        inst_id=str(payload.get("instId", "")),
        inst_type=str(payload.get("instType", "SWAP") or "SWAP"),
        last=last,
        volume_ccy_24h=_decimal(payload.get("volCcy24h", payload.get("vol24h", "0"))),
        change_utc0_pct=_pct(last, sod_utc0),
        raw=dict(payload),
    )


def parse_okx_candle(payload: list[Any]) -> OkxCandle:
    return OkxCandle(
        open_time=datetime.fromtimestamp(int(str(payload[0])) / 1000, tz=UTC),
        open=_decimal(payload[1]),
        high=_decimal(payload[2]),
        low=_decimal(payload[3]),
        close=_decimal(payload[4]),
        volume=_decimal(payload[5]),
        volume_ccy=_decimal(payload[6]),
        volume_ccy_quote=_decimal(payload[7]),
        confirmed=str(payload[8]) == "1",
        raw=list(payload),
    )


# --- public websocket protocol ------------------------------------------------------------
#
# Checked against the OKX API v5 documentation (WebSocket overview and "WS / Tickers channel",
# snapshot of 2026-11-09) and its change log ("WebSocket port 8443 discontinuation", updated
# 2026-10-22).

_WS_RETIRED_PORT = 8443
WS_TICKERS_CHANNEL = "tickers"


def normalize_okx_ws_url(url: str) -> str:
    """Drop the retired `:8443` from an OKX websocket URL.

    OKX stopped accepting websocket connections on port 8443 on 2026-10-31 (Colo: 2026-11-16):
    `wss://ws.okx.com:8443/ws/v5/public` is now `wss://ws.okx.com/ws/v5/public`, the same host
    and path on the default port 443. `.env.example` and the settings default used to carry the
    8443 form, so a deployed `.env` can still hold it. Only OKX hosts are rewritten; a local test
    server or a proxy that listens on 8443 is left alone.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return url
    host = parts.hostname or ""
    on_okx = host == "okx.com" or host.endswith(".okx.com")
    if port != _WS_RETIRED_PORT or not on_okx or "@" in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc=host))


def rank_swap_inst_ids(tickers: Iterable[OkxTicker], limit: int) -> list[str]:
    """The `limit` busiest instruments by 24h turnover (last x volCcy24h), busiest first.

    `volCcy24h` of a derivative is an amount of the base currency, so multiplied by the last price
    it is comparable across USDT, USDC and coin-margined contracts. Ties and untraded instruments
    (turnover 0) fall back to the instrument id, which keeps the choice deterministic.
    """
    unique = {ticker.inst_id: ticker for ticker in tickers if ticker.inst_id}
    ranked = sorted(unique.values(), key=lambda t: (-(t.last * t.volume_ccy_24h), t.inst_id))
    return [ticker.inst_id for ticker in ranked[: max(limit, 0)]]


def ticker_subscribe_requests(inst_ids: Sequence[str], batch_size: int) -> list[dict[str, Any]]:
    """Subscribe messages for the public `tickers` channel, `batch_size` instruments each.

    The channel is subscribed per instrument: its arguments are `channel` and `instId`, and
    `instType` is not one of them (OKX documents no way to subscribe `tickers` for a whole
    instrument type). A request may carry many arguments as long as its total length stays under
    64 KB; the only rate limit is 480 subscribe/unsubscribe/login requests per connection per hour.
    The request `id` is alphanumeric, as the documentation requires, and OKX echoes it back.
    """
    size = max(batch_size, 1)
    return [
        {
            "id": f"sub{number}",
            "op": "subscribe",
            "args": [
                {"channel": WS_TICKERS_CHANNEL, "instId": inst_id}
                for inst_id in inst_ids[start : start + size]
            ],
        }
        for number, start in enumerate(range(0, len(inst_ids), size), start=1)
    ]


@dataclass(frozen=True)
class WsFrame:
    kind: Literal["tickers", "pong", "ack", "error", "notice", "malformed", "ignored"]
    code: str = ""
    message: str = ""
    tickers: tuple[OkxTicker, ...] = ()


def parse_okx_ws_frame(raw: str | bytes) -> WsFrame:
    """Classify one frame received on the public websocket.

    OKX answers the text `ping` with the bare text `pong` (not JSON), acknowledges each subscribed
    argument with `{"event": "subscribe", ...}`, reports a refused request as
    `{"event": "error", "code": ..., "msg": ...}`, announces its own restarts as
    `{"event": "notice", "code": "64008", ...}` and pushes data as `{"arg": ..., "data": [...]}`.
    A frame this does not understand is never an exception: one odd frame must not drop a
    healthy connection.
    """
    if isinstance(raw, bytes):
        return WsFrame("ignored")  # binary frames belong to the SBE channels, which are not used
    if raw == "pong":
        return WsFrame("pong")
    try:
        payload = json.loads(raw)
    except ValueError:
        return WsFrame("malformed", message=raw[:200])
    if not isinstance(payload, dict):
        return WsFrame("malformed", message=raw[:200])
    event = payload.get("event")
    if event in ("error", "notice"):
        return WsFrame(
            event,
            code=str(payload.get("code", "")),
            message=str(payload.get("msg", "")),
        )
    if event is not None:
        return WsFrame("ack")
    arg = payload.get("arg")
    channel = arg.get("channel") if isinstance(arg, dict) else WS_TICKERS_CHANNEL
    data = payload.get("data")
    if channel != WS_TICKERS_CHANNEL or not isinstance(data, list):
        return WsFrame("ignored")
    return WsFrame(
        "tickers",
        tickers=tuple(
            parse_okx_ticker(item) for item in data if isinstance(item, dict) and item.get("instId")
        ),
    )
