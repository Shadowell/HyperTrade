"""Evidence curation for evolving research context; never a learned policy or approval."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any

from hypertrade.arc.contracts import ResearchWindowsV1

_METRICS = {
    "net_return",
    "total_return",
    "total_return_pct",
    "return_pct",
    "sharpe",
    "sharpe_ratio",
    "max_drawdown",
    "max_drawdown_pct",
    "trade_count",
    "trades",
    "win_rate",
    "profit_factor",
}
_SPEC = {"symbol", "timeframe", "family", "direction", "tunable_parameters", "risk_overlays"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def experiment_key(
    code_sha256: str,
    spec: dict[str, Any],
    capital: Any,
    windows: ResearchWindowsV1,
) -> str:
    # Same code on a different instrument/window/capital is a different experiment.
    return _digest(
        {
            "code": code_sha256,
            "symbol": spec.get("symbol"),
            "timeframe": spec.get("timeframe"),
            "capital": str(Decimal(str(capital)).normalize()),
            "development": [str(d) for d in windows.window("development")],
        }
    )


def _entry(
    record: dict[str, Any], symbol: str, timeframe: str, windows: ResearchWindowsV1
) -> dict[str, Any]:
    spec, receipt = record["spec"], record["development"]
    if not isinstance(spec, dict) or not isinstance(receipt, dict):
        raise ValueError("malformed_receipt")
    if spec.get("symbol") != symbol or spec.get("timeframe") != timeframe:
        raise ValueError("scope_mismatch")
    code = record["code_sha256"]
    if not re.fullmatch("[0-9a-f]{64}", code) or receipt.get("code_sha256") != code:
        raise ValueError("identity_mismatch")
    if receipt.get("purpose") != "development" or not receipt.get("backtest_id"):
        raise ValueError("unsettled_or_final")
    if type(receipt.get("passed")) is not bool:
        raise ValueError("unknown_outcome")
    metrics = receipt["metrics"]
    if not isinstance(metrics, dict):
        raise ValueError("malformed_receipt")
    window = metrics["evaluation_window"]
    if not isinstance(window, dict):
        raise ValueError("malformed_receipt")
    start, end = date.fromisoformat(window["start_date"]), date.fromisoformat(window["end_date"])
    if window.get("purpose") != "development" or start > end:
        raise ValueError("invalid_window")
    if end > windows.window("development")[1]:
        raise ValueError("outside_development_horizon")
    clean_metrics = {}
    for key in sorted(_METRICS & metrics.keys()):
        value = metrics[key]
        if isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError("invalid_metric")
        clean_metrics[key] = float(value)
    if not clean_metrics:
        raise ValueError("missing_metrics")
    clean_spec = {k: spec[k] for k in sorted(_SPEC & spec.keys())}
    for key in ("symbol", "timeframe", "family", "direction"):
        if key in clean_spec and (
            not isinstance(clean_spec[key], str) or len(clean_spec[key]) > 100
        ):
            raise ValueError("invalid_spec")
    for key in ("tunable_parameters", "risk_overlays"):
        # Numeric parameter maps only; source comments/config/runtime are never context.
        if key in clean_spec:
            values = clean_spec[key]
            if not isinstance(values, dict) or any(
                not isinstance(v, (int, float, bool)) or not math.isfinite(float(v))
                for v in values.values()
            ):
                clean_spec.pop(key)
    capital = Decimal(str(record["capital"]))
    if not capital.is_finite() or capital <= 0:
        raise ValueError("invalid_capital")
    # Use the actual receipt window, not a guessed reconstruction of its policy.
    identity = {
        "code": code,
        "symbol": symbol,
        "timeframe": timeframe,
        "capital": str(capital.normalize()),
        "development": [str(start), str(end)],
    }
    entry = {
        "mission_id": str(record["mission_id"])[:128],
        "candidate_id": str(record["candidate_id"])[:128],
        "hypothesis": str(record["hypothesis"])[:400],
        "code_sha256": code,
        "experiment_key": _digest(identity),
        "spec": clean_spec,
        "capital": str(capital),
        "evidence_status": "development_only",
        "development": {
            "backtest_id": str(receipt["backtest_id"])[:128],
            "passed": receipt["passed"],
            "metrics": clean_metrics,
            "window": [str(start), str(end)],
            "reason_codes": [str(r)[:100] for r in receipt.get("reasons", [])[:10]],
        },
    }
    if len(json.dumps(entry, allow_nan=False)) > 2400:
        raise ValueError("entry_too_large")
    entry["memory_id"] = _digest(entry)
    return entry


def curate_memory(
    records: list[dict[str, Any]],
    *,
    symbol: str,
    timeframe: str,
    windows: ResearchWindowsV1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deterministic bounded context, keeping both supporting and opposing experiments."""
    excluded: Counter[str] = Counter()
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records[:200]:
        try:
            entry = _entry(record, symbol, timeframe, windows)
            ref = entry["development"]["backtest_id"]
            if ref in seen:
                raise ValueError("duplicate_receipt")
            seen.add(ref)
            accepted.append(entry)
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "malformed_receipt"
            allowed = {
                "scope_mismatch",
                "identity_mismatch",
                "unsettled_or_final",
                "unknown_outcome",
                "invalid_window",
                "outside_development_horizon",
                "invalid_metric",
                "missing_metrics",
                "invalid_capital",
                "entry_too_large",
                "duplicate_receipt",
            }
            excluded[reason if reason in allowed else "malformed_receipt"] += 1
    # Preserve a counterexample quota instead of only remembering high returns.
    positive = [e for e in accepted if e["development"]["passed"]]
    negative = [e for e in accepted if not e["development"]["passed"]]
    selected = positive[:10] + negative[:10]
    selected_ids = {e["memory_id"] for e in selected}
    selected += [e for e in accepted if e["memory_id"] not in selected_ids][: 20 - len(selected)]
    if len(accepted) > len(selected):
        excluded["context_budget"] += len(accepted) - len(selected)
    if len(records) > 200:
        excluded["scan_budget"] += len(records) - 200
    manifest = {
        "policy": "evidence_context_v1",
        "selected": len(selected),
        "supporting": sum(e["development"]["passed"] for e in selected),
        "opposing": sum(not e["development"]["passed"] for e in selected),
        "excluded": dict(excluded),
        "digest": _digest(selected),
        "rule": "Development observations only, not causal lessons or trading approval.",
    }
    return selected, manifest


def bind_hypothesis(
    proposal: dict[str, Any],
    context: dict[str, Any],
    development: dict[str, Any],
) -> dict[str, Any]:
    """Bind a falsifiable proposal to available evidence, never certify its causal claim."""
    hypothesis = proposal.get("evolution_hypothesis")
    if not hypothesis:
        raise ValueError(
            "evolution_hypothesis requires evidence_refs, expected_metric and falsification"
        )
    available = {
        entry["memory_id"] for entry in context.get("memory", []) if entry.get("memory_id")
    }
    if context.get("paper_feedback"):
        available.add("paper_feedback")
    if context.get("orders", {}).get("sample_count", 0):
        available.add("order_sample")
    available.update(key for key, result in development.items() if result.get("backtest_id"))
    if not set(hypothesis["evidence_refs"]) <= available:
        raise ValueError("evolution_hypothesis cites unavailable evidence")
    return {
        **hypothesis,
        "status": "hypothesis_not_causal_fact",
        "context_digest": context.get("memory_manifest", {}).get("digest"),
    }
