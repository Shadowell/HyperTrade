"""Read-only target boundary for the evolution scanner."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from hypertrade.arc.observation import _snapshot_body
from hypertrade.targets.ports import (
    EquityPoint,
    Fill,
    SeriesPage,
    SessionSnapshot,
    StrategyHandle,
    StrategySource,
)


def read_ports(client: Any) -> Any:
    """Accept an explicit read-port implementation or adapt the BitPro contract."""
    if all(
        callable(getattr(client, name, None))
        for name in (
            "list_running_strategies",
            "inventory_coverage",
            "get_strategy_source",
            "get_session_snapshot",
            "list_fills",
            "read_equity_series",
        )
    ):
        return client
    return BitProReadPorts(client)


class SnapshotContractError(ValueError):
    """A snapshot response arrived but failed the read-port contract."""


class BitProReadPorts:
    def __init__(self, client: Any) -> None:
        self.client = client
        self._total = 0
        self._unavailable: tuple[StrategyHandle, ...] = ()

    def list_running_strategies(self, limit: int) -> list[StrategyHandle]:
        raw = self.client.paper_strategy_performance(limit=limit)
        rows = raw.get("strategies", [])
        self._total = int(raw.get("performance_summary", {}).get("reported_total", len(rows)))
        self._unavailable = tuple(
            StrategyHandle(
                strategy_id=str(row.get("strategy_id") or ""),
                name=str(row.get("strategy_name") or ""),
                timeframe=str(row.get("timeframe") or ""),
                mode=str(row.get("mode") or ""),
                unavailable_reason=str(row.get("reason") or "unavailable"),
            )
            for row in raw.get("unavailable_strategies", [])
        )
        return [
            StrategyHandle(
                strategy_id=str(row["strategy_id"]),
                name=str(row.get("strategy_name") or ""),
                timeframe=str(row.get("timeframe") or ""),
                mode=str(row.get("mode") or ""),
            )
            for row in rows
        ]

    def inventory_coverage(self) -> tuple[int, tuple[StrategyHandle, ...]]:
        return self._total, self._unavailable

    def get_strategy_source(self, strategy_id: str) -> StrategySource:
        raw = self.client.strategy_get(strategy_id=int(strategy_id)).get("strategy", {})
        actual_id = raw.get("id", raw.get("strategy_id"))
        if actual_id is None or str(actual_id) != str(strategy_id):
            raise ValueError("strategy_source_identity_mismatch")
        code = raw.get("script_content")
        config = raw.get("config") or {}
        if not isinstance(code, str) or not isinstance(config, dict):
            raise ValueError("strategy source contract invalid")
        return StrategySource(
            strategy_id=str(actual_id),
            code=code,
            code_sha256=hashlib.sha256(code.encode()).hexdigest(),
            config=config,
            symbols=tuple(raw.get("symbols") or ()),
            timeframe=str(config.get("timeframe") or ""),
        )

    def get_session_snapshot(
        self, *, strategy_id: str | None = None, instance_id: str | None = None
    ) -> SessionSnapshot:
        payload = self.client.paper_snapshot(
            strategy_id=int(strategy_id) if strategy_id is not None else None,
            instance_id=instance_id,
        )
        raw = _snapshot_body(payload)
        if (strategy_id is not None and str(raw.get("strategy_id")) != strategy_id) or (
            instance_id is not None and str(raw.get("instance_id")) != instance_id
        ):
            raise SnapshotContractError("session_snapshot_identity_mismatch")
        try:
            started = (raw.get("session") or {}).get("started_at")
            return SessionSnapshot(
                instance_id=str(raw.get("instance_id") or ""),
                strategy_id=str(raw.get("strategy_id") or ""),
                strategy_version=raw.get("strategy_version"),
                config_version=raw.get("config_version"),
                status=str(raw.get("status") or ""),
                trade_count=int(raw.get("trade_count") or 0),
                session_started_at=(
                    datetime.fromisoformat(started.replace("Z", "+00:00")) if started else None
                ),
                symbols=tuple((raw.get("strategy") or {}).get("symbols") or ()),
                source=raw,
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise SnapshotContractError("session_snapshot_contract_mismatch") from exc

    def list_fills(
        self, strategy_id: str, *, limit: int, since_ms: int | None = None
    ) -> list[Fill]:
        rows = self.client.strategy_trades(strategy_id=int(strategy_id), limit=limit)
        return [
            Fill(
                fill_id=str(row.get("id") or ""),
                ts_ms=int(row["timestamp"]),
                symbol=str(row.get("symbol") or ""),
                side=str(row.get("side") or ""),
                order_type=row.get("type"),
                price=float(row["price"]) if row.get("price") is not None else None,
                qty=float(row["quantity"]) if row.get("quantity") is not None else None,
                fee=float(row["fee"]) if row.get("fee") is not None else None,
                pnl=float(row["pnl"]) if row.get("pnl") is not None else None,
                strategy_id=str(row.get("strategy_id") or ""),
            )
            for row in rows
            if since_ms is None or int(row["timestamp"]) >= since_ms
        ]

    def read_equity_series(
        self,
        instance_id: str,
        *,
        start_ms: int,
        end_ms: int,
        bucket_seconds: int,
        limit: int,
    ) -> SeriesPage:
        raw = self.client.strategy_return_series(
            source_layer="paper",
            source_id=instance_id,
            start_at=datetime.fromtimestamp(start_ms / 1000, UTC).isoformat(),
            end_at=datetime.fromtimestamp(end_ms / 1000, UTC).isoformat(),
            bucket_seconds=bucket_seconds,
            limit=limit,
        )
        if (
            raw.get("schema_version") != "strategy_return_series.v1"
            or raw.get("source_layer") != "paper"
            or raw.get("source_id") != instance_id
            or raw.get("bucket_seconds") != bucket_seconds
        ):
            raise ValueError("incomplete_or_mismatched_series_contract")
        return SeriesPage(
            points=tuple(
                EquityPoint(
                    ts_ms=int(
                        datetime.fromisoformat(
                            point["timestamp"].replace("Z", "+00:00")
                        ).timestamp()
                        * 1000
                    ),
                    equity=float(point["equity"]),
                )
                for point in raw.get("points", [])
            ),
            source_hash=str(raw.get("source_hash") or ""),
            content_hash=str(raw.get("content_hash") or ""),
            complete=not bool((raw.get("pagination") or {}).get("next_cursor")),
            next_cursor=(raw.get("pagination") or {}).get("next_cursor"),
            data_gaps=tuple(raw.get("data_gaps") or ()),
            strategy_id=str(raw.get("strategy_id") or ""),
            strategy_version=raw.get("strategy_version"),
            config_version=raw.get("config_version"),
            currency=raw.get("currency"),
            cost_model=raw.get("cost_model"),
            timezone=raw.get("timezone"),
            raw=raw,
        )
