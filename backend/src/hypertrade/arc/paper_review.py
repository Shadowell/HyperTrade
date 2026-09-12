"""Version-bound human Paper review. Model proposals never authorize execution."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from hypertrade.arc.contracts import PaperPreauthorizationV1
from hypertrade.arc.incubation import ARCPaperIncubationResolver
from hypertrade.arc.universe import candidate_symbol

if TYPE_CHECKING:
    from hypertrade.arc.controller import ARCController, ARCMissionProjection


def build_paper_review(
    projection: ARCMissionProjection,
    *,
    newly_validated: bool = False,
) -> dict[str, Any]:
    stored = projection.paper_review
    selected = next(
        (a for a in projection.attempts if a.attempt_id == stored.get("attempt_id")),
        next((a for a in reversed(projection.attempts) if a.state == "validated"), None),
    )
    goal = projection.goal
    unknowns = []
    if selected is None:
        unknowns.append("missing_validated_candidate")
    for key in ("bitpro_strategy_id", "bitpro_backtest_id", "validation_id"):
        if selected is None or not getattr(selected, key):
            unknowns.append(f"missing_{key}")
    if goal is None or not goal.paper_review_required:
        unknowns.append("paper_review_protocol_required")
    selected_symbols = []
    if selected is not None and goal is not None:
        try:
            selected_symbols = [candidate_symbol(selected.strategy_spec, goal.symbols)]
        except ValueError as exc:
            unknowns.append(str(exc))
    binding: dict[str, Any] = {
        "schema_version": "paper_review.v1",
        "mission_id": projection.mission_id,
        "attempt_id": selected.attempt_id if selected else None,
        "strategy": {
            "candidate_id": selected.candidate_id if selected else None,
            "bitpro_strategy_id": selected.bitpro_strategy_id if selected else None,
            "code_sha256": hashlib.sha256(selected.strategy_code.encode()).hexdigest()
            if selected
            else None,
            "spec": selected.strategy_spec if selected else {},
        },
        "backtest": {
            "backtest_id": selected.bitpro_backtest_id if selected else None,
            "validation_id": selected.validation_id if selected else None,
            "metrics": selected.observed_metrics if selected else {},
        },
        "criteria": goal.success_criteria.model_dump(mode="json") if goal else {},
        "feedback_policy": goal.feedback.model_dump(mode="json") if goal else {},
        "paper_configuration": {
            "initial_equity": str(goal.paper_initial_equity) if goal else "100",
            "symbols": selected_symbols,
            "exchange": "okx",
            "loop_interval_sec": 60,
        },
    }
    if selected is not None and selected.strategy_spec.get("execution_policy"):
        binding["paper_configuration"]["execution_policy"] = selected.strategy_spec[
            "execution_policy"
        ]
    if goal is not None and goal.research_windows is not None:
        binding["research_windows"] = goal.research_windows.model_dump(mode="json")
    if goal is not None and goal.feedback_parent:
        binding["feedback_parent"] = goal.feedback_parent
        comparison = (selected.observed_metrics if selected else {}).get("baseline_comparison", {})
        if comparison.get("passed") is not True or not comparison.get("backtest_id"):
            unknowns.append("missing_or_failed_baseline_comparison")
    try:
        digest = hashlib.sha256(
            json.dumps(
                binding,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
    except (ValueError, TypeError):
        digest = ""
        unknowns.append("invalid_review_values")
    if stored.get("package_hash") and stored["package_hash"] != digest and not newly_validated:
        unknowns.append("review_evidence_changed")
    status = "incomplete" if unknowns else "ready"
    if digest and stored.get("package_hash") == digest and not unknowns:
        status = str(stored.get("status") or status)
    return {
        **binding,
        "package_hash": digest,
        "status": status,
        "unknowns": unknowns,
        "kind": "paper",
        "recommendation": "review",
    }


def request_paper_review(controller: ARCController) -> dict[str, Any]:
    package = build_paper_review(
        controller.projection,
        newly_validated=controller.projection.state == "paper_authorizing",
    )
    if controller.projection.paper_review.get("package_hash") == package["package_hash"]:
        return package
    controller.apply_event("paper_review_requested", {"package": package})
    return package


def decide_paper_review(
    controller: ARCController,
    *,
    package_hash: str,
    decision: str,
    reason: str,
    operator_id: str,
    identity_source: str,
    idempotency_key: str,
    resolver: ARCPaperIncubationResolver | None = None,
) -> dict[str, Any]:
    if decision not in {"approve", "reject"} or not all(
        value.strip() for value in (reason, operator_id, idempotency_key, package_hash)
    ):
        raise PermissionError("review requires decision, identity, reason, hash and key")
    current = build_paper_review(controller.projection)
    if current["unknowns"] or current["package_hash"] != package_hash:
        raise PermissionError("review evidence is incomplete or changed")
    stored = controller.projection.paper_review
    prior = stored.get("decision") or {}
    if prior:
        if prior.get("idempotency_key") == idempotency_key and all(
            prior.get(key) == value
            for key, value in {
                "decision": decision,
                "operator_id": operator_id,
                "package_hash": package_hash,
                "reason": reason,
                "identity_source": identity_source,
            }.items()
        ):
            return {**stored, "idempotent": True}
        raise PermissionError("review already decided or execution pending")
    # The reducer claims under the store's row lock; a competing API process cannot
    # dispatch twice. A lost/unknown receipt remains unresolved, never blindly retried.
    controller.apply_event(
        "paper_review_decided",
        {
            "package_hash": package_hash,
            "decision": decision,
            "reason": reason,
            "operator_id": operator_id,
            "identity_source": identity_source,
            "idempotency_key": idempotency_key,
        },
    )
    if decision == "reject":
        return dict(controller.projection.paper_review)
    attempt = next(
        a for a in controller.projection.attempts if a.attempt_id == current["attempt_id"]
    )
    configuration = current["paper_configuration"]
    authorization = PaperPreauthorizationV1(
        symbols=configuration["symbols"],
        max_capital_per_instance=configuration["initial_equity"],
        allowed_actions=["configure", "start", "observe"],
        policy_hash=package_hash,
    )
    runner = resolver or ARCPaperIncubationResolver()
    try:
        ok, instance, name, message = runner.resolve_and_provision_paper_trading(
            attempt,
            authorization,
        )
    except Exception as exc:
        ok, instance, name, message = False, None, None, type(exc).__name__
    controller.apply_event(
        "paper_review_effect",
        {
            "package_hash": package_hash,
            "ok": bool(ok and instance),
            "paper_instance_id": instance if ok else None,
            "strategy_name": name,
            "message": message,
        },
    )
    return dict(controller.projection.paper_review)
