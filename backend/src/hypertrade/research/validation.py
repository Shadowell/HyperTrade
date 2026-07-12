"""Deterministic, fail-closed validation gates for BitPro research evidence."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, cast


class ValidationGate:
    """Evaluate only persisted BitPro metrics; model narrative cannot pass a gate."""

    REQUIRED_METRICS = ("total_return_pct", "max_drawdown_pct", "trade_count")

    def evaluate(
        self,
        *,
        results: list[dict[str, Any]],
        validation: dict[str, Any],
        data_complete: bool,
        costs_declared: bool,
    ) -> dict[str, Any]:
        gate_results = {
            "real_data_coverage": data_complete,
            "cost_assumptions_declared": costs_declared,
            "locked_sample_available": any(
                row.get("window") == "locked_out_of_sample" for row in results
            ),
            "reported_metrics_complete": True,
            "trade_count": True,
            "drawdown": True,
        }
        reasons: list[str] = []
        if not data_complete:
            reasons.append("real_data_coverage_inadequate")
        if not costs_declared:
            reasons.append("cost_assumptions_missing")

        min_trades = int(validation.get("min_trade_count", 0))
        max_drawdown = _decimal(validation.get("max_drawdown_pct"))
        for row in results:
            label = str(row.get("label", row.get("window", "unknown")))
            raw_metrics = row.get("metrics")
            metrics = cast(dict[str, Any], raw_metrics) if isinstance(raw_metrics, dict) else {}
            missing = [key for key in self.REQUIRED_METRICS if _decimal(metrics.get(key)) is None]
            if missing:
                gate_results["reported_metrics_complete"] = False
                reasons.append(f"missing_metrics:{label}:{','.join(missing)}")
                continue
            trades = int(_decimal(metrics.get("trade_count")) or Decimal("0"))
            drawdown = _decimal(metrics.get("max_drawdown_pct"))
            if trades < min_trades:
                gate_results["trade_count"] = False
                reasons.append(f"trade_count_below_minimum:{label}")
            if drawdown is None or max_drawdown is None or drawdown > max_drawdown:
                gate_results["drawdown"] = False
                reasons.append(f"drawdown_exceeds_mandate:{label}")

        passed = all(gate_results.values()) and not reasons
        return {
            "passed": passed,
            "gate_results": gate_results,
            "rejection_reasons": sorted(set(reasons)),
        }


def _decimal(value: Any) -> Decimal | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
