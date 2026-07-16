"""Named synthetic fixtures available only to the isolated evaluator."""

from __future__ import annotations

from typing import Any, Literal

EvaluationFailure = Literal["timeout", "source_unavailable"]
_PREFIX = "operator_eval_fixture:"
_CASE_FAILURES: dict[str, EvaluationFailure] = {
    "source_timeout": "timeout",
    "provider_failure": "source_unavailable",
    "a07_data_source_timeout": "timeout",
    "a10_unavailable_provider": "source_unavailable",
    "d09_source_timeout_delivery": "timeout",
}


def operator_eval_fixture_enabled(*, app_env: str, enabled: bool) -> bool:
    """Keep synthetic data physically unreachable from non-evaluation runtimes."""

    return enabled and app_env.casefold() == "evaluation"


class IsolatedLiveStrategyFixtureAdapter:
    """Bounded fixture source for task-completion tests; never a BitPro substitute.

    The application only constructs this adapter after the explicit environment
    guard above.  This preserves the production boundary: BitPro remains the
    only source for live strategy facts outside isolated evaluation.
    """

    def live_strategy_performance(self, *, exchange: str, limit: int) -> dict[str, Any]:
        del exchange
        strategies = [
            {
                "strategy_id": "eval_live_btc",
                "strategy_name": "BTC 趋势跟踪",
                "status": "running",
                "workspace_status": "active",
                "symbols": ["BTC-USDT-SWAP"],
                "return_pct": "12.5",
                "total_pnl": "125",
                "deployment_status": "deployed",
                "updated_at": "2026-07-16T00:00:00Z",
            },
            {
                "strategy_id": "eval_live_eth",
                "strategy_name": "ETH 均值回归",
                "status": "running",
                "workspace_status": "active",
                "symbols": ["ETH-USDT-SWAP"],
                "return_pct": "4.2",
                "total_pnl": "42",
                "deployment_status": "deployed",
                "updated_at": "2026-07-16T00:00:00Z",
            },
            {
                "strategy_id": "eval_live_sol",
                "strategy_name": "SOL 均值回归",
                "status": "paused",
                "workspace_status": "paused",
                "symbols": ["SOL-USDT-SWAP"],
                "return_pct": "-3.2",
                "total_pnl": "-32",
                "deployment_status": "deployed",
                "updated_at": "2026-07-16T00:00:00Z",
            },
        ]
        return {"strategies": strategies[: max(0, limit)]}


def fixture_constraint(case_id: str) -> str:
    """Return a durable, non-sensitive fixture marker for one authored case."""

    failure = _CASE_FAILURES.get(case_id, "")
    return f"{_PREFIX}{failure}" if failure else ""


def failure_from_constraints(constraints: tuple[str, ...]) -> EvaluationFailure | None:
    """Recognize only the two authored failure modes; arbitrary values are ignored."""

    for item in constraints:
        value = item.removeprefix(_PREFIX)
        if item.startswith(_PREFIX) and value in _CASE_FAILURES.values():
            return value  # type: ignore[return-value]
    return None
