"""
ARC High-Order Microstructure Alpha Factor Library
(OFI, VOI, Funding Arbitrage, Liquidation Cascade, Kyle's Lambda, Amihud, Roll, Microprice & VPIN)
"""

import math
from typing import Any

import numpy as np


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


def compute_kyle_lambda_market_impact(
    price_changes: list[float],
    signed_volumes: list[float],
) -> float:
    """
    Computes Kyle's Lambda (λ = ΔP / SignedVolume), measuring market price impact per unit volume.
    Higher λ indicates illiquid market where trades significantly move price.
    """
    if len(price_changes) < 2 or len(signed_volumes) < 2:
        return 0.0

    dp = np.array(price_changes, dtype=np.float64)
    v = np.array(signed_volumes, dtype=np.float64)

    vol_var = np.var(v)
    if vol_var < 1e-12:
        return 0.0

    cov = np.cov(dp, v)[0, 1]
    kyle_lambda = cov / vol_var
    return round(float(kyle_lambda), 6)


def compute_amihud_illiquidity_ratio(
    returns: list[float],
    dollar_volumes: list[float],
) -> float:
    """
    Computes Amihud Illiquidity Ratio (Illiq = avg(|Return_t| / DollarVolume_t)).
    Higher value indicates higher illiquidity (higher price response per dollar traded).
    """
    if not returns or not dollar_volumes or len(returns) != len(dollar_volumes):
        return 0.0

    r = np.abs(np.array(returns, dtype=np.float64))
    v = np.array(dollar_volumes, dtype=np.float64)

    valid_mask = v > 0
    if not np.any(valid_mask):
        return 0.0

    ratio = r[valid_mask] / v[valid_mask]
    return round(float(np.mean(ratio)), 8)


def compute_roll_implicit_spread(
    price_changes: list[float],
) -> float:
    """
    Computes Roll's implicit effective bid-ask spread from serial autocovariance of price changes.
    Spread S = 2 * sqrt(max(0, -cov(ΔP_t, ΔP_{t-1}))).
    """
    if len(price_changes) < 3:
        return 0.0

    dp = np.array(price_changes, dtype=np.float64)
    cov = np.cov(dp[1:], dp[:-1])[0, 1]

    roll_spread = 2.0 * math.sqrt(-cov) if cov < 0 else 0.0
    return round(float(roll_spread), 4)


def compute_microprice_imbalance(
    bid_price: float,
    bid_volume: float,
    ask_price: float,
    ask_volume: float,
) -> float:
    """
    Computes depth-weighted Microprice:
    P_micro = (P_bid * V_ask + P_ask * V_bid) / (V_bid + V_ask).
    Captures orderbook depth imbalance pushing microprice toward the thinner side.
    """
    total_vol = bid_volume + ask_volume
    if total_vol <= 0:
        return round((bid_price + ask_price) / 2.0, 4)

    microprice = (bid_price * ask_volume + ask_price * bid_volume) / total_vol
    return round(float(microprice), 4)


def compute_trade_flow_toxicity_vpin(
    buy_volumes: list[float],
    sell_volumes: list[float],
    bucket_volume: float = 1000.0,
) -> dict[str, Any]:
    """
    Computes Volume-Synchronized Probability of Toxicity (VPIN).
    VPIN = sum(|V_buy - V_sell|) / (N * bucket_volume).
    High VPIN (> 0.65) warns of high toxicity and impending sharp market moves.
    """
    if not buy_volumes or not sell_volumes:
        return {"vpin": 0.0, "is_toxic": False, "alert_level": "normal"}

    buys = np.array(buy_volumes, dtype=np.float64)
    sells = np.array(sell_volumes, dtype=np.float64)

    imbalances = np.abs(buys - sells)
    total_vol = np.sum(buys + sells)

    if total_vol <= 0:
        return {"vpin": 0.0, "is_toxic": False, "alert_level": "normal"}

    vpin = float(np.sum(imbalances) / total_vol)
    vpin_rounded = round(vpin, 4)

    is_toxic = vpin_rounded >= 0.65
    alert = "critical" if vpin_rounded >= 0.75 else ("high" if is_toxic else "normal")

    return {
        "vpin": vpin_rounded,
        "is_toxic": is_toxic,
        "alert_level": alert,
    }
