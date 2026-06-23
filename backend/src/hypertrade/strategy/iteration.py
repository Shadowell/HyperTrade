from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from hypertrade.db import Database
from hypertrade.strategy.library import StrategyLibraryService

DEFAULT_STRATEGY_KEY = "momentum_breakout_v1"
DEFAULT_MAX_VARIANTS = 3


class StrategyIterationService:
    """Plan bounded strategy iterations from audited strategy-library evidence."""

    def __init__(self, db: Database, *, max_variants: int = DEFAULT_MAX_VARIANTS) -> None:
        self.db = db
        self.max_variants = _cap_variant_count(max_variants)

    def plan(
        self,
        prompt: str,
        *,
        strategy_key: str = DEFAULT_STRATEGY_KEY,
        max_variants: int | None = None,
    ) -> dict[str, Any]:
        resolved_strategy = _resolve_strategy_key(prompt=prompt, strategy_key=strategy_key)
        variant_limit = _cap_variant_count(max_variants or self.max_variants)
        library = StrategyLibraryService(self.db).search(
            strategy_key=resolved_strategy,
            limit=1,
        )
        items = library.get("items")
        items = items if isinstance(items, list) else []
        if not items:
            return {
                "mode": "first_baseline",
                "strategy_key": resolved_strategy,
                "summary": (
                    "No strategy-library evidence matched; creating a first baseline "
                    "with bounded adjacent variants."
                ),
                "max_variants": variant_limit,
                "prior_evidence": {
                    "source": library.get("source", "memory.strategy_knowledge"),
                    "items": [],
                    "source_memory_ids": [],
                },
                "variants": _first_baseline_variants(variant_limit),
            }

        summary = _as_dict(items[0])
        return {
            "mode": "evidence_driven",
            "strategy_key": resolved_strategy,
            "summary": (
                "Strategy-library evidence found; using source memory ids and "
                "failure reasons to choose bounded adjacent variants."
            ),
            "max_variants": variant_limit,
            "prior_evidence": _prior_evidence_payload(
                source=str(library.get("source", "memory.strategy_knowledge")),
                summary=summary,
            ),
            "variants": _evidence_driven_variants(summary, variant_limit),
        }

    def compare_result(self, winner: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
        return compare_iteration_result(winner=winner, plan=plan)


def compare_iteration_result(*, winner: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    prior = _as_dict(plan.get("prior_evidence"))
    best = _as_dict(prior.get("best"))
    winner_metrics = _as_dict(winner.get("metrics"))
    new_summary = {
        "variant_id": winner.get("variant_id", ""),
        "backtest_id": winner.get("backtest_id", ""),
        "total_return_pct": winner_metrics.get("total_return_pct", "n/a"),
        "max_drawdown_pct": winner_metrics.get("max_drawdown_pct", "n/a"),
        "trade_count": winner_metrics.get("trade_count", "n/a"),
    }
    if not best:
        return {
            "claim": "first_baseline",
            "can_claim_improvement": False,
            "reason": "No prior evidence exists, so this run establishes a baseline.",
            "prior_best": {},
            "new_winner": new_summary,
        }

    prior_return = _decimal_or_none(best.get("total_return_pct"))
    prior_drawdown = _decimal_or_none(best.get("max_drawdown_pct"))
    new_return = _decimal_or_none(winner_metrics.get("total_return_pct"))
    new_drawdown = _decimal_or_none(winner_metrics.get("max_drawdown_pct"))
    if (
        prior_return is None
        or prior_drawdown is None
        or new_return is None
        or new_drawdown is None
    ):
        return {
            "claim": "metrics_missing",
            "can_claim_improvement": False,
            "reason": "Prior or new metrics are missing; refusing to claim improvement.",
            "prior_best": best,
            "new_winner": new_summary,
        }

    improved = bool(new_return > prior_return and new_drawdown <= prior_drawdown)
    return {
        "claim": "improved" if improved else "not_improved",
        "can_claim_improvement": improved,
        "reason": (
            "New winner beat prior return without worse drawdown."
            if improved
            else "New winner did not beat prior evidence on return and drawdown together."
        ),
        "prior_best": best,
        "new_winner": new_summary,
    }


def _prior_evidence_payload(*, source: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": source,
        "strategy_key": summary.get("strategy_key", ""),
        "evidence_count": summary.get("evidence_count", 0),
        "passed_count": summary.get("passed_count", 0),
        "failed_count": summary.get("failed_count", 0),
        "best": _as_dict(summary.get("best")),
        "latest": _as_dict(summary.get("latest")),
        "failure_reasons": list(_as_list(summary.get("failure_reasons"))),
        "next_experiments": list(_as_list(summary.get("next_experiments"))),
        "source_memory_ids": list(_as_list(summary.get("source_memory_ids"))),
        "items": [summary],
    }


def _first_baseline_variants(max_variants: int) -> list[dict[str, Any]]:
    candidates = [
        {
            "variant_id": "baseline",
            "name": "Baseline SMA5 breakout",
            "strategy_params": {"sma_period": 5, "breakout_pct": 0.0},
            "reason": (
                "No strategy-library evidence matched; creating a first baseline "
                "from the current built-in parameters."
            ),
        },
        {
            "variant_id": "fast",
            "name": "Fast SMA3 breakout",
            "strategy_params": {"sma_period": 3, "breakout_pct": 0.0},
            "reason": "Bounded adjacent fast variant for first-pass comparison.",
        },
        {
            "variant_id": "conservative",
            "name": "Conservative SMA8 breakout",
            "strategy_params": {"sma_period": 8, "breakout_pct": 0.005},
            "reason": "Bounded adjacent conservative variant for first-pass comparison.",
        },
    ]
    return [_with_empty_sources(candidate) for candidate in candidates[:max_variants]]


def _evidence_driven_variants(
    summary: dict[str, Any],
    max_variants: int,
) -> list[dict[str, Any]]:
    best = _as_dict(summary.get("best"))
    params = _coerce_strategy_params(_as_dict(best.get("params")))
    source_fields = _source_fields(best)
    failure_reasons = [str(item) for item in _as_list(summary.get("failure_reasons"))]
    next_steps = [str(item) for item in _as_list(summary.get("next_experiments"))]
    failure_text = ", ".join(failure_reasons) if failure_reasons else "none"
    next_text = next_steps[0] if next_steps else "No prior next-experiment note."
    variants = [
        {
            "variant_id": "evidence_baseline",
            "name": "Evidence baseline replay",
            "strategy_params": params,
            "reason": (
                "Replay best prior evidence before adjacent changes: "
                f"memory={best.get('memory_id', 'n/a')} "
                f"experiment={best.get('experiment_id', 'n/a')} "
                f"backtest={best.get('backtest_id', 'n/a')}."
            ),
            **source_fields,
        }
    ]

    if "require_non_negative_return" in failure_reasons:
        adjusted_params = _adjust_params(params, sma_delta=-1, breakout_delta=Decimal("-0.001"))
        reason = (
            "Prior failures included require_non_negative_return; test a faster "
            "lower-threshold adjacent variant."
        )
    elif "max_drawdown_pct" in failure_reasons:
        adjusted_params = _adjust_params(params, sma_delta=2, breakout_delta=Decimal("0.002"))
        reason = (
            "Prior failures included max_drawdown_pct; test a slower higher-threshold "
            "risk-control variant."
        )
    else:
        adjusted_params = _adjust_params(params, sma_delta=-1, breakout_delta=Decimal("0"))
        reason = "Prior evidence passed gates; test the nearest faster adjacent variant."
    variants.append(
        {
            "variant_id": "failure_adjusted",
            "name": "Failure-adjusted adjacent variant",
            "strategy_params": adjusted_params,
            "reason": reason,
            **source_fields,
        }
    )
    variants.append(
        {
            "variant_id": "conservative_followup",
            "name": "Conservative follow-up",
            "strategy_params": _adjust_params(
                params,
                sma_delta=2,
                breakout_delta=Decimal("0.002"),
            ),
            "reason": (
                f"Follow prior next-experiment guidance while bounding risk: {next_text} "
                f"Prior failure reasons: {failure_text}."
            ),
            **source_fields,
        }
    )
    return variants[:max_variants]


def _source_fields(best: dict[str, Any]) -> dict[str, str]:
    return {
        "source_memory_id": str(best.get("memory_id", "")),
        "source_experiment_id": str(best.get("experiment_id", "")),
        "source_backtest_id": str(best.get("backtest_id", "")),
    }


def _with_empty_sources(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        **candidate,
        "source_memory_id": "",
        "source_experiment_id": "",
        "source_backtest_id": "",
    }


def _coerce_strategy_params(params: dict[str, Any]) -> dict[str, int | float]:
    return {
        "sma_period": _int_between(params.get("sma_period"), default=5, low=2, high=100),
        "breakout_pct": _float_between(
            params.get("breakout_pct"),
            default=Decimal("0.0"),
            low=Decimal("0.0"),
            high=Decimal("0.5"),
        ),
    }


def _adjust_params(
    params: dict[str, int | float],
    *,
    sma_delta: int,
    breakout_delta: Decimal,
) -> dict[str, int | float]:
    sma_period = max(2, min(int(params.get("sma_period", 5)) + sma_delta, 100))
    breakout = Decimal(str(params.get("breakout_pct", 0))) + breakout_delta
    breakout = max(Decimal("0.0"), min(breakout, Decimal("0.5")))
    return {
        "sma_period": sma_period,
        "breakout_pct": float(breakout.quantize(Decimal("0.000001"))),
    }


def _resolve_strategy_key(*, prompt: str, strategy_key: str) -> str:
    value = strategy_key.strip() or DEFAULT_STRATEGY_KEY
    if value:
        return value
    if DEFAULT_STRATEGY_KEY in prompt:
        return DEFAULT_STRATEGY_KEY
    return DEFAULT_STRATEGY_KEY


def _cap_variant_count(value: int) -> int:
    return max(1, min(int(value or DEFAULT_MAX_VARIANTS), 5))


def _int_between(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


def _float_between(
    value: Any,
    *,
    default: Decimal,
    low: Decimal,
    high: Decimal,
) -> float:
    parsed = _decimal_or_none(value) or default
    return float(max(low, min(parsed, high)).quantize(Decimal("0.000001")))


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        text = str(value).replace("%", "").strip()
        if not text or text.lower() == "n/a":
            return None
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
