"""BitPro self-test: validate, create, backtest, then apply success_criteria.

Local replay is only a cheap pre-filter. A candidate is not validated for paper
until BitPro has a result reference and the operator-declared criteria pass.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1, ARCSuccessCriteriaV1
from hypertrade.bitpro.mcp import BitProToolAdapter


class SelfTestClient(Protocol):
    def strategy_validate_code(
        self,
        *,
        script_content: str,
        idempotency_key: str,
        symbols: list[str] | None = None,
        market_type: str = "spot",
        timeframe: str = "1m",
        smoke: bool = True,
    ) -> dict[str, Any]: ...

    def strategy_create(
        self,
        *,
        name: str,
        script_content: str,
        description: str | None = None,
        exchange: str = "okx",
        symbols: list[str] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]: ...

    def backtest_start_job(
        self,
        *,
        strategy_id: int,
        start_date: str,
        end_date: str,
        initial_capital: float = 10000.0,
        exchange: str = "okx",
        symbol: str | None = None,
        timeframe: str | None = None,
        wait_for_result: bool = False,
        idempotency_key: str = "",
    ) -> dict[str, Any]: ...


@dataclass
class SelfTestResult:
    passed: bool
    validation_id: str | None
    bitpro_strategy_id: str | None
    backtest_id: str | None
    metrics: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    message: str = ""


def apply_success_criteria(
    metrics: dict[str, Any], criteria: ARCSuccessCriteriaV1
) -> tuple[bool, list[str]]:
    """Deterministic paper-promotion referee. Model text cannot pass this.

    The criteria are fractions (0.05 is five percent). BitPro reports ratios under
    `sharpe_ratio`/`trade_count` and returns and drawdowns as percentages under
    `*_pct`, so both the names and the units have to be translated. Reading only the
    fraction spellings left sharpe, drawdown and net return unreadable on every real
    BitPro result, and the referee reported the absent numbers as having failed the
    gate; taking a `*_pct` value at face value would be worse, turning a 0.98% return
    into a 98% one and waving it past a 5% floor.
    """
    reasons: list[str] = []
    sharpe = _number(metrics, "sharpe", "out_of_sample_sharpe", "oos_sharpe", "sharpe_ratio")
    drawdown = _fraction(
        metrics,
        fractions=("max_drawdown", "out_of_sample_max_drawdown", "drawdown"),
        percentages=("max_drawdown_pct",),
    )
    trades = _number(metrics, "trades", "out_of_sample_trades", "trade_count")
    net_return = _fraction(
        metrics,
        fractions=("net_return", "out_of_sample_return", "total_return"),
        percentages=("total_return_pct",),
    )
    if sharpe is None:
        reasons.append("sharpe not reported by the backtest result")
    elif sharpe < float(criteria.min_oos_sharpe):
        reasons.append(
            f"sharpe {sharpe} below success_criteria.min_oos_sharpe {criteria.min_oos_sharpe}"
        )
    if drawdown is None:
        reasons.append("max_drawdown not reported by the backtest result")
    elif abs(drawdown) > float(criteria.max_drawdown):
        reasons.append(
            f"drawdown {drawdown} exceeds success_criteria.max_drawdown {criteria.max_drawdown}"
        )
    if trades is None:
        reasons.append("trade count not reported by the backtest result")
    elif trades < criteria.min_trades:
        reasons.append(
            f"trades {trades} below success_criteria.min_trades {criteria.min_trades}"
        )
    if net_return is None:
        reasons.append("net_return not reported by the backtest result")
    elif net_return < float(criteria.min_oos_net_return):
        reasons.append(
            f"net_return {net_return} below success_criteria.min_oos_net_return "
            f"{criteria.min_oos_net_return}"
        )
    return not reasons, reasons


def _fraction(
    metrics: dict[str, Any],
    *,
    fractions: tuple[str, ...],
    percentages: tuple[str, ...],
) -> float | None:
    """Read a ratio, accepting either a fraction or an explicit percentage spelling."""
    value = _number(metrics, *fractions)
    if value is not None:
        return value
    percent = _number(metrics, *percentages)
    return None if percent is None else percent / 100.0


def _number(metrics: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = metrics.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _as_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _strategy_id(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    nested = payload.get("strategy")
    if isinstance(nested, dict):
        found = _as_int(nested.get("id"))
        if found is not None:
            return found
    return _as_int(payload.get("id") or payload.get("strategy_id"))


def _backtest_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("backtest_result", "result", "job"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            for id_key in ("backtest_id", "id", "job_id", "result_id"):
                value = nested.get(id_key)
                if value is not None and str(value).strip():
                    return str(value)
    for id_key in ("backtest_id", "result_id"):
        value = payload.get(id_key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _result_metrics(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    result = payload.get("backtest_result") or payload.get("result") or {}
    if isinstance(result, dict):
        metrics = result.get("metrics")
        if isinstance(metrics, dict) and metrics:
            return dict(metrics)
        extracted = {
            key: result.get(key)
            for key in (
                "sharpe",
                "max_drawdown",
                "trades",
                "net_return",
                "out_of_sample_sharpe",
                "out_of_sample_trades",
                "out_of_sample_return",
                "out_of_sample_max_drawdown",
            )
            if result.get(key) is not None
        }
        if extracted:
            return extracted
    if isinstance(payload.get("metrics"), dict):
        return dict(payload["metrics"])
    return {}


class ARCSelfTestService:
    """Run the BitPro experiment and judge it with the mission success_criteria."""

    def __init__(self, client: SelfTestClient | None = None) -> None:
        self._client = client

    def run(self, attempt: ARCCandidateAttemptV1, goal: ARCGoalV1) -> SelfTestResult:
        client = self._client or BitProToolAdapter()
        symbol = (
            str(attempt.strategy_spec.get("symbol") or "")
            or (goal.symbols[0] if goal.symbols else "BTC-USDT-SWAP")
        )
        timeframe = (
            str(attempt.strategy_spec.get("timeframe") or "")
            or (goal.timeframes[0] if goal.timeframes else "1H")
        )
        create_key = f"arc-selftest-create-{attempt.candidate_id}"
        backtest_key = f"arc-selftest-backtest-{attempt.candidate_id}"
        validate_key = f"arc-selftest-validate-{attempt.candidate_id}"

        try:
            validated = client.strategy_validate_code(
                script_content=attempt.strategy_code,
                idempotency_key=validate_key,
                symbols=[symbol],
                timeframe=timeframe,
            )
        except Exception as exc:
            return SelfTestResult(
                passed=False,
                validation_id=None,
                bitpro_strategy_id=None,
                backtest_id=None,
                reasons=[f"bitpro_strategy_validate_failed:{type(exc).__name__}"],
                message=str(exc)[:200],
            )
        if isinstance(validated, dict) and validated.get("status") not in {None, "ok"}:
            return SelfTestResult(
                passed=False,
                validation_id=None,
                bitpro_strategy_id=None,
                backtest_id=None,
                reasons=["bitpro_strategy_validate_rejected"],
                message=str(validated)[:200],
            )

        try:
            created = client.strategy_create(
                name=f"ARC self-test {attempt.candidate_id}",
                script_content=attempt.strategy_code,
                description=f"ARC self-test {attempt.candidate_id} for {symbol}",
                exchange="okx",
                symbols=[symbol],
                idempotency_key=create_key,
            )
        except Exception as exc:
            return SelfTestResult(
                passed=False,
                validation_id=None,
                bitpro_strategy_id=None,
                backtest_id=None,
                reasons=[f"bitpro_strategy_create_failed:{type(exc).__name__}"],
                message=str(exc)[:200],
            )
        strategy_id = _strategy_id(created)
        if strategy_id is None:
            return SelfTestResult(
                passed=False,
                validation_id=None,
                bitpro_strategy_id=None,
                backtest_id=None,
                reasons=["bitpro_strategy_create_rejected"],
            )

        end = date.today()
        start = end - timedelta(days=90)
        try:
            backtest = client.backtest_start_job(
                strategy_id=strategy_id,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                symbol=symbol,
                timeframe=timeframe,
                wait_for_result=True,
                idempotency_key=backtest_key,
            )
        except Exception as exc:
            return SelfTestResult(
                passed=False,
                validation_id=None,
                bitpro_strategy_id=str(strategy_id),
                backtest_id=None,
                reasons=[f"bitpro_backtest_failed:{type(exc).__name__}"],
                message=str(exc)[:200],
            )

        backtest_id = _backtest_id(backtest)
        metrics = _result_metrics(backtest)
        if not backtest_id:
            return SelfTestResult(
                passed=False,
                validation_id=None,
                bitpro_strategy_id=str(strategy_id),
                backtest_id=None,
                metrics=metrics,
                reasons=["bitpro_backtest_missing_result_ref"],
            )

        passed, reasons = apply_success_criteria(metrics, goal.success_criteria)
        digest = hashlib.sha256(
            f"{attempt.candidate_id}|{backtest_id}|{sorted(metrics.items())}".encode()
        ).hexdigest()[:16]
        validation_id = f"val_arc_{digest}"
        return SelfTestResult(
            passed=passed,
            validation_id=validation_id if passed else None,
            bitpro_strategy_id=str(strategy_id),
            backtest_id=backtest_id,
            metrics=metrics,
            reasons=reasons,
            message="success_criteria passed" if passed else "; ".join(reasons),
        )


def record_self_test_outcome(
    *,
    mission_id: str,
    attempt: ARCCandidateAttemptV1,
    result: SelfTestResult,
) -> dict[str, Any]:
    """Audit record stored on the mission. Does not invent ledger lineage ids."""
    return {
        "kind": "arc_self_test",
        "mission_id": mission_id,
        "attempt_id": attempt.attempt_id,
        "candidate_id": attempt.candidate_id,
        "passed": result.passed,
        "validation_id": result.validation_id,
        "bitpro_strategy_id": result.bitpro_strategy_id,
        "backtest_id": result.backtest_id,
        "metrics": result.metrics,
        "reasons": result.reasons,
        "as_of": datetime.now(UTC).isoformat(),
    }
