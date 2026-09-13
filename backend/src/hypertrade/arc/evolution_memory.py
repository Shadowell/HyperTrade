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

from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1, ResearchWindowsV1
from hypertrade.memory.research import version_projection

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
    if any(
        not isinstance(record.get(key), str) or not record[key].strip()
        for key in ("mission_id", "candidate_id")
    ):
        raise ValueError("unknown_source")
    if record.get("contamination_reasons"):
        raise ValueError("contaminated")
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
    cost_hash = metrics.get("cost_policy_hash")
    cost_hash = (
        cost_hash
        if isinstance(cost_hash, str) and re.fullmatch("[0-9a-f]{64}", cost_hash)
        else None
    )
    entry = {
        "mission_id": str(record["mission_id"])[:128],
        "candidate_id": str(record["candidate_id"])[:128],
        "hypothesis": str(record["hypothesis"])[:400],
        "code_sha256": code,
        "experiment_key": _digest(identity),
        "spec": clean_spec,
        "capital": format(capital.normalize(), "f"),
        "evidence_status": "development_only",
        "cost_policy_hash": cost_hash,
        "development": {
            "backtest_id": str(receipt["backtest_id"])[:128],
            "passed": receipt["passed"],
            "metrics": clean_metrics,
            "window": [str(start), str(end)],
            "reason_codes": [str(r)[:100] for r in receipt.get("reasons", [])[:10]],
        },
    }
    assessment = receipt.get("hypothesis_assessment")
    if (
        isinstance(assessment, dict)
        and assessment.get("scope") == "development_metric_direction_only"
        and assessment.get("status") in ("unknown", "mixed", "observed", "not_observed")
        and assessment.get("metric") in ("net_return", "max_drawdown", "trade_count")
        and assessment.get("direction") in ("increase", "decrease")
    ):
        entry["hypothesis_assessment"] = {
            "status": assessment.get("status")
            if cost_hash and assessment.get("cost_policy_hash") == cost_hash
            else "unknown",
            "cost_policy_hash": cost_hash,
            "metric": assessment.get("metric"),
            "direction": assessment.get("direction"),
            "scope": "development_metric_direction_only",
            "causal_claim_verified": False,
        }
    config_hash = metrics.get("config_sha256")
    config_hash = (
        config_hash
        if isinstance(config_hash, str) and re.fullmatch("[0-9a-f]{64}", config_hash)
        else None
    )
    entry = version_projection(entry, config_hash)
    if len(json.dumps(entry, allow_nan=False)) > 3200:
        raise ValueError("entry_too_large")
    entry["memory_id"] = _digest(entry)
    return entry


