"""Approval-bound BitPro live promote. Agents cannot reach this through call_tool."""

from __future__ import annotations

from typing import Any, Protocol

from hypertrade.arc.controller import ARCController
from hypertrade.arc.live_approval import assert_approvable, build_live_approval_package
from hypertrade.bitpro.mcp import BitProToolAdapter


class LivePromoteClient(Protocol):
    def authorized_live_promote(
        self,
        *,
        strategy_id: int,
        approval_package_hash: str,
        mandate: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]: ...


class BitProLivePromoteClient:
    """Narrow port: only a frozen approval package hash plus mandate may promote."""

    def __init__(self, adapter: LivePromoteClient | None = None) -> None:
        self._adapter = adapter

    def live_promote(
        self,
        *,
        approval_package_hash: str,
        mandate: dict[str, Any],
        strategy_id: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not str(approval_package_hash or "").strip():
            raise PermissionError("live_promote requires approval_package_hash")
        adapter: LivePromoteClient = self._adapter or BitProToolAdapter()
        return adapter.authorized_live_promote(
            strategy_id=int(strategy_id),
            approval_package_hash=approval_package_hash,
            mandate=mandate,
            idempotency_key=idempotency_key,
        )


def decide_live_approval(
    controller: ARCController,
    *,
    decision: str,
    reason: str,
    operator_id: str,
    idempotency_key: str,
    force: bool = False,
    client: LivePromoteClient | None = None,
) -> dict[str, Any]:
    if controller.projection.state == "live_canary" and decision == "approve":
        attempt = next(
            (item for item in controller.projection.attempts if item.live_instance_id),
            None,
        )
        return {
            "status": "live_canary",
            "idempotent": True,
            "live_instance_id": attempt.live_instance_id if attempt else None,
        }
    package = controller.projection.live_approval or build_live_approval_package(
        controller.projection
    )
    if decision == "approve":
        assert_approvable(package, force=force)
        controller.apply_event(
            "live_decided",
            {
                "decision": "approved",
                "reason": reason,
                "operator_id": operator_id,
                "idempotency_key": idempotency_key,
                "package_hash": package.package_hash,
                "force": force,
            },
        )
        return promote_approved_mission(controller, client=client, idempotency_key=idempotency_key)
    if decision != "reject":
        raise ValueError(f"unsupported live decision: {decision}")
    controller.apply_event(
        "live_decided",
        {
            "decision": "rejected",
            "reason": reason,
            "operator_id": operator_id,
            "idempotency_key": idempotency_key,
            "package_hash": package.package_hash,
        },
    )
    return {"status": controller.projection.state, "decision": "rejected"}


def promote_approved_mission(
    controller: ARCController,
    *,
    client: LivePromoteClient | None = None,
    idempotency_key: str,
) -> dict[str, Any]:
    package = controller.projection.live_approval
    if package is None:
        raise PermissionError("no live approval package")
    if controller.projection.state not in {"approved_pending_effect", "live_canary"}:
        raise PermissionError("mission is not approved for live promote")
    if controller.projection.state == "live_canary":
        attempt = next(
            (item for item in controller.projection.attempts if item.live_instance_id),
            None,
        )
        return {
            "status": "live_canary",
            "idempotent": True,
            "live_instance_id": attempt.live_instance_id if attempt else None,
        }
    strategy_id = package.strategy.get("bitpro_strategy_id")
    if strategy_id is None:
        raise PermissionError("approval package missing bitpro_strategy_id")
    promoter = BitProLivePromoteClient(client)
    result = promoter.live_promote(
        approval_package_hash=package.package_hash,
        mandate=dict(package.live_intent),
        strategy_id=int(strategy_id),
        idempotency_key=idempotency_key or f"arc-live-{package.package_hash}",
    )
    if result.get("status") != "ok":
        controller.apply_event(
            "operator_needed",
            {
                "reason": result.get("reason") or "live_promote_unhealthy",
                "promote": result,
            },
        )
        return {
            "status": controller.projection.state,
            "pending_effect": True,
            "promote": result,
        }
    live_id = _live_id(result)
    attempt_id = package.strategy.get("attempt_id")
    controller.apply_event(
        "live_promoted",
        {
            "attempt_id": attempt_id,
            "live_instance_id": live_id,
            "package_hash": package.package_hash,
            "promote": {key: result.get(key) for key in ("status", "promotion")},
        },
    )
    return {
        "status": controller.projection.state,
        "live_instance_id": live_id,
        "package_hash": package.package_hash,
    }


def revoke_live_approval(
    controller: ARCController,
    *,
    operator_id: str,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    controller.apply_event(
        "live_revoked",
        {
            "operator_id": operator_id,
            "reason": reason,
            "idempotency_key": idempotency_key,
        },
    )
    return {"status": controller.projection.state, "revoked": True}


def _live_id(payload: dict[str, Any]) -> str | None:
    promotion = payload.get("promotion")
    if isinstance(promotion, dict):
        for key in ("live_instance_id", "instance_id", "id", "operation_id", "strategy_id"):
            value = promotion.get(key)
            if value is not None and str(value).strip():
                return str(value)
    for key in ("live_instance_id", "instance_id"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None
