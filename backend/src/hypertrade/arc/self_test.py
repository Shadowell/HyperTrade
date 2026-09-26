"""BitPro self-test: validate, create, backtest, then apply success_criteria.

Local replay is only a cheap pre-filter. A candidate is not validated for paper
until BitPro has a result reference and the operator-declared criteria pass.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol

from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCGoalV1, ARCSuccessCriteriaV1
from hypertrade.arc.strategy_names import (
    format_bitpro_strategy_name,
    logic_summary,
    scope_label_from_symbols,
)
from hypertrade.arc.universe import candidate_symbols
from hypertrade.bitpro.cost_identity import source_cost_policy_hash
from hypertrade.bitpro.mcp import BitProToolAdapter


class SelfTestClient(Protocol):
    def strategy_get(self, *, strategy_id: int) -> dict[str, Any]: ...

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
        config: dict[str, Any] | None = None,
        exchange: str = "okx",
        symbols: list[str] | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]: ...

    def strategy_research_variant_create(
        self,
        *,
        strategy_id: int,
        expected_parent_manifest_sha256: str,
        idempotency_key: str,
        parameter_changes: dict[str, int | float],
        purpose: str = "candidate",
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
        timeout_sec: float = 90.0,
        verified_data_snapshot_id: str | None = None,
        verified_data_manifest_sha256: str | None = None,
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
        reasons.append(f"trades {trades} below success_criteria.min_trades {criteria.min_trades}")
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
        if value is None or isinstance(value, bool):
            continue
        try:
            number = float(value)
            if math.isfinite(number):
                return number
        except (TypeError, ValueError):
            continue
    return None


# Sealed research backtests add a fixed warmup and may cover whole baskets; the
# connector's 90s interactive default abandoned completed jobs as empty results.
BACKTEST_WAIT_SECONDS = 1800.0
_PENDING_JOB_STATES = {"queued", "pending", "preparing_data", "running", "cancelling"}


def _backtest_still_running(payload: Any) -> bool:
    if not isinstance(payload, dict) or payload.get("backtest_result"):
        return False
    job = payload.get("job")
    return isinstance(job, dict) and str(job.get("status") or "").lower() in _PENDING_JOB_STATES


def _experiment_scope(
    goal: ARCGoalV1,
    code: str,
    symbols: list[str],
    timeframe: str,
    spec: dict[str, Any],
    parameter_changes: dict[str, Any],
) -> str:
    identity = f"{goal.research_id}|{code}|{'|'.join(symbols)}|{timeframe}"
    if spec.get("is_source_variant") is True:
        # Variants share the parent's source; parameters are what distinguish them.
        identity += "|variant|{}|{}".format(
            spec.get("parent_manifest_sha256"),
            json.dumps(parameter_changes, sort_keys=True, separators=(",", ":")),
        )
    return hashlib.sha256(identity.encode()).hexdigest()


def _window_backtest_key(scope: str, purpose: str, start: date, end: date, goal: ARCGoalV1) -> str:
    window_digest = hashlib.sha256(
        f"{scope}|{purpose}|{start}|{end}|{goal.paper_initial_equity}".encode()
    ).hexdigest()
    return f"arc-window-{window_digest}"


def _baseline_data_reference(
    client: Any,
    attempt: ARCCandidateAttemptV1,
    goal: ARCGoalV1,
    symbols: list[str],
    timeframe: str,
    purpose: str,
    start: date,
    end: date,
) -> dict[str, str] | SelfTestResult:
    spec = attempt.strategy_spec
    scope = _experiment_scope(goal, attempt.strategy_code, symbols, timeframe, spec, {})
    try:
        created = client.strategy_research_variant_create(
            strategy_id=int(spec["parent_strategy_id"]),
            expected_parent_manifest_sha256=str(spec["parent_manifest_sha256"]),
            idempotency_key=f"arc-selftest-create-{scope}",
            parameter_changes={},
            purpose="baseline",
        )
        baseline_id = _strategy_id(created) or _as_int(created.get("candidate_strategy_id"))
        if baseline_id is None:
            raise ValueError("baseline variant identity missing")
        backtest = client.backtest_start_job(
            strategy_id=baseline_id,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            initial_capital=float(goal.paper_initial_equity),
            symbol=symbols[0] if len(symbols) == 1 else None,
            timeframe=timeframe,
            wait_for_result=True,
            timeout_sec=BACKTEST_WAIT_SECONDS,
            idempotency_key=_window_backtest_key(scope, purpose, start, end, goal),
        )
        entries = ((backtest.get("job") or {}).get("verified_data_binding") or {}).get(
            "entries"
        ) or []
        if len(entries) != 1:
            raise ValueError("baseline sealed data binding missing")
        return {
            "verified_data_snapshot_id": str(entries[0]["verified_snapshot_id"]),
            "verified_data_manifest_sha256": str(entries[0]["manifest_sha256"]),
        }
    except Exception as exc:
        return SelfTestResult(
            passed=False,
            validation_id=None,
            bitpro_strategy_id=None,
            backtest_id=None,
            reasons=["baseline_data_snapshot_unavailable"],
            message=f"{type(exc).__name__}: {str(exc)[:180]}",
        )


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

    def run(
        self,
        attempt: ARCCandidateAttemptV1,
        goal: ARCGoalV1,
        *,
        purpose: Literal["development", "final"] = "final",
    ) -> SelfTestResult:
        client = self._client or BitProToolAdapter()
        try:
            symbols = candidate_symbols(attempt.strategy_spec, goal.symbols)
        except ValueError as exc:
            return SelfTestResult(False, None, None, None, reasons=[str(exc)])
        symbol = symbols[0]  # naming/asset display only; execution uses the full set
        timeframe = str(attempt.strategy_spec.get("timeframe") or "") or (
            goal.timeframes[0] if goal.timeframes else "1H"
        )
        scope = attempt.candidate_id
        is_source_variant = attempt.strategy_spec.get("is_source_variant") is True
        is_baseline_attempt = attempt.attempt_id.startswith("baseline_")
        if goal.paper_review_required:
            if not goal.research_id:
                return SelfTestResult(
                    False, None, None, None, reasons=["research_identity_missing"]
                )
            scope = _experiment_scope(
                goal,
                attempt.strategy_code,
                symbols,
                timeframe,
                attempt.strategy_spec,
                dict(attempt.strategy_spec.get("parameter_changes") or {}),
            )
        create_key = f"arc-selftest-create-{scope}"
        backtest_key = f"arc-selftest-backtest-{scope}"
        validate_key = f"arc-selftest-validate-{scope}"
        strategy_name = f"ARC self-test {attempt.candidate_id}"
        if goal.paper_review_required:
            # Full identity stays in dispatch keys. Frozen creation rejects name collisions;
            # a compact revision distinguishes independent experiments without hiding the method.
            strategy_name = format_bitpro_strategy_name(
                symbol,
                timeframe,
                logic_summary=f"{logic_summary(attempt.strategy_spec)} V{scope[:12]}",
                capital_u=goal.paper_initial_equity,
                asset_type="合约" if symbol.endswith("-SWAP") or ":USDT" in symbol else "现货",
                scope_label=scope_label_from_symbols(symbols) if len(symbols) > 1 else None,
            )

        if not is_source_variant:
            try:
                validated = client.strategy_validate_code(
                    script_content=attempt.strategy_code,
                    idempotency_key=validate_key,
                    symbols=symbols,
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

        strategy_id: int | None = None
        try:
            if is_source_variant:
                if attempt.bitpro_strategy_id is not None:
                    existing_id = _as_int(attempt.bitpro_strategy_id)
                    if existing_id is None or existing_id <= 0:
                        raise ValueError("invalid existing strategy identity")
                    existing = client.strategy_get(strategy_id=existing_id)
                    created = existing
                    strategy_id = existing_id
                else:
                    parent_id = int(attempt.strategy_spec["parent_strategy_id"])
                    parent_sha = str(attempt.strategy_spec["parent_manifest_sha256"])
                    param_changes = dict(attempt.strategy_spec.get("parameter_changes") or {})
                    created = client.strategy_research_variant_create(
                        strategy_id=parent_id,
                        expected_parent_manifest_sha256=parent_sha,
                        idempotency_key=create_key,
                        parameter_changes=param_changes,
                        purpose="baseline" if is_baseline_attempt else "candidate",
                    )
                    strategy_id = _strategy_id(created)
                    if strategy_id is None:
                        strategy_id = _as_int(created.get("candidate_strategy_id"))
            elif attempt.bitpro_strategy_id is not None:
                existing_id = _as_int(attempt.bitpro_strategy_id)
                if existing_id is None or existing_id <= 0:
                    raise ValueError("invalid existing strategy identity")
                existing = client.strategy_get(strategy_id=existing_id)
                body = existing.get("strategy", existing)
                if (
                    _strategy_id(body) != existing_id
                    or body.get("script_content") != attempt.strategy_code
                ):
                    return SelfTestResult(
                        False,
                        None,
                        str(existing_id),
                        None,
                        reasons=["bitpro_existing_strategy_mismatch"],
                    )
                created = existing
                strategy_id = existing_id
            else:
                created = client.strategy_create(
                    name=strategy_name,
                    script_content=attempt.strategy_code,
                    description=(
                        f"ARC self-test {attempt.candidate_id} for "
                        + (symbol if len(symbols) == 1 else scope_label_from_symbols(symbols))
                    ),
                    exchange="okx",
                    symbols=symbols,
                    idempotency_key=create_key,
                    **(
                        {
                            "config": {
                                **attempt.strategy_spec.get("baseline_config", {}),
                                **(
                                    {"_freeze_research_costs": True, "market_type": "swap"}
                                    if goal.paper_review_required
                                    else {}
                                ),
                            }
                        }
                        if "baseline_config" in attempt.strategy_spec or goal.paper_review_required
                        else {}
                    ),
                )
                strategy_id = _strategy_id(created)
        except Exception as exc:
            return SelfTestResult(
                passed=False,
                validation_id=None,
                bitpro_strategy_id=None,
                backtest_id=None,
                reasons=[f"bitpro_strategy_create_failed:{type(exc).__name__}"],
                message=str(exc)[:200],
            )
        if strategy_id is None:
            return SelfTestResult(
                passed=False,
                validation_id=None,
                bitpro_strategy_id=None,
                backtest_id=None,
                reasons=["bitpro_strategy_create_rejected"],
            )

        cost_policy_hash = source_cost_policy_hash(created, strategy_id, attempt.strategy_code)
        config_hash = None
        try:
            source = created.get("strategy", created)
            if (
                isinstance(source, dict)
                and _strategy_id(source) == strategy_id
                and source.get("script_content") == attempt.strategy_code
                and isinstance(source.get("config"), dict)
            ):
                config_hash = hashlib.sha256(
                    json.dumps(
                        source["config"],
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ).encode()
                ).hexdigest()
        except (TypeError, ValueError):
            # Non-canonical config remains unknown; it is never reconstructed later.
            config_hash = None
        end = date.today()
        start = end - timedelta(days=90)
        if goal.research_windows is not None:
            start, end = goal.research_windows.window(purpose)
            backtest_key = _window_backtest_key(scope, purpose, start, end, goal)
        data_ref: dict[str, str] = {}
        if is_source_variant and not is_baseline_attempt and goal.paper_review_required:
            # BitPro compares a candidate only on its baseline's sealed data. The baseline
            # uses the exact create/backtest keys its own attempt would, so the later
            # baseline self-test replays this job instead of running a second one.
            baseline_ref = _baseline_data_reference(
                client, attempt, goal, symbols, timeframe, purpose, start, end
            )
            if isinstance(baseline_ref, SelfTestResult):
                baseline_ref.bitpro_strategy_id = str(strategy_id)
                return baseline_ref
            data_ref = baseline_ref
        try:
            backtest = client.backtest_start_job(
                strategy_id=strategy_id,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                initial_capital=float(goal.paper_initial_equity)
                if goal.paper_review_required
                else 10000.0,
                # Single symbol: explicit selector. Portfolio: None so BitPro
                # derives the full basket from the strategy config's trade_symbols.
                symbol=symbol if len(symbols) == 1 else None,
                timeframe=timeframe,
                wait_for_result=True,
                timeout_sec=BACKTEST_WAIT_SECONDS,
                idempotency_key=backtest_key,
                **data_ref,
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

        if _backtest_still_running(backtest):
            return SelfTestResult(
                passed=False,
                validation_id=None,
                bitpro_strategy_id=str(strategy_id),
                backtest_id=None,
                reasons=["bitpro_backtest_timeout"],
                message="backtest still running after the wait window; retry replays the same job",
            )
        backtest_id = _backtest_id(backtest)
        metrics = _result_metrics(backtest)
        # Bind to the immutable creation/read receipt, not arbitrary backtest metric text.
        metrics.pop("cost_policy_hash", None)
        metrics.pop("config_sha256", None)
        if cost_policy_hash is not None:
            metrics["cost_policy_hash"] = cost_policy_hash
        if config_hash is not None:
            metrics["config_sha256"] = config_hash
        if goal.research_windows is not None:
            metrics["evaluation_window"] = {
                "purpose": purpose,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "research_id": goal.research_id,
            }
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
