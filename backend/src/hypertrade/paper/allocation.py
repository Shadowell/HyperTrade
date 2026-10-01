"""Inverse-volatility risk-parity capital allocator.

Distributes capital across multiple concurrent strategies and instruments
proportional to inverse volatility and conviction, with correlation damping
and hard exposure guardrails.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from hypertrade.paper.models import PaperTicker
from hypertrade.paper.strategies import StrategySignal

MONEY_QUANT = Decimal("0.000000000001")


@dataclass(frozen=True)
class AllocationTarget:
    """Calculated position sizing and parameters for an approved strategy signal."""

    inst_id: str
    side: str
    strategy_key: str
    volatility_est: float
    risk_weight: float
    target_notional: Decimal
    stop_loss_pct: Decimal
    take_profit_pct: Decimal
    conviction: float
    reason: str


@dataclass(frozen=True)
class AllocationPlan:
    """Overall multi-asset risk-parity portfolio distribution."""

    total_equity: Decimal
    allocated_notional: Decimal
    reserve_equity: Decimal
    leverage_ratio: float
    targets: list[AllocationTarget]


class RiskParityAllocator:
    """Computes capital allocation sizing using inverse volatility risk parity."""

    def __init__(
        self,
        *,
        max_leverage: Decimal = Decimal("1.0"),
        max_symbol_notional_pct: Decimal = Decimal("0.25"),
        min_notional_usdt: Decimal = Decimal("10.0"),
        baseline_volatility: float = 0.03,
    ) -> None:
        self.max_leverage = max_leverage
        self.max_symbol_notional_pct = max_symbol_notional_pct
        self.min_notional_usdt = min_notional_usdt
        self.baseline_volatility = baseline_volatility

    def estimate_volatility(
        self,
        ticker: PaperTicker | None,
        klines: list[dict[str, Any]] | None = None,
    ) -> float:
        """Estimate volatility from kline returns standard deviation or 24h change."""
        if klines and len(klines) >= 10:
            closes = [
                float(k.get("close", 0))
                for k in klines
                if float(k.get("close", 0)) > 0
            ]
            if len(closes) >= 10:
                returns = [
                    (closes[i] - closes[i - 1]) / closes[i - 1]
                    for i in range(1, len(closes))
                ]
                mean_ret = sum(returns) / len(returns)
                var = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
                std = math.sqrt(max(1e-8, var))
                return max(0.005, min(0.30, std * math.sqrt(24)))

        if ticker is not None:
            # Approximate 24h return volatility from absolute 24h change
            pct = abs(float(ticker.change_utc0_pct)) / 100.0
            return max(0.01, min(0.30, max(self.baseline_volatility, pct * 0.7)))

        return self.baseline_volatility

    def allocate(
        self,
        *,
        equity: Decimal,
        signals: list[StrategySignal],
        tickers: list[PaperTicker],
        stage_multipliers: dict[str, float] | None = None,
        open_symbols: set[str] | None = None,
        klines_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> AllocationPlan:
        """Calculate risk-parity weights and sizing for pending signals."""
        if equity <= 0 or not signals:
            return AllocationPlan(
                total_equity=equity,
                allocated_notional=Decimal("0"),
                reserve_equity=equity,
                leverage_ratio=0.0,
                targets=[],
            )

        open_set = open_symbols or set()
        active_signals = [s for s in signals if s.inst_id not in open_set]
        if not active_signals:
            return AllocationPlan(
                total_equity=equity,
                allocated_notional=Decimal("0"),
                reserve_equity=equity,
                leverage_ratio=0.0,
                targets=[],
            )

        ticker_map = {t.inst_id: t for t in tickers}
        stage_map = stage_multipliers or {}

        # 1. Compute raw inverse-volatility weights
        raw_weights: list[float] = []
        volatilities: list[float] = []
        for sig in active_signals:
            ticker = ticker_map.get(sig.inst_id)
            klines = klines_by_symbol.get(sig.inst_id) if klines_by_symbol else None
            vol = self.estimate_volatility(ticker, klines)
            volatilities.append(vol)

            # Weight inversely proportional to volatility
            inv_vol = 1.0 / vol

            # Scale by conviction
            conv_scaled = inv_vol * max(0.2, min(1.0, sig.conviction))

            # Scale by progressive stage multiplier
            stage_mult = stage_map.get(sig.strategy_key, 1.0)
            stage_scaled = conv_scaled * max(0.1, min(1.0, stage_mult))

            raw_weights.append(stage_scaled)

        # 2. Cross-asset correlation damping
        # If multiple majors or correlated pairs move in the same direction,
        # apply damping to secondary signals
        damped_weights = list(raw_weights)
        seen_sides: dict[str, int] = {}
        for idx, sig in enumerate(active_signals):
            side = sig.side
            count = seen_sides.get(side, 0)
            if count > 0:
                # Damp subsequent correlated exposure by 15% per additional correlated asset
                damping = 0.85 ** count
                damped_weights[idx] *= damping
            seen_sides[side] = count + 1

        total_weight = sum(damped_weights)
        if total_weight <= 0:
            total_weight = 1.0

        # 3. Size notional capital
        # Available capital = equity * max_leverage
        max_capital = equity * self.max_leverage
        max_per_symbol = equity * self.max_symbol_notional_pct

        targets: list[AllocationTarget] = []
        allocated_sum = Decimal("0")

        for idx, sig in enumerate(active_signals):
            norm_weight = damped_weights[idx] / total_weight
            notional = Decimal(str(round(float(max_capital) * norm_weight, 6)))

            # Bound by max per symbol
            bounded_notional = min(notional, max_per_symbol)

            # Skip dust below minimum notional
            if bounded_notional < self.min_notional_usdt:
                continue

            targets.append(
                AllocationTarget(
                    inst_id=sig.inst_id,
                    side=sig.side,
                    strategy_key=sig.strategy_key,
                    volatility_est=volatilities[idx],
                    risk_weight=norm_weight,
                    target_notional=bounded_notional.quantize(MONEY_QUANT),
                    stop_loss_pct=sig.stop_loss_pct,
                    take_profit_pct=sig.take_profit_pct,
                    conviction=sig.conviction,
                    reason=sig.reason,
                )
            )
            allocated_sum += bounded_notional

        reserve = max(Decimal("0"), equity - allocated_sum)
        leverage = float(allocated_sum / equity) if equity > 0 else 0.0

        return AllocationPlan(
            total_equity=equity,
            allocated_notional=allocated_sum.quantize(MONEY_QUANT),
            reserve_equity=reserve.quantize(MONEY_QUANT),
            leverage_ratio=round(leverage, 4),
            targets=targets,
        )
