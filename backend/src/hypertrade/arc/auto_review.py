"""User-enabled autonomous Paper referee. No human identity or Live authority is implied."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution import EvolutionConfig
from hypertrade.arc.evolution_models import EvolutionControl
from hypertrade.arc.feedback import compare_backtests
from hypertrade.arc.incubation import ARCPaperIncubationResolver
from hypertrade.arc.paper_review import build_paper_review, decide_paper_review
from hypertrade.arc.self_test import apply_success_criteria
from hypertrade.arc.store import get_controller, list_mission_ids, research_lock
from hypertrade.db import Database

_ACTIVE = {
    "created",
    "exploring_candidates",
    "mutating",
    "red_team_testing",
    "validating",
    "paper_authorizing",
    "paper_review_ready",
    "paper_observing",
}


def evaluate_auto_review(controller: ARCController, config: EvolutionConfig) -> dict[str, Any]:
    projection = controller.projection
    goal = projection.goal
    package = build_paper_review(projection)
    reasons = list(package["unknowns"])
    if goal is None:
        return {"decision": "block", "reasons": ["missing_goal"]}
    attempt = next((a for a in projection.attempts if a.attempt_id == package["attempt_id"]), None)
    if attempt is None:
        return {"decision": "block", "reasons": ["missing_candidate"]}
    proof = next(
        (
            r
            for r in reversed(projection.self_test_records)
            if r.get("attempt_id") == attempt.attempt_id and r.get("purpose") == "final"
        ),
        {},
    )
    if (
        not proof
        or proof.get("passed") is not True
        or proof.get("validation_id") != attempt.validation_id
        or proof.get("code_sha256") != hashlib.sha256(attempt.strategy_code.encode()).hexdigest()
        or str(proof.get("backtest_id")) != str(attempt.bitpro_backtest_id)
    ):
        reasons.append("missing_version_bound_final_receipt")
    metrics = proof.get("metrics") or {}
    passed, failed = apply_success_criteria(metrics, goal.success_criteria)
    if not passed:
        reasons.extend(failed)
    policy_passed, policy_failed = apply_success_criteria(metrics, config.paper_criteria)
    if not policy_passed:
        reasons.extend("policy: " + reason for reason in policy_failed)
    if config.paper_criteria.required_validation_policy != "arc_windowed_v1":
        reasons.append("unsupported_automatic_validation_policy")
    window = metrics.get("evaluation_window") or {}
    dates = goal.research_windows.window("final") if goal.research_windows else ()
    if (
        window.get("purpose") != "final"
        or window.get("research_id") != goal.research_id
        or [window.get("start_date"), window.get("end_date")] != [str(d) for d in dates]
    ):
        reasons.append("final_window_unverified")
    if goal.evolution_context or goal.feedback_parent:
        comparison = compare_backtests(metrics, projection.avo.get("baseline_final", {}))
        if not comparison["passed"] or not comparison.get("backtest_id"):
            reasons.append("baseline_comparison_failed")
    if Decimal(package["paper_configuration"]["initial_equity"]) > config.paper_capital:
        reasons.append("automatic_paper_capital_limit")
    if goal.live_allowed:
        reasons.append("paper_only_policy")
    return {
        "decision": "reject" if reasons else "approve",
        "reasons": reasons,
        "package_hash": package["package_hash"],
        "policy": "autonomous_paper_referee_v1",
        "live_authorized": False,
    }


def configured_review_mode(db: Database) -> Any:
    with db.session() as session:
        row = session.get(EvolutionControl, "global")
        config = EvolutionConfig.model_validate(row.config_json if row else {})
        return config.paper_review_mode if config.enabled else "human"


def auto_review_once(
    db: Database, resolver: ARCPaperIncubationResolver | None = None
) -> dict[str, Any]:
    with research_lock("autonomous-paper-review") as owner:
        if owner is None:
            return {"status": "busy"}
        # Serialize policy changes with dispatch; this does not impersonate human approval.
        with db.session() as session:
            control = session.get(EvolutionControl, "global", with_for_update=True)
            config = EvolutionConfig.model_validate(control.config_json if control else {})
            if not config.enabled or control is None:
                return {"status": "disabled"}
            for mission_id in list_mission_ids():
                with research_lock(mission_id) as check_owner:
                    if check_owner is None:
                        continue
                    controller = get_controller(mission_id)
                    if controller is None or controller.projection.goal is None:
                        continue
                    projection, goal = controller.projection, controller.projection.goal
                    if projection.state not in _ACTIVE or not goal.paper_review_required:
                        continue
                    source_id = (goal.evolution_context or {}).get("source_strategy_id")
                    if config.strategy_ids and source_id not in config.strategy_ids:
                        continue
                    if goal.paper_review_mode != config.paper_review_mode:
                        controller.apply_event(
                            "paper_review_policy_selected",
                            {
                                "mode": config.paper_review_mode,
                                "policy_revision": control.revision,
                                "authorized_by": control.updated_by,
                            },
                        )
                    if (
                        config.paper_review_mode != "agent"
                        or projection.state != "paper_review_ready"
                    ):
                        continue
                    evaluation = evaluate_auto_review(controller, config)
                    if evaluation["decision"] == "approve":
                        cost_reasons = verify_candidate_costs(controller)
                        if cost_reasons:
                            recover_with_new_candidate = set(cost_reasons) <= {
                                "cost_evidence_incomplete",
                                "cost_policy_unverified",
                                "candidate_already_has_runtime_history",
                            }
                            evaluation.update(
                                decision="reject" if recover_with_new_candidate else "block",
                                reasons=cost_reasons,
                            )
                    evaluation["policy_revision"] = control.revision
                    if projection.paper_review.get("automatic_evaluation") != evaluation:
                        controller.apply_event("paper_auto_review_evaluated", evaluation)
                    if (
                        evaluation["decision"] == "block"
                        or build_paper_review(projection)["unknowns"]
                    ):
                        return {
                            "status": "blocked",
                            "mission_id": mission_id,
                            "evaluation": evaluation,
                        }
                    check_owner()
                    result = decide_paper_review(
                        controller,
                        package_hash=evaluation["package_hash"],
                        decision=evaluation["decision"],
                        reason="Agent自动评审："
                        + (
                            "全部确定性门禁通过"
                            if not evaluation["reasons"]
                            else "; ".join(evaluation["reasons"])
                        ),
                        operator_id=f"hypertrade:paper-referee:policy-{control.revision}",
                        identity_source="agent_policy",
                        idempotency_key=f"auto-paper:{control.revision}:{evaluation['package_hash']}",
                        resolver=resolver,
                    )
                    return {"status": result["status"], "mission_id": mission_id}
            return {"status": "idle"}


def read_candidate_source(strategy_id: int) -> dict[str, Any]:
    from hypertrade.bitpro.mcp import BitProToolAdapter
    from hypertrade.bitpro.paced_reads import PacedReadClient

    source = BitProToolAdapter(PacedReadClient()).strategy_get(strategy_id=strategy_id)["strategy"]
    if not isinstance(source, dict):
        raise ValueError("invalid strategy source")
    return source


def verify_candidate_costs(controller: ARCController) -> list[str]:
    """Verify the BitPro cost-freeze contract; never duplicate its fee-selection rules."""
    try:
        package = build_paper_review(controller.projection)
        expected = package["strategy"]
        source = read_candidate_source(int(expected["bitpro_strategy_id"]))
        if str(source["id"]) != str(expected["bitpro_strategy_id"]):
            return ["cost_source_strategy_mismatch"]
        if hashlib.sha256(source["script_content"].encode()).hexdigest() != expected["code_sha256"]:
            return ["cost_source_code_changed"]
        config = source["config"]
        if (
            config.get("paper_instance_id")
            or source.get("run_started_at")
            or source.get("status") == "running"
        ):
            return ["candidate_already_has_runtime_history"]
        policy = config["_research_cost_policy"]
        values = policy["values"]
        if (
            config.get("_freeze_research_costs") is not True
            or policy.get("version") != "research_costs.v1"
            or policy.get("source") != "bitpro_backtest_cost_resolver"
            or policy.get("exchange") != "okx"
            or policy.get("market_type") != "swap"
        ):
            return ["cost_policy_unverified"]
        for key in ["taker_fee_bps", "maker_fee_bps", "slippage_bps"]:
            if (
                isinstance(values[key], bool)
                or not isinstance(values[key], (float, int))
                or not math.isfinite(values[key])
                or config[key] != values[key]
            ):
                return ["cost_values_unverified"]
        if (
            values["funding_mode"] not in {"not_modeled", "strategy_defined_or_not_modeled"}
            or config["funding_mode"] != values["funding_mode"]
        ):
            return ["funding_model_unverified"]
        digest = hashlib.sha256(
            json.dumps(
                {k: v for k, v in policy.items() if k != "hash"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        if policy.get("hash") != digest:
            return ["cost_policy_hash_mismatch"]
        return []
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        return ["cost_evidence_incomplete"]
    except Exception:
        # A read failure is not a license to provision with implicit costs.
        return ["cost_source_unavailable"]
