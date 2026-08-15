"""Build and decide the single live-approval package. Missing refs cannot be approved."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from hypertrade.arc.contracts import ARCCandidateAttemptV1, LiveApprovalPackageV1
from hypertrade.arc.controller import ARCMissionProjection
from hypertrade.arc.observation import observation_window_complete

_DECAY_REJECT_THRESHOLD = 0.30


def _digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _code_digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _paper_attempt_from_projection(
    projection: ARCMissionProjection,
) -> ARCCandidateAttemptV1 | None:
    observing = [item for item in projection.attempts if item.paper_instance_id]
    return observing[-1] if observing else None


def build_live_approval_package(projection: ARCMissionProjection) -> LiveApprovalPackageV1:
    attempt = _paper_attempt_from_projection(projection) or (
        projection.attempts[-1] if projection.attempts else None
    )
    goal = projection.goal
    observation = dict(projection.paper_observation or {})
    unknowns: list[str] = []
    if attempt is None:
        unknowns.append("missing_candidate")
    if attempt is not None and not attempt.bitpro_backtest_id:
        unknowns.append("missing_backtest_ref")
    if attempt is not None and not attempt.validation_id:
        unknowns.append("missing_validation_id")
    if attempt is not None and not attempt.bitpro_strategy_id:
        unknowns.append("missing_bitpro_strategy_id")
    if attempt is None or not attempt.paper_instance_id:
        unknowns.append("missing_paper_instance")
    if not observation:
        unknowns.append("missing_paper_observation")
    policy = goal.observation if goal is not None else None
    if policy is not None:
        complete, missing = observation_window_complete(
            policy=policy,
            observation=observation,
            started_at=projection.paper_started_at,
        )
        if not complete:
            unknowns.extend(missing)
    # The package carried instance_matched without ever gating on it, so a paper run
    # that BitPro never confirmed as the instance ARC started could still be presented
    # as the evidence for a live promote.
    if observation and observation.get("instance_matched") is not True:
        unknowns.append("paper_instance_unconfirmed")
    health = str(observation.get("bitpro_health") or "").lower()
    if health and health not in {"healthy", "ok", "unknown"}:
        unknowns.append(f"bitpro_unhealthy:{observation.get('bitpro_health')}")
    if observation.get("ok") is False:
        unknowns.append(str(observation.get("reason") or "paper_observation_failed"))

    backtest_metrics = dict(attempt.observed_metrics) if attempt is not None else {}
    backtest = {
        "backtest_id": attempt.bitpro_backtest_id if attempt else None,
        "validation_id": attempt.validation_id if attempt else None,
        "sharpe": backtest_metrics.get("sharpe")
        or backtest_metrics.get("out_of_sample_sharpe")
        or backtest_metrics.get("ranking_sharpe"),
        "net_return": backtest_metrics.get("net_return")
        or backtest_metrics.get("out_of_sample_return"),
        "max_drawdown": backtest_metrics.get("max_drawdown")
        or backtest_metrics.get("out_of_sample_max_drawdown"),
        "trades": backtest_metrics.get("trades")
        or backtest_metrics.get("out_of_sample_trades"),
        "walk_forward": backtest_metrics.get("walk_forward"),
        "ranking_basis": backtest_metrics.get("ranking_basis"),
    }
    paper = {
        "instance_id": attempt.paper_instance_id if attempt else None,
        "started_at": projection.paper_started_at.isoformat()
        if projection.paper_started_at
        else None,
        "trades": observation.get("trades"),
        "net_return": observation.get("net_return"),
        "max_drawdown": observation.get("max_drawdown"),
        "equity": observation.get("equity"),
        "sharpe": observation.get("sharpe"),
        "status": observation.get("status"),
        "instance_matched": observation.get("instance_matched"),
    }
    comparison = _compare(backtest, paper)
    recommendation: Literal["approve", "reject", "wait"] = "wait"
    if unknowns:
        recommendation = "wait"
    elif comparison.get("recommend_reject"):
        recommendation = "reject"
    else:
        recommendation = "approve"
    status: Literal["incomplete", "ready", "approved", "rejected", "promoted"] = (
        "incomplete" if unknowns else "ready"
    )
    existing = projection.live_approval
    if existing is not None and existing.status in {"approved", "rejected", "promoted"}:
        status = existing.status
        recommendation = existing.recommendation
    live_until = None
    if goal is not None:
        live_until = (datetime.now(UTC) + timedelta(hours=goal.live_mandate_hours)).isoformat()
    live_intent = {
        "account": "bitpro_live",
        "environment": "canary",
        "max_capital_u": str(goal.live_max_capital_u) if goal is not None else "100",
        "max_leverage": 1,
        "symbols": list(goal.symbols) if goal is not None else [],
        "mandate_hours": goal.live_mandate_hours if goal is not None else 24,
        "valid_until": live_until,
        "kill_switch": True,
    }
    strategy = {
        "candidate_id": attempt.candidate_id if attempt else None,
        "attempt_id": attempt.attempt_id if attempt else None,
        "bitpro_strategy_id": attempt.bitpro_strategy_id if attempt else None,
        "code_digest": _code_digest(attempt.strategy_code) if attempt else None,
        "parameters": dict(attempt.strategy_spec) if attempt else {},
        "symbols": list(goal.symbols) if goal is not None else [],
        "timeframe": (goal.timeframes[0] if goal and goal.timeframes else None),
    }
    frozen = {
        "strategy": strategy,
        "backtest": {key: backtest[key] for key in ("backtest_id", "validation_id")},
        "paper": {"instance_id": paper["instance_id"]},
        "live_intent": live_intent,
    }
    return LiveApprovalPackageV1(
        mission_id=projection.mission_id,
        status=status,
        recommendation=recommendation,
        package_hash=_digest(frozen),
        strategy=strategy,
        backtest=backtest,
        paper=paper,
        comparison=comparison,
        unknowns=unknowns,
        live_intent=live_intent,
        decision=existing.decision if existing is not None else None,
    )


def _compare(backtest: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
    def _f(value: Any) -> float | None:
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    bt_sharpe = _f(backtest.get("sharpe"))
    paper_sharpe = _f(paper.get("sharpe"))
    bt_dd = _f(backtest.get("max_drawdown"))
    paper_dd = _f(paper.get("max_drawdown"))
    bt_ret = _f(backtest.get("net_return"))
    paper_ret = _f(paper.get("net_return"))
    sharpe_decay = None
    if bt_sharpe is not None and bt_sharpe != 0.0 and paper_sharpe is not None:
        sharpe_decay = (bt_sharpe - paper_sharpe) / abs(bt_sharpe)
    recommend_reject = bool(sharpe_decay is not None and sharpe_decay > _DECAY_REJECT_THRESHOLD)
    return {
        "sharpe_decay": sharpe_decay,
        "return_delta": None if bt_ret is None or paper_ret is None else paper_ret - bt_ret,
        "drawdown_delta": None if bt_dd is None or paper_dd is None else paper_dd - bt_dd,
        "recommend_reject": recommend_reject,
        "reject_reason": (
            f"paper sharpe decay {sharpe_decay:.0%} exceeds {_DECAY_REJECT_THRESHOLD:.0%}"
            if recommend_reject and sharpe_decay is not None
            else None
        ),
    }


def assert_approvable(package: LiveApprovalPackageV1, *, force: bool = False) -> None:
    if package.unknowns or package.status == "incomplete":
        raise PermissionError("incomplete live approval package cannot be approved")
    if not package.backtest.get("backtest_id") or not package.paper.get("instance_id"):
        raise PermissionError("live approval package is missing BitPro refs")
    if package.recommendation == "reject" and not force:
        raise PermissionError(
            "package recommends reject; force approve requires an operator reason"
        )
    if package.status in {"rejected", "promoted"}:
        raise PermissionError(f"package already {package.status}")
