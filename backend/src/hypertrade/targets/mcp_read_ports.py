"""Synchronous typed read ports backed by the standard async MCP registry."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from hypertrade.connectors.mcp_client import run_async
from hypertrade.targets.mcp_contract import (
    MARKET_EVOLUTION_CONTRACT_V1,
    McpContractClient,
)
from hypertrade.targets.ports import (
    EquityPoint,
    Fill,
    SeriesPage,
    SessionCalendarEvidence,
    SessionSnapshot,
    StrategyHandle,
    StrategySource,
)
from hypertrade.targets.registry import MarketTargetUnavailable


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name}_must_be_object")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{name}_missing_or_invalid")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{name}_invalid")
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"{name}_invalid") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name}_invalid")
    return result


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name}_invalid")
    return value


def _strategy_code(value: Any) -> str:
    # Match the existing research discovery strategy_code contract; a tool's
    # generic identifier bound would reject ordinary source files.
    if not isinstance(value, str) or not value.strip() or len(value) > 100_000:
        raise ValueError("strategy_code_missing_or_out_of_bounds")
    return value


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError(f"{name}_invalid")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{name}_invalid") from exc
    if not result.is_finite():
        raise ValueError(f"{name}_invalid")
    return result


class McpReadPorts:
    """Only read capabilities; no Paper configuration or order methods exist here."""

    def __init__(self, client: McpContractClient) -> None:
        report = run_async(client.preflight_read())
        if not report.ok:
            raise MarketTargetUnavailable(
                f"market target {client.profile.target_id!r} read tools unavailable: "
                + ", ".join((*report.missing, *report.errors))
            )
        self.client = client
        self._total = 0
        self._unavailable: tuple[StrategyHandle, ...] = ()

    def _call(self, capability: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payload = _object(run_async(self.client.call_canonical(capability, arguments)), capability)
        if (
            payload.get("schema_version") != MARKET_EVOLUTION_CONTRACT_V1
            or payload.get("target_id") != self.client.profile.target_id
        ):
            raise ValueError("mcp_read_contract_or_target_mismatch")
        return payload

    def list_running_strategies(self, limit: int) -> list[StrategyHandle]:
        payload = self._call("list_running_strategies", {"limit": limit})
        rows = payload.get("strategies")
        unavailable = payload.get("unavailable_strategies", [])
        if not isinstance(rows, list) or not isinstance(unavailable, list):
            raise ValueError("mcp_inventory_invalid")

        def handle(row: Any, *, unavailable_row: bool = False) -> StrategyHandle:
            item = _object(row, "strategy")
            return StrategyHandle(
                strategy_id=_text(item.get("strategy_id"), "strategy_id"),
                name=_text(item.get("name"), "strategy_name"),
                timeframe=_text(item.get("timeframe"), "timeframe"),
                mode=_text(item.get("mode"), "mode"),
                symbols=tuple(_text(value, "symbol") for value in item.get("symbols", [])),
                unavailable_reason=(
                    _text(item.get("reason"), "reason") if unavailable_row else None
                ),
            )

        result = [handle(row) for row in rows]
        self._unavailable = tuple(handle(row, unavailable_row=True) for row in unavailable)
        self._total = _integer(payload.get("reported_total"), "reported_total")
        if self._total < len(result):
            raise ValueError("mcp_inventory_total_invalid")
        return result

    def inventory_coverage(self) -> tuple[int, tuple[StrategyHandle, ...]]:
        return self._total, self._unavailable

    def get_strategy_source(self, strategy_id: str) -> StrategySource:
        payload = self._call("get_strategy_source", {"strategy_id": strategy_id})
        if payload.get("strategy_id") != strategy_id:
            raise ValueError("strategy_source_identity_mismatch")
        code = _strategy_code(payload.get("code"))
        code_hash = _text(payload.get("code_sha256"), "code_sha256")
        if hashlib.sha256(code.encode()).hexdigest() != code_hash:
            raise ValueError("strategy_source_hash_mismatch")
        config = _object(payload.get("config"), "strategy_config")
        symbols = payload.get("symbols")
        if not isinstance(symbols, list) or not symbols:
            raise ValueError("strategy_symbols_missing")
        return StrategySource(
            strategy_id=strategy_id,
            code=code,
            code_sha256=code_hash,
            config=config,
            symbols=tuple(_text(value, "symbol") for value in symbols),
            timeframe=_text(payload.get("timeframe"), "timeframe"),
            strategy_version=payload.get("strategy_version"),
            config_version=payload.get("config_version"),
        )

    def get_session_snapshot(
        self, *, strategy_id: str | None = None, instance_id: str | None = None
    ) -> SessionSnapshot:
        payload = self._call(
            "get_session_snapshot",
            {"strategy_id": strategy_id, "instance_id": instance_id},
        )
        actual_strategy = _text(payload.get("strategy_id"), "strategy_id")
        actual_instance = _text(payload.get("instance_id"), "instance_id")
        if (strategy_id and actual_strategy != strategy_id) or (
            instance_id and actual_instance != instance_id
        ):
            raise ValueError("session_snapshot_identity_mismatch")
        started = datetime.fromisoformat(
            _text(payload.get("session_started_at"), "session_started_at").replace("Z", "+00:00")
        )
        if started.tzinfo is None:
            raise ValueError("session_start_missing_timezone")
        symbols = payload.get("symbols")
        if not isinstance(symbols, list) or not symbols:
            raise ValueError("session_symbols_missing")
        return SessionSnapshot(
            instance_id=actual_instance,
            strategy_id=actual_strategy,
            strategy_version=_text(payload.get("strategy_version"), "strategy_version"),
            config_version=_text(payload.get("config_version"), "config_version"),
            status=_text(payload.get("status"), "status"),
            trade_count=_integer(payload.get("trade_count"), "trade_count"),
            session_started_at=started,
            symbols=tuple(_text(value, "symbol") for value in symbols),
            timeframe=payload.get("timeframe"),
        )

    def list_fills(
        self, strategy_id: str, *, limit: int, since_ms: int | None = None
    ) -> list[Fill]:
        payload = self._call(
            "list_session_trades", {"strategy_id": strategy_id, "limit": limit, "since": since_ms}
        )
        rows = payload.get("fills")
        if not isinstance(rows, list):
            raise ValueError("mcp_fills_invalid")
        fills = []
        for row in rows:
            item = _object(row, "fill")
            if item.get("strategy_id") != strategy_id:
                raise ValueError("fill_strategy_identity_mismatch")
            fills.append(
                Fill(
                    fill_id=_text(item.get("fill_id"), "fill_id"),
                    ts_ms=_integer(item.get("ts_ms"), "fill_timestamp"),
                    symbol=_text(item.get("symbol"), "fill_symbol"),
                    side=_text(item.get("side"), "fill_side"),
                    price=_number(item["price"], "fill_price")
                    if item.get("price") is not None
                    else None,
                    qty=_number(item["qty"], "fill_qty") if item.get("qty") is not None else None,
                    fee=_number(item["fee"], "fill_fee") if item.get("fee") is not None else None,
                    pnl=_number(item["pnl"], "fill_pnl") if item.get("pnl") is not None else None,
                    order_type=item.get("order_type"),
                    strategy_id=strategy_id,
                )
            )
        return fills

    def read_equity_series(
        self, instance_id: str, *, start_ms: int, end_ms: int, bucket_seconds: int, limit: int
    ) -> SeriesPage:
        payload = self._call(
            "read_equity_series",
            {
                "instance_id": instance_id,
                "start": start_ms,
                "end": end_ms,
                "bucket_seconds": bucket_seconds,
                "limit": limit,
            },
        )
        if payload.get("instance_id") != instance_id:
            raise ValueError("equity_series_instance_mismatch")
        rows = payload.get("points")
        gaps = payload.get("data_gaps", [])
        if not isinstance(rows, list) or not isinstance(gaps, list):
            raise ValueError("mcp_equity_series_invalid")
        return SeriesPage(
            points=tuple(
                EquityPoint(
                    ts_ms=_integer(_object(row, "equity_point").get("ts_ms"), "point_timestamp"),
                    equity=_decimal(row.get("equity"), "equity"),
                    trading_day=row.get("trading_day"),
                )
                for row in rows
            ),
            source_hash=_text(payload.get("source_hash"), "source_hash"),
            content_hash=_text(payload.get("content_hash"), "content_hash"),
            complete=payload.get("complete") is True,
            data_gaps=tuple(_text(value, "data_gap") for value in gaps),
            next_cursor=payload.get("next_cursor"),
            strategy_id=_text(payload.get("strategy_id"), "strategy_id"),
            strategy_version=_text(payload.get("strategy_version"), "strategy_version"),
            config_version=_text(payload.get("config_version"), "config_version"),
            currency=_text(payload.get("currency"), "currency"),
            cost_model=_object(payload.get("cost_model"), "cost_model"),
            timezone=_text(payload.get("timezone"), "timezone"),
        )

    def list_trading_sessions(self, *, start_date: str, end_date: str) -> SessionCalendarEvidence:
        payload = self._call(
            "list_trading_sessions", {"start_date": start_date, "end_date": end_date}
        )
        dates = payload.get("trading_dates")
        if not isinstance(dates, list):
            raise ValueError("mcp_trading_dates_invalid")
        return SessionCalendarEvidence(
            timezone=_text(payload.get("timezone"), "timezone"),
            start_date=_text(payload.get("start_date"), "start_date"),
            end_date=_text(payload.get("end_date"), "end_date"),
            trading_dates=tuple(_text(value, "trading_day") for value in dates),
            source_hash=_text(payload.get("source_hash"), "calendar_source_hash"),
            complete=payload.get("complete") is True,
        )
