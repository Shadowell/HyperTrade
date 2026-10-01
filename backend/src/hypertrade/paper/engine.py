from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from hypertrade.paper.models import PaperSignal, PaperTicker, SimulatedFill
from hypertrade.paper.strategies import MultiStrategySignalEngine

MONEY_QUANT = Decimal("0.000000000001")


class PaperSignalEngine:
    """Production signal engine coordinating multi-strategy and legacy signals."""

    def __init__(
        self,
        multi_engine: MultiStrategySignalEngine | None = None,
        *,
        use_multi_strategy: bool = True,
    ) -> None:
        self.multi_engine = multi_engine
        self.use_multi_strategy = use_multi_strategy

    def generate(
        self,
        tickers: list[PaperTicker],
        *,
        max_signals: int,
        klines_by_symbol: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[PaperSignal]:
        ticker_map = {t.inst_id: t for t in tickers}

        if self.use_multi_strategy:
            engine = self.multi_engine or MultiStrategySignalEngine()
            strat_signals = engine.generate(
                tickers,
                klines_by_symbol=klines_by_symbol,
                max_signals=max_signals,
            )
            converted: list[PaperSignal] = []
            for sig in strat_signals:
                ticker = ticker_map.get(sig.inst_id)
                change = ticker.change_utc0_pct if ticker else Decimal("0")
                converted.append(
                    PaperSignal(
                        inst_id=sig.inst_id,
                        side=sig.side,
                        change_utc0_pct=change,
                        reason=sig.reason,
                        strategy_key=sig.strategy_key,
                        conviction=sig.conviction,
                        stop_loss_pct=sig.stop_loss_pct,
                        take_profit_pct=sig.take_profit_pct,
                    )
                )
            if converted:
                return converted[:max_signals]

        # Fallback to direct UTC-0 momentum scan
        candidates: list[PaperSignal] = []
        for ticker in tickers:
            if ticker.last <= 0 or ticker.volume_ccy_24h <= 0:
                continue
            if ticker.change_utc0_pct >= Decimal("3"):
                candidates.append(
                    PaperSignal(
                        inst_id=ticker.inst_id,
                        side="long",
                        change_utc0_pct=ticker.change_utc0_pct,
                        reason="utc0_change_positive",
                        strategy_key="utc0_momentum_legacy",
                        conviction=min(1.0, float(ticker.change_utc0_pct / Decimal("10"))),
                    )
                )
            elif ticker.change_utc0_pct <= Decimal("-3"):
                candidates.append(
                    PaperSignal(
                        inst_id=ticker.inst_id,
                        side="short",
                        change_utc0_pct=ticker.change_utc0_pct,
                        reason="utc0_change_negative",
                        strategy_key="utc0_momentum_legacy",
                        conviction=min(1.0, float(abs(ticker.change_utc0_pct) / Decimal("10"))),
                    )
                )
        candidates.sort(
            key=lambda signal: (
                abs(signal.change_utc0_pct),
                next(
                    ticker.volume_ccy_24h
                    for ticker in tickers
                    if ticker.inst_id == signal.inst_id
                ),
            ),
            reverse=True,
        )
        return candidates[:max_signals]


class PaperExecutionEngine:
    def __init__(self, *, taker_fee_bps: Decimal, slippage_bps: Decimal) -> None:
        self.taker_fee_bps = taker_fee_bps
        self.slippage_bps = slippage_bps

    def simulate_fill(
        self,
        *,
        inst_id: str,
        side: str,
        target_notional: Decimal,
        last_price: Decimal,
    ) -> SimulatedFill:
        if side not in {"long", "short"}:
            raise ValueError(f"Unsupported paper side: {side}")
        slippage_ratio = self.slippage_bps / Decimal("10000")
        multiplier = (
            Decimal("1") + slippage_ratio
            if side == "long"
            else Decimal("1") - slippage_ratio
        )
        price = _quantize(last_price * multiplier)
        quantity = _quantize(target_notional / price)
        fee = _quantize(target_notional * self.taker_fee_bps / Decimal("10000"))
        return SimulatedFill(
            inst_id=inst_id,
            side=side,
            quantity=quantity,
            price=price,
            fee=fee,
            slippage_bps=self.slippage_bps,
        )


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
