"""
ARC High-Order Microstructure Alpha Factor Library
(OFI, VOI, Funding Arbitrage & Liquidation Cascade)
"""

from typing import Any


def compute_order_flow_imbalance(
    best_bid_prices: list[float],
    best_bid_volumes: list[float],
    best_ask_prices: list[float],
    best_ask_volumes: list[float],
) -> float:
    """
    Computes Order Flow Imbalance (OFI) across consecutive orderbook snapshots.
    OFI > 0 indicates net buying pressure; OFI < 0 indicates net selling pressure.
    """
    if len(best_bid_prices) < 2 or len(best_ask_prices) < 2:
        return 0.0

    ofi_sum = 0.0
    for i in range(1, len(best_bid_prices)):
        # Bid side delta (e_bid)
        if best_bid_prices[i] > best_bid_prices[i - 1]:
            e_bid = best_bid_volumes[i]
        elif best_bid_prices[i] == best_bid_prices[i - 1]:
            e_bid = best_bid_volumes[i] - best_bid_volumes[i - 1]
        else:
            e_bid = 0.0

        # Ask side delta (e_ask)
        if best_ask_prices[i] < best_ask_prices[i - 1]:
            e_ask = best_ask_volumes[i]
        elif best_ask_prices[i] == best_ask_prices[i - 1]:
            e_ask = best_ask_volumes[i] - best_ask_volumes[i - 1]
        else:
            e_ask = 0.0

        ofi_sum += e_bid - e_ask

    return round(ofi_sum, 4)


def compute_volume_order_imbalance(
    bid_volumes: list[float],
    ask_volumes: list[float],
) -> float:
    """
    Computes Volume Order Imbalance (VOI) ratio: (bid_vol - ask_vol) / (bid_vol + ask_vol).
    Value bounded in [-1.0, 1.0].
    """
    total_bid = sum(bid_volumes)
    total_ask = sum(ask_volumes)
    denom = total_bid + total_ask

    if denom <= 0:
        return 0.0

    return round((total_bid - total_ask) / denom, 4)


def compute_funding_rate_arbitrage_pressure(
    funding_rate: float,
    predicted_funding_rate: float,
    threshold: float = 0.0005,
) -> dict[str, Any]:
    """
    Computes perp-spot funding rate arbitrage pressure factor.
    Returns signal bias (-1 for short perp/long spot, +1 for long perp/short spot, 0 neutral)
    and expected APR.
    """
    abs_rate = abs(funding_rate)

    # 3 periods per day * 365 days = 1095 funding cycles/year
    annualized_apr = abs_rate * 1095.0 * 100.0

    if funding_rate > threshold:
        signal = -1  # Long spot / Short perp to collect positive funding
    elif funding_rate < -threshold:
        signal = 1  # Short spot / Long perp to collect negative funding
    else:
        signal = 0

    return {
        "funding_rate": funding_rate,
        "signal_bias": signal,
        "annualized_apr_pct": round(annualized_apr, 2),
        "arbitrage_opportunity": abs_rate >= threshold,
    }


def compute_liquidation_cascade_density(
    recent_liquidations_u: list[float],
    window_seconds: int = 300,
    cascade_threshold_u: float = 500000.0,
) -> dict[str, Any]:
    """
    Computes clearing cascade density from recent liquidation volumes in window.
    High density alerts potential forced-sell/buy price cascades.
    """
    total_liquidated_u = sum(recent_liquidations_u)
    density_per_min = total_liquidated_u / (window_seconds / 60.0) if window_seconds > 0 else 0.0

    is_cascade = total_liquidated_u >= cascade_threshold_u

    return {
        "total_liquidated_u": total_liquidated_u,
        "density_per_minute": round(density_per_min, 2),
        "is_cascade_alert": is_cascade,
        "recommended_position_multiplier": 0.5 if is_cascade else 1.0,
    }