def curate_memory(
    records: list[dict[str, Any]],
    *,
    symbol: str,
    timeframe: str,
    windows: ResearchWindowsV1,
    cost_policy_hash: str | None = None,
    invalidated: set[tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deterministic bounded context, keeping both supporting and opposing experiments."""
    excluded: Counter[str] = Counter()
    exclusions: list[dict[str, str]] = []
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records[:200]:
        try:
            entry = _entry(record, symbol, timeframe, windows)
            ref = entry["development"]["backtest_id"]
            if (entry["mission_id"], ref) in (invalidated or set()):
                raise ValueError("invalidated")
            if cost_policy_hash is not None and entry["cost_policy_hash"] != cost_policy_hash:
                raise ValueError("cost_identity_mismatch")
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
                "unknown_source",
                "contaminated",
                "invalidated",
                "cost_identity_mismatch",
            }
            reason = reason if reason in allowed else "malformed_receipt"
            excluded[reason] += 1
            exclusions.append(
                {"mission_id": str(record.get("mission_id", ""))[:128], "reason": reason}
            )
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
        "schema_version": "research_memory_manifest.v1",
        "selected": len(selected),
        "supporting": sum(e["development"]["passed"] for e in selected),
        "opposing": sum(not e["development"]["passed"] for e in selected),
        "excluded": dict(excluded),
        "exclusions": exclusions,
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
    diagnostic_fields = []
    report = context.get("attribution_report")
    if report:
        fields = {
            f"attribution:{report['report_id']}:{name}": {"field": name, "state": row["state"]}
            for name, row in report["dimensions"].items()
        }
        diagnostic_fields = [fields[ref] for ref in hypothesis["evidence_refs"] if ref in fields]
        if not diagnostic_fields:
            raise ValueError("evolution_hypothesis requires a specific diagnostic field")
        falsification = hypothesis.get("falsification")
        if not isinstance(falsification, str) or not 12 <= len(falsification.strip()) <= 400:
            raise ValueError("evolution_hypothesis requires explicit falsification")
        available.update(fields)
    if not set(hypothesis["evidence_refs"]) <= available:
        raise ValueError("evolution_hypothesis cites unavailable evidence")
    return {
        **hypothesis,
        "status": "hypothesis_not_causal_fact",
        "diagnostic_fields": diagnostic_fields,
        "context_digest": context.get("memory_manifest", {}).get("digest"),
    }


def assess_hypothesis(
    spec: dict[str, Any],
    metrics: dict[str, Any],
    references: list[dict[str, Any]],
    windows: ResearchWindowsV1,
    capital: Any,
    current_backtest_id: str | None = None,
) -> dict[str, Any]:
    """Measure a proposed direction without promoting it to a causal or OOS conclusion."""
    from hypertrade.arc.self_test import _fraction, _number

    hypothesis = spec.get("evolution_hypothesis")
    hypothesis = hypothesis if isinstance(hypothesis, dict) else {}
    metric = hypothesis.get("expected_metric")
    direction = hypothesis.get("expected_direction")

    def number(values: dict[str, Any]) -> float | None:
        if metric == "net_return":
            return _fraction(
                values,
                fractions=("net_return", "total_return"),
                percentages=("total_return_pct", "return_pct"),
            )
        if metric == "max_drawdown":
            value = _fraction(
                values, fractions=("max_drawdown",), percentages=("max_drawdown_pct",)
            )
            return abs(value) if value is not None else None
        return _number(values, "trade_count", "trades")

    cost_hash = metrics.get("cost_policy_hash")
    cost_hash = (
        cost_hash
        if isinstance(cost_hash, str) and re.fullmatch("[0-9a-f]{64}", cost_hash)
        else None
    )
    cost_mismatches = 0
    identity_mismatches = 0
    config_hash = metrics.get("config_sha256")
    config_known = isinstance(config_hash, str) and bool(re.fullmatch("[0-9a-f]{64}", config_hash))
    current = number(metrics)
    comparisons = []
    expected_window = [str(d) for d in windows.window("development")]
    window = metrics.get("evaluation_window")
    # Only the actual development receipt can establish comparability.
    valid_current = (
        metric in ("net_return", "max_drawdown", "trade_count")
        and direction in ("increase", "decrease")
        and isinstance(window, dict)
        and window.get("purpose") == "development"
        and [window.get("start_date"), window.get("end_date")] == expected_window
    )
    refs = hypothesis.get("evidence_refs")
    refs = refs if isinstance(refs, list) else []
    seen: set[str] = set()
    for entry in references[:200] if valid_current else []:
        try:
            if not isinstance(entry, dict) or entry.get("memory_id") not in refs:
                continue
            if not isinstance(entry.get("spec"), dict) or any(
                entry["spec"].get(k) != spec.get(k) for k in ("symbol", "timeframe")
            ):
                continue
            if not cost_hash or entry.get("cost_policy_hash") != cost_hash:
                cost_mismatches += 1
                continue
            prior_config = entry.get("config_sha256")
            if (
                not config_known
                or not isinstance(prior_config, str)
                or not re.fullmatch("[0-9a-f]{64}", prior_config)
            ):
                identity_mismatches += 1
                continue
            receipt = entry["development"]
            if isinstance(receipt, dict) and receipt.get("backtest_id") == current_backtest_id:
                # A resumed settlement must never be measured against itself.
                continue
            prior_capital, current_capital = Decimal(str(entry["capital"])), Decimal(str(capital))
            if (
                entry.get("evidence_status") != "development_only"
                or not re.fullmatch("[0-9a-f]{64}", entry["code_sha256"])
                or not isinstance(receipt, dict)
                or not receipt.get("backtest_id")
                or type(receipt.get("passed")) is not bool
                or receipt.get("window") != expected_window
                or not prior_capital.is_finite()
                or not current_capital.is_finite()
                or prior_capital <= 0
                or prior_capital != current_capital
                or not isinstance(receipt.get("metrics"), dict)
            ):
                continue
            prior = number(receipt["metrics"])
            if current is None or prior is None or receipt["backtest_id"] in seen:
                continue
            seen.add(receipt["backtest_id"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            # Old or incomplete memory must not interrupt a settled experiment.
            continue
        change = current - prior
        if not math.isfinite(change):
            continue
        observed = change > 0 if direction == "increase" else change < 0
        comparisons.append(
            {
                "reference_id": entry["memory_id"],
                "backtest_id": receipt["backtest_id"],
                "before": prior,
                "after": current,
                "delta": change,
                "observed": observed,
            }
        )
    outcomes = {c["observed"] for c in comparisons}
    status = (
        "unknown"
        if not outcomes or cost_mismatches or identity_mismatches
        else "mixed"
        if len(outcomes) > 1
        else "observed"
        if True in outcomes
        else "not_observed"
    )
    return {
        "status": status,
        "metric": metric,
        "direction": direction,
        "scope": "development_metric_direction_only",
        "causal_claim_verified": False,
        "comparisons": comparisons,
        "cost_policy_hash": cost_hash,
        "incomparable_cost_references": cost_mismatches,
        "incomparable_identity_references": identity_mismatches,
        "reason": "missing_or_incompatible_cost_policy"
        if not cost_hash or cost_mismatches
        else "missing_config_identity"
        if not config_known or identity_mismatches
        else "no_comparable_referenced_development"
        if not comparisons
        else "metric_direction_checked; textual_falsifier_requires_review",
    }


def assess_development(
    candidate: ARCCandidateAttemptV1,
    goal: ARCGoalV1,
    attempts: list[ARCCandidateAttemptV1],
    development: dict[str, Any],
    metrics: dict[str, Any],
    backtest_id: str | None,
) -> dict[str, Any]:
    """Assess after a settled experiment; bad legacy context must not lose its receipt."""
    try:
        assert goal.research_windows is not None
        raw = [
            {
                "mission_id": goal.research_id,
                "candidate_id": old.candidate_id,
                "hypothesis": old.hypothesis,
                "spec": old.strategy_spec,
                "code_sha256": hashlib.sha256(old.strategy_code.encode()).hexdigest(),
                "capital": str(goal.paper_initial_equity),
                "development": development[old.attempt_id],
            }
            for old in attempts
            if old.attempt_id in development
        ]
        references, _ = curate_memory(
            raw,
            symbol=candidate.strategy_spec["symbol"],
            timeframe=candidate.strategy_spec["timeframe"],
            windows=goal.research_windows,
        )
        attempt_ids = {a.candidate_id: a.attempt_id for a in attempts}
        for entry in references:
            entry["memory_id"] = attempt_ids[entry["candidate_id"]]
        references += [
            e
            for e in (goal.evolution_context or {}).get("memory", [])[:20]
            if isinstance(e, dict) and e.get("memory_id")
        ]
        return assess_hypothesis(
            candidate.strategy_spec,
            metrics,
            references,
            goal.research_windows,
            goal.paper_initial_equity,
            backtest_id,
        )
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        # A secondary interpretation is never grounds for redispatching a settled backtest.
        return {
            "status": "unknown",
            "scope": "development_metric_direction_only",
            "causal_claim_verified": False,
            "reason": "invalid_comparison_evidence",
        }
