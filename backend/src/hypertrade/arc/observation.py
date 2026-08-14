"""Pull BitPro paper evidence into an observing mission. Never copy backtest numbers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from hypertrade.arc.contracts import ARCCandidateAttemptV1, PaperObservationPolicyV1
from hypertrade.arc.controller import ARCController
from hypertrade.bitpro.mcp import BitProToolAdapter


class PaperObservationClient(Protocol):
    def paper_snapshot(
        self, *, strategy_id: int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]: ...

    def health(self) -> dict[str, Any]: ...


def _number(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _snapshot_body(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    snapshot = payload.get("snapshot")
    if isinstance(snapshot, dict):
        return snapshot
    return payload


def collect_paper_observation(
    attempt: ARCCandidateAttemptV1,
    client: PaperObservationClient,
) -> dict[str, Any]:
    """Read one BitPro snapshot. Missing identity is an unknown, not a fabricated id."""
    instance_id = attempt.paper_instance_id
    strategy_id = None
    if attempt.bitpro_strategy_id:
        try:
            strategy_id = int(attempt.bitpro_strategy_id)
        except (TypeError, ValueError):
            strategy_id = None
    try:
        raw = client.paper_snapshot(strategy_id=strategy_id, instance_id=instance_id)
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"paper_snapshot_failed:{type(exc).__name__}",
            "message": str(exc)[:200],
            "instance_id": instance_id,
        }
    body = _snapshot_body(raw)
    reported = body.get("instance_id") or body.get("id")
    matched = reported is None or str(reported) == str(instance_id)
    health = {}
    try:
        health = client.health()
    except Exception as exc:
        health = {"status": "unknown", "error": str(exc)[:200]}
    nested = health.get("health")
    if isinstance(nested, dict):
        healthy = str(nested.get("status") or "")
    else:
        healthy = str(health.get("status") or "")
    return {
        "ok": bool(matched and body),
        "instance_id": instance_id,
        "reported_instance_id": None if reported is None else str(reported),
        "instance_matched": matched,
        "status": body.get("status"),
        "trades": _number(body, "trade_count", "trades"),
        "equity": _number(body, "equity"),
        "net_return": _number(body, "cumulative_return_pct", "pnl", "net_return"),
        "max_drawdown": _number(body, "max_drawdown_pct", "max_drawdown"),
        "sharpe": _number(body, "sharpe_ratio", "sharpe"),
        "error_count": _number(body, "error_count"),
        "generated_at": body.get("generated_at"),
        "bitpro_health": healthy or "unknown",
        "raw_keys": sorted(body),
    }


def observation_window_complete(
    *,
    policy: PaperObservationPolicyV1,
    observation: dict[str, Any],
    started_at: datetime | None,
    now: datetime | None = None,
) -> tuple[bool, list[str]]:
    missing: list[str] = []
    clock = now or datetime.now(UTC)
    if started_at is None:
        missing.append("paper_started_at_missing")
        elapsed_hours = 0.0
    else:
        start = started_at if started_at.tzinfo else started_at.replace(tzinfo=UTC)
        elapsed_hours = max(0.0, (clock - start).total_seconds() / 3600.0)
    trades = observation.get("trades")
    if elapsed_hours < policy.min_hours:
        missing.append(f"observation_hours_{elapsed_hours:.2f}_lt_{policy.min_hours}")
    if trades is None or float(trades) < policy.min_trades:
        missing.append(f"paper_trades_{trades}_lt_{policy.min_trades}")
    if not observation.get("instance_matched", False):
        missing.append("paper_instance_mismatch")
    if observation.get("equity") is None:
        missing.append("paper_equity_missing")
    return not missing, missing


def observation_timed_out(
    *,
    policy: PaperObservationPolicyV1,
    started_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if started_at is None:
        return False
    clock = now or datetime.now(UTC)
    start = started_at if started_at.tzinfo else started_at.replace(tzinfo=UTC)
    elapsed_hours = (clock - start).total_seconds() / 3600.0
    limit = max(float(policy.min_hours) * 3.0, float(policy.min_hours) + 1.0, 1.0)
    return elapsed_hours >= limit


def paper_attempt(controller: ARCController) -> ARCCandidateAttemptV1 | None:
    observing = [item for item in controller.projection.attempts if item.paper_instance_id]
    if not observing:
        return None
    return observing[-1]


def observe_mission(
    controller: ARCController,
    client: PaperObservationClient | None = None,
) -> dict[str, Any]:
    """Record one observation. Window complete → live_approval_ready; timeout → operator."""
    if controller.projection.state != "paper_observing":
        return {"status": controller.projection.state, "skipped": True}
    attempt = paper_attempt(controller)
    if attempt is None or not attempt.paper_instance_id:
        controller.apply_event(
            "operator_needed",
            {"reason": "paper_instance_missing"},
        )
        return {"status": "needs_operator", "reason": "paper_instance_missing"}
    adapter: PaperObservationClient = client or BitProToolAdapter()
    observation = collect_paper_observation(attempt, adapter)
    controller.apply_event(
        "paper_observed",
        {"attempt_id": attempt.attempt_id, "observation": observation},
    )
    goal = controller.projection.goal
    policy = goal.observation if goal is not None else PaperObservationPolicyV1()
    complete, missing = observation_window_complete(
        policy=policy,
        observation=observation,
        started_at=controller.projection.paper_started_at,
    )
    if complete:
        from hypertrade.arc.live_approval import build_live_approval_package

        package = build_live_approval_package(controller.projection)
        controller.apply_event("live_approval_ready", {"package": package.model_dump(mode="json")})
        return {"status": controller.projection.state, "observation": observation}
    if observation_timed_out(policy=policy, started_at=controller.projection.paper_started_at):
        controller.apply_event(
            "operator_needed",
            {
                "reason": "paper_sample_insufficient",
                "missing": missing,
                "observation": observation,
            },
        )
        return {"status": "needs_operator", "reason": "paper_sample_insufficient"}
    return {"status": "paper_observing", "missing": missing, "observation": observation}


def observe_arc_missions_once(client: PaperObservationClient | None = None) -> dict[str, Any]:
    from hypertrade.arc.store import get_controller, list_mission_ids

    results: list[dict[str, Any]] = []
    for mission_id in list_mission_ids(state="paper_observing"):
        controller = get_controller(mission_id)
        if controller is None:
            continue
        results.append({"mission_id": mission_id, **observe_mission(controller, client)})
    return {"observed": len(results), "results": results}
