"""Position Netting and Smooth Relay Handover Engine.

Solves unnecessary gross turnover churn when a winning challenger strategy (Gen N+1)
succeeds a parent strategy (Gen N). Instead of draining all parent positions and
re-buying all challenger positions, common holdings are retained in-place and only
differential net deltas are rebalanced across smooth execution slices.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from hypertrade.research.a_share_rules import AShareRuleValidator

logger = logging.getLogger("hypertrade.paper.relay_netting")


@dataclass
class PositionHolding:
    """Holding representation for position netting calculation."""

    symbol: str
    qty: Decimal
    price: Decimal = Decimal("0")
    market: str = "cn"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PositionHolding:
        return cls(
            symbol=str(data["symbol"]),
            qty=Decimal(str(data["qty"])),
            price=Decimal(str(data.get("price", "0"))),
            market=str(data.get("market", "cn")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "qty": str(self.qty),
            "price": str(self.price),
            "market": self.market,
        }


@dataclass
class PositionNettingDelta:
    """Detailed netting outcome for a single asset."""

    symbol: str
    parent_qty: Decimal
    challenger_target_qty: Decimal
    net_delta_qty: Decimal
    action: str  # "BUY" | "SELL" | "HOLD"
    retained_qty: Decimal
    price: Decimal
    gross_turnover: Decimal
    net_turnover: Decimal
    turnover_saved: Decimal
    friction_saved: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "parent_qty": str(self.parent_qty),
            "challenger_target_qty": str(self.challenger_target_qty),
            "net_delta_qty": str(self.net_delta_qty),
            "action": self.action,
            "retained_qty": str(self.retained_qty),
            "price": str(self.price),
            "gross_turnover": str(self.gross_turnover),
            "net_turnover": str(self.net_turnover),
            "turnover_saved": str(self.turnover_saved),
            "friction_saved": str(self.friction_saved),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PositionNettingDelta:
        return cls(
            symbol=str(data["symbol"]),
            parent_qty=Decimal(str(data["parent_qty"])),
            challenger_target_qty=Decimal(str(data["challenger_target_qty"])),
            net_delta_qty=Decimal(str(data["net_delta_qty"])),
            action=str(data["action"]),
            retained_qty=Decimal(str(data["retained_qty"])),
            price=Decimal(str(data["price"])),
            gross_turnover=Decimal(str(data["gross_turnover"])),
            net_turnover=Decimal(str(data["net_turnover"])),
            turnover_saved=Decimal(str(data["turnover_saved"])),
            friction_saved=Decimal(str(data["friction_saved"])),
        )


@dataclass
class RelaySliceOrder:
    """Individual trade instruction in a rebalancing slice."""

    symbol: str
    side: str  # "buy" | "sell"
    slice_qty: Decimal
    price: Decimal
    status: str = "pending"  # pending | executed | rejected_limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "slice_qty": str(self.slice_qty),
            "price": str(self.price),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelaySliceOrder:
        return cls(
            symbol=str(data["symbol"]),
            side=str(data["side"]),
            slice_qty=Decimal(str(data["slice_qty"])),
            price=Decimal(str(data["price"])),
            status=str(data.get("status", "pending")),
        )


@dataclass
class RelayHandoverSlice:
    """A batch slice within the smooth rebalancing schedule."""

    slice_index: int
    total_slices: int
    orders: list[RelaySliceOrder]
    executed: bool = False
    executed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_index": self.slice_index,
            "total_slices": self.total_slices,
            "orders": [o.to_dict() for o in self.orders],
            "executed": self.executed,
            "executed_at": self.executed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelayHandoverSlice:
        return cls(
            slice_index=int(data["slice_index"]),
            total_slices=int(data["total_slices"]),
            orders=[RelaySliceOrder.from_dict(o) for o in data.get("orders", [])],
            executed=bool(data.get("executed", False)),
            executed_at=data.get("executed_at"),
        )


@dataclass
class RelayHandoverPlan:
    """Full cryptographic audit plan for a position netting relay handover."""

    plan_id: str
    parent_strategy_id: str | int
    challenger_strategy_id: str | int
    target_id: str = "bitpro"
    state: str = "planned"  # planned | in_progress | completed | aborted
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    overlap_window_hours: int = 24
    slices_total: int = 5
    slices_completed: int = 0
    deltas: list[PositionNettingDelta] = field(default_factory=list)
    slices: list[RelayHandoverSlice] = field(default_factory=list)
    total_gross_turnover: Decimal = Decimal("0")
    total_net_turnover: Decimal = Decimal("0")
    turnover_reduction_ratio: float = 0.0
    total_friction_saved: Decimal = Decimal("0")
    plan_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "parent_strategy_id": self.parent_strategy_id,
            "challenger_strategy_id": self.challenger_strategy_id,
            "target_id": self.target_id,
            "state": self.state,
            "created_at": self.created_at,
            "overlap_window_hours": self.overlap_window_hours,
            "slices_total": self.slices_total,
            "slices_completed": self.slices_completed,
            "deltas": [d.to_dict() for d in self.deltas],
            "slices": [s.to_dict() for s in self.slices],
            "total_gross_turnover": str(self.total_gross_turnover),
            "total_net_turnover": str(self.total_net_turnover),
            "turnover_reduction_ratio": self.turnover_reduction_ratio,
            "total_friction_saved": str(self.total_friction_saved),
            "plan_sha256": self.plan_sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RelayHandoverPlan:
        return cls(
            plan_id=str(data["plan_id"]),
            parent_strategy_id=data["parent_strategy_id"],
            challenger_strategy_id=data["challenger_strategy_id"],
            target_id=str(data.get("target_id", "bitpro")),
            state=str(data.get("state", "planned")),
            created_at=str(data.get("created_at", "")),
            overlap_window_hours=int(data.get("overlap_window_hours", 24)),
            slices_total=int(data.get("slices_total", 5)),
            slices_completed=int(data.get("slices_completed", 0)),
            deltas=[PositionNettingDelta.from_dict(d) for d in data.get("deltas", [])],
            slices=[RelayHandoverSlice.from_dict(s) for s in data.get("slices", [])],
            total_gross_turnover=Decimal(str(data.get("total_gross_turnover", "0"))),
            total_net_turnover=Decimal(str(data.get("total_net_turnover", "0"))),
            turnover_reduction_ratio=float(data.get("turnover_reduction_ratio", 0.0)),
            total_friction_saved=Decimal(str(data.get("total_friction_saved", "0"))),
            plan_sha256=str(data.get("plan_sha256", "")),
        )


class PositionNettingRelayService:
    """Coordinator service managing netting calculations, smooth slicing, and lifecycle."""

    def __init__(self, *, state_file: Path | None = None) -> None:
        self.state_file = (
            state_file if state_file is not None else Path("data/paper_relay_handovers.json")
        )
        self._plans: dict[str, RelayHandoverPlan] = {}
        self._load_plans()

    def _load_plans(self) -> None:
        if not self.state_file.exists():
            return
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    plan = RelayHandoverPlan.from_dict(item)
                    self._plans[plan.plan_id] = plan
        except Exception as exc:
            logger.warning("Failed to load relay handover plans: %s", exc)

    def _persist_plans(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data = [p.to_dict() for p in self._plans.values()]
            self.state_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist relay handover plans: %s", exc)

    def calculate_plan(
        self,
        *,
        parent_strategy_id: str | int,
        challenger_strategy_id: str | int,
        parent_holdings: Sequence[PositionHolding | dict[str, Any]],
        challenger_target_holdings: Sequence[PositionHolding | dict[str, Any]],
        target_id: str = "bitpro",
        overlap_window_hours: int = 24,
        slices_total: int = 5,
        market: str = "cn",
    ) -> RelayHandoverPlan:
        """Calculate netting, turnover reduction, friction savings, and slices."""
        if slices_total < 1:
            slices_total = 1

        p_map: dict[str, PositionHolding] = {}
        for item in parent_holdings:
            h = item if isinstance(item, PositionHolding) else PositionHolding.from_dict(item)
            p_map[h.symbol] = h

        c_map: dict[str, PositionHolding] = {}
        for item in challenger_target_holdings:
            h = item if isinstance(item, PositionHolding) else PositionHolding.from_dict(item)
            c_map[h.symbol] = h

        all_symbols = sorted(set(p_map.keys()) | set(c_map.keys()))
        deltas: list[PositionNettingDelta] = []

        total_gross_turnover = Decimal("0")
        total_net_turnover = Decimal("0")
        total_friction_saved = Decimal("0")

        for sym in all_symbols:
            p_hold = p_map.get(sym)
            c_hold = c_map.get(sym)

            p_qty = p_hold.qty if p_hold else Decimal("0")
            c_qty = c_hold.qty if c_hold else Decimal("0")

            price = Decimal("0")
            if p_hold and p_hold.price > 0:
                price = p_hold.price
            elif c_hold and c_hold.price > 0:
                price = c_hold.price

            # Net delta
            delta_qty = c_qty - p_qty
            if delta_qty > Decimal("0"):
                action = "BUY"
            elif delta_qty < Decimal("0"):
                action = "SELL"
            else:
                action = "HOLD"

            # Retained quantity
            retained_qty = min(p_qty, c_qty) if (p_qty > 0 and c_qty > 0) else Decimal("0")

            gross_turnover = (abs(p_qty) + abs(c_qty)) * price
            net_turnover = abs(delta_qty) * price
            turnover_saved = gross_turnover - net_turnover

            # Saved friction on retained volume (avoiding both selling P and buying C)
            friction_saved = Decimal("0")
            if retained_qty > 0 and price > 0:
                if market == "cn":
                    # In China A-Share:
                    # Avoided round-trip turnover friction:
                    # Stamp duty, transfer fee, commissions & slippage
                    costs = AShareRuleValidator.calculate_friction_costs(
                        buy_turnover=float(retained_qty * price),
                        sell_turnover=float(retained_qty * price),
                    )
                    friction_saved = Decimal(str(costs["total_friction"]))
                else:
                    # Standard 10 bps on round trip
                    friction_saved = (retained_qty * price * Decimal("0.002")).quantize(
                        Decimal("0.01")
                    )

            total_gross_turnover += gross_turnover
            total_net_turnover += net_turnover
            total_friction_saved += friction_saved

            deltas.append(
                PositionNettingDelta(
                    symbol=sym,
                    parent_qty=p_qty,
                    challenger_target_qty=c_qty,
                    net_delta_qty=delta_qty,
                    action=action,
                    retained_qty=retained_qty,
                    price=price,
                    gross_turnover=gross_turnover,
                    net_turnover=net_turnover,
                    turnover_saved=turnover_saved,
                    friction_saved=friction_saved,
                )
            )

        reduction_ratio = 0.0
        if total_gross_turnover > Decimal("0"):
            reduction_ratio = float(
                (total_gross_turnover - total_net_turnover) / total_gross_turnover
            )

        # Build smooth rebalancing slices
        slices = self._build_slices(deltas, slices_total=slices_total, market=market)

        ts_str = int(datetime.now(UTC).timestamp())
        plan_id = f"relay_plan_{parent_strategy_id}_{challenger_strategy_id}_{ts_str}"
        
        # Compute deterministic fingerprint
        fingerprint_data = {
            "plan_id": plan_id,
            "parent": str(parent_strategy_id),
            "challenger": str(challenger_strategy_id),
            "target": target_id,
            "deltas": [d.to_dict() for d in deltas],
            "slices_total": slices_total,
        }
        plan_sha256 = hashlib.sha256(
            json.dumps(fingerprint_data, sort_keys=True).encode("utf-8")
        ).hexdigest()

        plan = RelayHandoverPlan(
            plan_id=plan_id,
            parent_strategy_id=parent_strategy_id,
            challenger_strategy_id=challenger_strategy_id,
            target_id=target_id,
            state="planned",
            created_at=datetime.now(UTC).isoformat(),
            overlap_window_hours=overlap_window_hours,
            slices_total=slices_total,
            slices_completed=0,
            deltas=deltas,
            slices=slices,
            total_gross_turnover=total_gross_turnover,
            total_net_turnover=total_net_turnover,
            turnover_reduction_ratio=round(reduction_ratio, 4),
            total_friction_saved=total_friction_saved.quantize(Decimal("0.01")),
            plan_sha256=plan_sha256,
        )

        self._plans[plan_id] = plan
        self._persist_plans()
        return plan

    def _build_slices(
        self,
        deltas: list[PositionNettingDelta],
        *,
        slices_total: int,
        market: str = "cn",
    ) -> list[RelayHandoverSlice]:
        """Distribute net differential orders across K slices respecting lot size boundaries."""
        slices: list[RelayHandoverSlice] = []

        # Track remaining shares to allocate for each symbol
        remaining_allocations: dict[str, Decimal] = {
            d.symbol: abs(d.net_delta_qty) for d in deltas if d.action in ("BUY", "SELL")
        }

        for idx in range(1, slices_total + 1):
            orders: list[RelaySliceOrder] = []
            is_last_slice = idx == slices_total

            for d in deltas:
                if d.action == "HOLD":
                    continue

                remaining = remaining_allocations[d.symbol]
                if remaining <= Decimal("0"):
                    continue

                slices_left = slices_total - idx + 1
                if is_last_slice:
                    slice_qty = remaining
                else:
                    target_portion = remaining / Decimal(str(slices_left))
                    if market == "cn" and d.action == "BUY":
                        # Down to 100 shares lot size
                        lots = (target_portion / Decimal("100")).quantize(
                            Decimal("1"), rounding=ROUND_DOWN
                        )
                        slice_qty = lots * Decimal("100")
                        if slice_qty <= Decimal("0") and remaining >= Decimal("100"):
                            slice_qty = Decimal("100")
                    else:
                        slice_qty = target_portion.quantize(Decimal("1"), rounding=ROUND_DOWN)

                # Cap at remaining
                if slice_qty > remaining:
                    slice_qty = remaining

                if slice_qty > Decimal("0"):
                    remaining_allocations[d.symbol] -= slice_qty
                    orders.append(
                        RelaySliceOrder(
                            symbol=d.symbol,
                            side=d.action.lower(),
                            slice_qty=slice_qty,
                            price=d.price,
                            status="pending",
                        )
                    )

            slices.append(
                RelayHandoverSlice(
                    slice_index=idx,
                    total_slices=slices_total,
                    orders=orders,
                    executed=False,
                )
            )

        return slices

    def step_slice(
        self,
        plan_id: str,
        *,
        simulate_execution: bool = True,
    ) -> tuple[RelayHandoverSlice | None, RelayHandoverPlan]:
        """Advance the next rebalancing slice in the plan."""
        plan = self._plans.get(plan_id)
        if plan is None:
            raise KeyError(f"Relay handover plan '{plan_id}' not found")

        if plan.slices_completed >= plan.slices_total or plan.state == "completed":
            plan.state = "completed"
            self._persist_plans()
            return None, plan

        plan.state = "in_progress"
        next_slice_idx = plan.slices_completed  # 0-indexed into slices
        current_slice = plan.slices[next_slice_idx]

        if simulate_execution:
            for o in current_slice.orders:
                o.status = "executed"
            current_slice.executed = True
            current_slice.executed_at = datetime.now(UTC).isoformat()

        plan.slices_completed += 1
        if plan.slices_completed >= plan.slices_total:
            plan.state = "completed"

        self._persist_plans()
        return current_slice, plan

    def get_plan(self, plan_id: str) -> RelayHandoverPlan | None:
        return self._plans.get(plan_id)

    def find_plan_by_pair(
        self,
        parent_strategy_id: str | int,
        challenger_strategy_id: str | int,
    ) -> RelayHandoverPlan | None:
        """Find the most recent plan for a specific strategy pair."""
        pid_str = str(parent_strategy_id)
        cid_str = str(challenger_strategy_id)
        matched = [
            p
            for p in self._plans.values()
            if str(p.parent_strategy_id) == pid_str
            and str(p.challenger_strategy_id) == cid_str
        ]
        if not matched:
            return None
        matched.sort(key=lambda p: p.created_at, reverse=True)
        return matched[0]

    def list_plans(self) -> list[RelayHandoverPlan]:
        return sorted(self._plans.values(), key=lambda p: p.created_at, reverse=True)
