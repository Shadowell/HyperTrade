from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PaperTicker:
    inst_id: str
    last: Decimal
    volume_ccy_24h: Decimal
    change_utc0_pct: Decimal


@dataclass(frozen=True)
class PaperSignal:
    inst_id: str
    side: str
    change_utc0_pct: Decimal
    reason: str


@dataclass(frozen=True)
class SimulatedFill:
    inst_id: str
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    slippage_bps: Decimal


@dataclass(frozen=True)
class PaperSessionSnapshot:
    id: str
    status: str
    cash: str
    equity: str
    realized_pnl: str = "0"


@dataclass(frozen=True)
class PaperRunResult:
    status: str
    fill_count: int
    event_count: int
