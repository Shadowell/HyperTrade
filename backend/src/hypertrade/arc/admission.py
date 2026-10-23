"""Basic admission for evolution candidates.

The forward Paper race is the real exam; this gate only keeps clearly broken or clearly
worse candidates out of it. Thresholds are fixed in code so a config edit cannot quietly
loosen them. The strict final result is still recorded truthfully; admission is a separate,
explicit decision bound to that receipt.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_CEILING, Decimal
from typing import Any

from hypertrade.arc.contracts import ARCGoalV1
from hypertrade.arc.feedback import compare_backtests
from hypertrade.arc.self_test import _fraction, _number

BASIC_ADMISSION_VERSION = "basic_admission.v1"
MIN_RETURN_TOLERANCE = Decimal("0.02")  # candidate may trail the parent by 2 pp ...
DRAWDOWN_SHARE_TOLERANCE = Decimal("0.5")  # ... or by half of the parent's own max drawdown
MAX_EXTRA_DRAWDOWN = Decimal("0.05")  # drawdown at most 5 pp worse than the parent
MAX_DRAWDOWN_CAP = Decimal("0.30")  # and never above 30%
MIN_TRADE_SHARE = Decimal("0.3")  # at least 30% of the parent's trade count
MIN_TRADES = 1  # and at least one trade


def basic_admission(
    metrics: dict[str, Any], baseline_receipt: dict[str, Any]
) -> dict[str, Any]:
    """Judge a failed final candidate against its same-window parent; pure and deterministic."""
    comparison = compare_backtests(metrics, baseline_receipt)
    baseline_backtest_id = comparison.get("backtest_id")
    checks: dict[str, Any] = {
        "baseline_backtest_id": None
        if baseline_backtest_id is None
        else str(baseline_backtest_id)
    }
    if "reason" in comparison or not comparison.get("backtest_id"):
        return {
            "version": BASIC_ADMISSION_VERSION,
            "passed": False,
            "reasons": ["baseline_evidence_invalid"],
            "checks": checks,
        }

    parent = baseline_receipt.get("metrics")
    parent_metrics = parent if isinstance(parent, dict) else {}
    candidate_return = _fraction(
        metrics,
        fractions=("net_return", "out_of_sample_return", "total_return"),
        percentages=("total_return_pct",),
    )
    parent_return = _fraction(
        parent_metrics,
        fractions=("net_return", "out_of_sample_return", "total_return"),
        percentages=("total_return_pct",),
    )
    candidate_drawdown = _fraction(
        metrics,
        fractions=("max_drawdown", "out_of_sample_max_drawdown", "drawdown"),
        percentages=("max_drawdown_pct",),
    )
    parent_drawdown = _fraction(
        parent_metrics,
        fractions=("max_drawdown", "out_of_sample_max_drawdown", "drawdown"),
        percentages=("max_drawdown_pct",),
    )
    candidate_trades = _number(metrics, "trades", "out_of_sample_trades", "trade_count")
    parent_trades = _number(parent_metrics, "trades", "out_of_sample_trades", "trade_count")

    # Absolute drawdowns; the sign convention upstream must never change the verdict.
    if candidate_drawdown is not None:
        candidate_drawdown = abs(candidate_drawdown)
    if parent_drawdown is not None:
        parent_drawdown = abs(parent_drawdown)

    values = {
        "candidate_return": candidate_return,
        "parent_return": parent_return,
        "candidate_drawdown": candidate_drawdown,
        "parent_drawdown": parent_drawdown,
        "candidate_trades": candidate_trades,
        "parent_trades": parent_trades,
    }
    for name, value in values.items():
        if value is not None:
            checks[name] = str(value)

    reasons: list[str] = []
    if candidate_return is None:
        reasons.append("metric_missing:candidate_return")
    if parent_return is None:
        reasons.append("metric_missing:parent_return")
    if candidate_drawdown is None:
        reasons.append("metric_missing:candidate_drawdown")
    if parent_drawdown is None:
        reasons.append("metric_missing:parent_drawdown")
    if candidate_trades is None:
        reasons.append("metric_missing:candidate_trades")
    if parent_trades is None:
        reasons.append("metric_missing:parent_trades")
    if reasons:
        return {
            "version": BASIC_ADMISSION_VERSION,
            "passed": False,
            "reasons": reasons,
            "checks": checks,
        }

    assert candidate_return is not None
    assert parent_return is not None
    assert candidate_drawdown is not None
    assert parent_drawdown is not None
    assert candidate_trades is not None
    assert parent_trades is not None

    candidate_return_d = Decimal(str(candidate_return))
    parent_return_d = Decimal(str(parent_return))
    candidate_drawdown_d = Decimal(str(candidate_drawdown))
    parent_drawdown_d = Decimal(str(parent_drawdown))
    candidate_trades_d = Decimal(str(candidate_trades))
    parent_trades_d = Decimal(str(parent_trades))

    required_trades = max(
        MIN_TRADES,
        int((MIN_TRADE_SHARE * parent_trades_d).to_integral_value(rounding=ROUND_CEILING)),
    )
    return_tolerance = max(MIN_RETURN_TOLERANCE, DRAWDOWN_SHARE_TOLERANCE * parent_drawdown_d)
    drawdown_limit = min(MAX_DRAWDOWN_CAP, parent_drawdown_d + MAX_EXTRA_DRAWDOWN)

    checks["return_tolerance"] = str(return_tolerance)
    checks["drawdown_limit"] = str(drawdown_limit)
    checks["required_trades"] = str(required_trades)

    if candidate_trades_d < required_trades:
        reasons.append("too_few_trades")
    if candidate_return_d < parent_return_d - return_tolerance:
        reasons.append("return_shortfall")
    if candidate_drawdown_d > drawdown_limit:
        reasons.append("drawdown_too_large")

    return {
        "version": BASIC_ADMISSION_VERSION,
        "passed": not reasons,
        "reasons": reasons,
        "checks": checks,
    }


def basic_validation_id(receipt: dict[str, Any]) -> str:
    """Content-bound id for a basic-admitted final receipt."""
    payload = {
        "version": BASIC_ADMISSION_VERSION,
        "attempt_id": receipt.get("attempt_id"),
        "backtest_id": receipt.get("backtest_id"),
        "code_sha256": receipt.get("code_sha256"),
        "bitpro_strategy_id": receipt.get("bitpro_strategy_id"),
        "admission": receipt.get("admission"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
    return "val_basic_" + digest[:24]


def basic_admitted(goal: ARCGoalV1 | None, receipt: dict[str, Any]) -> bool:
    """True only for a receipt this task itself admitted under the basic policy."""
    if goal is None or goal.paper_admission != "basic":
        return False
    if receipt.get("purpose") != "final":
        return False
    if receipt.get("admitted") is not True:
        return False
    if receipt.get("passed") is True:
        return False
    admission = receipt.get("admission")
    if not isinstance(admission, dict):
        return False
    if admission.get("version") != BASIC_ADMISSION_VERSION:
        return False
    if admission.get("passed") is not True:
        return False
    return receipt.get("validation_id") == basic_validation_id(receipt)
