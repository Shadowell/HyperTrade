from decimal import ROUND_HALF_UP, Decimal

from hypertrade.paper.models import PaperSignal, PaperTicker, SimulatedFill

MONEY_QUANT = Decimal("0.000000000001")


class PaperSignalEngine:
    def generate(self, tickers: list[PaperTicker], *, max_signals: int) -> list[PaperSignal]:
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
                    )
                )
            elif ticker.change_utc0_pct <= Decimal("-3"):
                candidates.append(
                    PaperSignal(
                        inst_id=ticker.inst_id,
                        side="short",
                        change_utc0_pct=ticker.change_utc0_pct,
                        reason="utc0_change_negative",
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
