"""Market target contracts.

A market target describes one external strategy platform HyperTrade can run
its governed evolution loop against (BitPro today, QuantLab and other
MCP-speaking platforms later). The profile below is the declarative boundary:
everything the evolution core would otherwise hardcode — venue vocabulary,
trading calendar, evidence contracts, cost policy sources, identity format —
is declared here by the target instead of being assumed by the core.
"""

from __future__ import annotations

from datetime import time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

TargetTransport = Literal["bitpro_mcp_v1", "mcp_contract_v1"]
TargetIdFormat = Literal["integer", "string"]


class TargetCalendarV1(BaseModel):
    """Trading calendar the evidence gates align to.

    ``continuous`` keeps the 24/7 crypto semantics: windows are whole UTC (or
    ``timezone``) days and every day trades. ``sessions`` declares an
    exchange-style calendar so equity-market targets can reuse the same gates
    without the core assuming round-the-clock trading.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["continuous", "sessions"] = "continuous"
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    evidence_window_days: int = Field(default=14, ge=1, le=90)
    evidence_bucket_seconds: int = Field(default=3600, ge=60, le=86400)
    session_open: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    session_close: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    # 0 = Monday .. 6 = Sunday; empty means every day trades.
    trading_days: tuple[int, ...] = Field(default=())

    @model_validator(mode="after")
    def validate_session_calendar(self) -> TargetCalendarV1:
        if self.mode == "sessions":
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("session timezone must be an IANA zone") from exc
            if not self.session_open or not self.session_close:
                raise ValueError("session open and close are required")
            try:
                if time.fromisoformat(self.session_open) >= time.fromisoformat(self.session_close):
                    raise ValueError("session open must precede close")
            except ValueError as exc:
                raise ValueError("invalid session hours") from exc
            if self.evidence_window_days != 14:
                raise ValueError("sessions evidence requires exactly 14 trading days")
            if any(day < 0 or day > 6 for day in self.trading_days):
                raise ValueError("trading_days must use weekday numbers 0..6")
        return self


class TargetCapabilitiesV1(BaseModel):
    """Which governed operations the target's contract actually supports.

    Capability flags gate features, never permissions: a disabled capability
    makes the evolution loop skip that evidence source instead of guessing.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    running_inventory: bool = True
    session_snapshot: bool = True
    return_series: bool = True
    session_trades: bool = True
    execution_ledger: bool = True
    backtest: bool = True
    paper_launch: bool = True
    cost_identity: bool = True
    live_preflight: bool = False


class MarketTargetProfileV1(BaseModel):
    """Declarative identity of one pluggable strategy platform."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["market_target.v1"] = "market_target.v1"
    target_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    display_name: str = Field(min_length=1, max_length=120)
    transport: TargetTransport
    tool_contract: str | None = Field(default=None, max_length=64)
    venue: str | None = Field(default=None, max_length=32)
    market_type: str | None = Field(default=None, max_length=32)
    quote_currency: str | None = Field(default=None, max_length=16)
    strategy_id_format: TargetIdFormat = "integer"
    calendar: TargetCalendarV1 = Field(default_factory=TargetCalendarV1)
    evidence_contracts: tuple[str, ...] = ()
    cost_policy_sources: tuple[str, ...] = ()
    capabilities: TargetCapabilitiesV1 = Field(default_factory=TargetCapabilitiesV1)
