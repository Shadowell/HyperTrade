"""Return moments and DSR (Bailey & Lopez de Prado, 2014, equations 1-2).

All Sharpe values here are per observation, never annualized. Missing or sampled
curves are not statistical evidence. https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from statistics import NormalDist, mean, variance
from typing import Any


def calculate_deflated_sharpe_ratio(
    observed_sharpe: float,
    num_trials: int,
    *,
    sample_length: int,
    skewness: float,
    kurtosis: float,
    trial_sharpe_variance: float,
) -> float:
    """Probability that SR exceeds the expected maximum under a zero-alpha null.

    Use all distinct tested configurations as N: without a measured dependence model
    we make no claim that correlated trials can be discounted to fewer independent ones.
    """
    values = (observed_sharpe, skewness, kurtosis, trial_sharpe_variance)
    if (
        not all(math.isfinite(value) for value in values)
        or isinstance(num_trials, bool)
        or num_trials < 1
        or int(num_trials) != num_trials
        or isinstance(sample_length, bool)
        or sample_length < 4
        or trial_sharpe_variance < 0
        or kurtosis < 1
    ):
        raise ValueError("invalid DSR observations")
    normal = NormalDist()
    expected_max = 0.0
    if num_trials > 1:
        gamma = 0.5772156649015329
        expected_max = math.sqrt(trial_sharpe_variance) * (
            (1 - gamma) * normal.inv_cdf(1 - 1 / num_trials)
            + gamma * normal.inv_cdf(1 - 1 / (num_trials * math.e))
        )
    denominator = 1 - skewness * observed_sharpe + (kurtosis - 1) * observed_sharpe**2 / 4
    if denominator <= 0:
        raise ValueError("invalid DSR moment variance")
    return normal.cdf(
        (observed_sharpe - expected_max) * math.sqrt(sample_length - 1) / math.sqrt(denominator)
    )


def _stamp(value: Any) -> float:
    if isinstance(value, str) and not value.replace(".", "", 1).isdigit():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timestamp timezone missing")
        return parsed.timestamp()
    if isinstance(value, bool):
        raise ValueError("invalid timestamp")
    result = float(value)
    # BitPro epoch timestamps are milliseconds; modern Unix seconds are < 1e11.
    return result / 1000 if abs(result) >= 1e11 else result


def equity_return_statistics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a full, regularly sampled equity curve before UI truncation."""
    unknown = {"schema_version": "return_statistics.v1", "status": "unknown"}
    if len(rows) < 5:
        return {**unknown, "reason": "insufficient_return_observations"}
    try:
        equity = [float(row["equity"]) for row in rows]
        stamps = [_stamp(row["timestamp"]) for row in rows]
        if not all(math.isfinite(value) for value in equity + stamps) or min(equity) <= 0:
            raise ValueError("invalid equity")
        intervals = [right - left for left, right in zip(stamps, stamps[1:], strict=False)]
        period = intervals[0]
        if period <= 0 or any(not math.isclose(x, period, abs_tol=0.001) for x in intervals):
            raise ValueError("irregular equity sampling")
        returns = [right / left - 1 for left, right in zip(equity, equity[1:], strict=False)]
        average = mean(returns)
        sample_variance = variance(returns)
        population_variance = mean((value - average) ** 2 for value in returns)
        if sample_variance <= 0:
            raise ValueError("zero return variance")
        skew = mean((value - average) ** 3 for value in returns) / population_variance**1.5
        kurt = mean((value - average) ** 4 for value in returns) / population_variance**2
        return {
            "schema_version": "return_statistics.v1",
            "status": "observed",
            "sample_length": len(returns),
            "period_seconds": period,
            "period_sharpe": average / math.sqrt(sample_variance),
            "skewness": skew,
            "kurtosis": kurt,
            "series_sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            "first_timestamp": stamps[0],
            "last_timestamp": stamps[-1],
        }
    except (ValueError, TypeError, KeyError, OverflowError):
        return {**unknown, "reason": "invalid_return_observations"}
