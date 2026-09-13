"""Typed platform ports for the evolution core (Phase 2 contract).

These Protocols are the target-agnostic boundary the evolution loop will
consume directly: ``StrategySourcePort``, ``PaperSessionPort``, ``EvidencePort``
and ``PaperProvisionPort``. Today the loop reaches BitPro through
``BitProToolAdapter`` and its narrow injected protocols; this module freezes the
canonical shapes so a second target (QuantLab over the standard MCP contract)
can be adapted mechanically rather than by re-deriving field names.

Nothing here performs I/O or registration — implementations live with each
target (``hypertrade.targets.bitpro`` / ``hypertrade.targets.mcp_contract``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class StrategyHandle:
    strategy_id: str
    name: str
    timeframe: str
    mode: str
    symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategySource:
    strategy_id: str
    code: str
    code_sha256: str
    config: dict[str, Any]
    symbols: tuple[str, ...]
    timeframe: str
    strategy_version: str | None = None
    config_version: str | None = None
    runtime_history: bool = False


@dataclass(frozen=True)
class SessionSnapshot:
    instance_id: str
    strategy_id: str
    strategy_version: str | None
    config_version: str | None
    status: str
    trade_count: int
    session_started_at: datetime | None
    symbols: tuple[str, ...] = ()
    timeframe: str | None = None
    equity: float | None = None


@dataclass(frozen=True)
class Fill:
    fill_id: str
    ts_ms: int
    symbol: str
    side: str
    price: float
    qty: float
    fee: float | None = None
    pnl: float | None = None


@dataclass(frozen=True)
class EquityPoint:
    ts_ms: int
    equity: float


@dataclass(frozen=True)
class SeriesPage:
    points: tuple[EquityPoint, ...]
    source_hash: str
    content_hash: str
    complete: bool
    data_gaps: tuple[str, ...] = ()
    next_cursor: str | None = None


@runtime_checkable
class StrategySourcePort(Protocol):
    def list_running_strategies(self, limit: int) -> list[StrategyHandle]: ...

    def get_strategy_source(self, strategy_id: str) -> StrategySource: ...


@runtime_checkable
class PaperSessionPort(Protocol):
    def get_session_snapshot(
        self, *, strategy_id: str | None = None, instance_id: str | None = None
    ) -> SessionSnapshot: ...


@runtime_checkable
class EvidencePort(Protocol):
    def list_fills(
        self, strategy_id: str, *, limit: int, since_ms: int | None = None
    ) -> list[Fill]: ...

    def read_equity_series(
        self,
        instance_id: str,
        *,
        start_ms: int,
        end_ms: int,
        bucket_seconds: int,
        limit: int,
    ) -> SeriesPage: ...


@runtime_checkable
class PaperProvisionPort(Protocol):
    def configure_paper(self, candidate_key: str, **fields: Any) -> dict[str, Any]: ...

    def start_paper(self, candidate_key: str, **fields: Any) -> dict[str, Any]: ...
