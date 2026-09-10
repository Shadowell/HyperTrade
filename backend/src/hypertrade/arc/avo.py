"""Bounded agentic variation over immutable candidates and real experiment feedback."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from jsonschema import ValidationError, validate

from hypertrade.arc.adversarial import BlueTeamQuant
from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.controller import ARCController, ARCEventV1, ARCMissionProjection
from hypertrade.arc.paper_review import request_paper_review
from hypertrade.arc.provider_hypothesis import ProviderProposal, _bounded_spec
from hypertrade.arc.self_test import ARCSelfTestService
from hypertrade.arc.store import get_controller, list_mission_ids, research_lock
from hypertrade.config import get_settings
from hypertrade.providers.chat import ChatProvider
from hypertrade.providers.runtime import ProviderRuntime
from hypertrade.research.codegen import FAMILIES, StrategyCodegenError

RESEARCH_STATES = {"created", "exploring_candidates", "mutating", "red_team_testing", "validating"}
_ID = {"type": "string", "minLength": 1, "maxLength": 128}
_PARAMETERS = {
    "stop": {
        "type": "object",
        "properties": {"reason": {"type": "string", "minLength": 1, "maxLength": 500}},
        "required": ["reason"],
        "additionalProperties": False,
    },
    "inspect": {
        "type": "object",
        "properties": {
            "target": {"enum": ["knowledge", "lineage", "candidate"]},
            "attempt_id": _ID,
        },
        "required": ["target"],
        "additionalProperties": False,
    },
    "propose": {
        "type": "object",
        "properties": {
            "hypothesis": {"type": "string", "minLength": 1, "maxLength": 400},
            "family_key": {"enum": [family.key for family in FAMILIES]},
            "direction": {"enum": ["long_only", "short_only", "long_short"]},
            "parameter_bounds": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {"min": {"type": "number"}, "max": {"type": "number"}},
                    "required": ["min", "max"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["hypothesis", "family_key", "direction", "parameter_bounds"],
        "additionalProperties": False,
    },
    "develop": {
        "type": "object",
        "properties": {"attempt_id": _ID},
        "required": ["attempt_id"],
        "additionalProperties": False,
    },
    "finish": {
        "type": "object",
        "properties": {"attempt_id": _ID},
        "required": ["attempt_id"],
        "additionalProperties": False,
    },
}
_DESCRIPTIONS = {
    "stop": "End research honestly when evidence or budget cannot support a candidate.",
    "inspect": "Read bounded strategy knowledge, candidate lineage or one candidate.",
    "propose": "Compile an immutable candidate using known parameters.",
    "develop": "Run a real BitPro experiment on the development window and inspect feedback.",
    "finish": "Freeze a developed candidate for final validation, then human review.",
}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": _DESCRIPTIONS[name],
            "parameters": parameters,
        },
    }
    for name, parameters in _PARAMETERS.items()
]
_SYSTEM = """You are a strategy research agent using agentic variation operators.
Use tools to investigate, propose, run development experiments and repair failures.
Read knowledge for parameter names/ranges. Use observed results, not invented performance.
Choose your investigation order. Only finish a candidate already developed.
The final validation window is hidden from iterative feedback. Finish ends the research attempt.
Never change budgets, evaluation criteria, permissions, running strategies or approvals.
No Paper/live actions exist here. Use stop to end honestly without a winner.
The server budget and remaining quotas are CURRENT totals including ALL actions in history
and this model request. Never add historical tool calls or candidates to those totals again.
Use remaining directly; candidate_ids are already counted. Zero candidate slots still allows
developing or finishing existing candidates. Use final_backtests_reserved;
optimization includes a baseline comparison.
"""


_STOP_MESSAGES = {
    "avo_validation_policy_unsupported": "当前研究仅支持基础窗口验证，不能声明已执行其他验证策略",
    "avo_provider_unavailable": "研究模型暂不可用，请检查配置或额度",
    "avo_effect_unknown": "操作结果尚未确认，需要先核对，系统不会盲目重复执行",
    "avo_fresh_validation_window_required": "最终验证窗口已使用，不能再用其结果继续调参",
    "avo_model_budget_exhausted": "模型调用预算已用尽，可明确追加预算后继续",
    "avo_tool_budget_exhausted": "工具调用预算已用尽，可明确追加预算后继续",
    "avo_wall_budget_exhausted": "研究时间预算已用尽",
    "avo_model_returned_no_action": "模型未返回可执行的研究操作",
    "avo_invalid_tool_batch": "模型返回了无效或重复的操作标识",
    "avo_context_budget_exhausted": "研究上下文达到上限，请缩小研究范围",
}


class ResearchStopped(Exception):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str)


def reduce_avo_event(projection: ARCMissionProjection, event: ARCEventV1) -> None:
    state, payload = projection.avo, event.payload
    goal = projection.goal
    if goal is None:
        raise ValueError("AVO goal missing")
    kind = event.event_type
    if kind == "avo_initialized":
        state.update(
            messages=payload["messages"], started_at=event.timestamp.isoformat(), awaiting=[]
        )
    elif kind == "avo_model_requested":
        state["phase"] = "research"
        goal.budget.model_calls_used += 1
        state["pending"] = {"kind": "model", **payload}
    elif kind == "avo_model_replied":
        state.setdefault("messages", []).append(payload["message"])
        state["awaiting"] = list(payload["calls"])
        state["pending"] = None
        state["last_usage"] = payload["usage"]
    elif kind == "avo_model_abandoned":
        state["pending"] = None
        state["usage_unknown"] = True
    elif kind == "avo_tool_requested":
        state["phase"] = {"develop": "development", "finish": "final"}.get(
            str(payload.get("name") or ""), "research"
        )
        goal.budget.tool_calls_used += 1
        state["pending"] = {"kind": "tool", **payload}
    elif kind == "avo_tool_finished":
        if (state.get("pending") or {}).get("id") != payload["id"]:
            raise ValueError("AVO tool receipt does not match its request")
        state.setdefault("messages", []).append(
            {
                "role": "tool",
                "tool_call_id": payload["id"],
                "content": _json(payload["result"]),
            }
        )
        state["awaiting"] = [
            call for call in state.get("awaiting", []) if call["id"] != payload["id"]
        ]
        state["pending"] = None
        if payload.get("recovered") and not state.get("final_window_consumed"):
            projection.state = "exploring_candidates"
    elif kind in {"avo_development_requested", "avo_final_requested", "avo_baseline_requested"}:
        goal.budget.backtests_used += 1
        if kind in {"avo_final_requested", "avo_baseline_requested"}:
            state["final_window_consumed"] = True
        projection.state = "validating"
    elif kind == "avo_baseline_result":
        state["baseline_final"] = payload
    elif kind == "avo_development_result":
        state["phase"] = "research"
        state.setdefault("development", {})[payload["attempt_id"]] = payload["result"]
        projection.state = "exploring_candidates"
    elif kind == "avo_unknown_result":
        state["unknown_result"] = dict(payload)


def _context(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = [i for i, message in enumerate(messages) if message["role"] == "assistant"]
    if not groups:
        return messages
    for start in groups[-6:]:
        bounded = messages[:2] + messages[start:]
        if len(_json(bounded)) <= 64_000:
            return bounded
    raise ResearchStopped("avo_context_budget_exhausted")


def _check_budget(controller: ARCController, *, model: bool = False) -> None:
    goal = controller.projection.goal
    assert goal is not None
    budget = goal.budget
    started = datetime.fromisoformat(controller.projection.avo["started_at"]).replace(tzinfo=UTC)
    if (datetime.now(UTC) - started).total_seconds() >= budget.max_wall_seconds:
        raise ResearchStopped("avo_wall_budget_exhausted")
    used, limit = (
        (budget.model_calls_used, budget.max_model_calls)
        if model
        else (
            budget.tool_calls_used,
            budget.max_tool_calls,
        )
    )
    if used >= limit:
        raise ResearchStopped(
            "avo_model_budget_exhausted" if model else "avo_tool_budget_exhausted"
        )


def _candidate(controller: ARCController, attempt_id: str) -> ARCCandidateAttemptV1:
    for candidate in controller.projection.attempts:
        if candidate.attempt_id == attempt_id:
            return candidate
    raise ValueError("candidate is not in this research lineage")


def _perform(
    controller: ARCController,
    name: str,
    arguments: dict[str, Any],
    experiments: ARCSelfTestService,
    check_owner: Callable[[], None] | None = None,
) -> dict[str, Any]:
    goal = controller.projection.goal
    assert goal is not None
    budget = goal.budget
    validate(arguments, _PARAMETERS[name])
    if name == "stop":
        controller.apply_event(
            "operator_needed", {"reason": "avo_no_candidate", "message": arguments["reason"]}
        )
        return {"research_finished": True, "reason": arguments["reason"]}
    if name == "inspect":
        if arguments["target"] == "knowledge":
            return {
                "families": [
                    {
                        "key": f.key,
                        "label": f.label,
                        "parameters": [asdict(p) for p in f.parameters],
                    }
                    for f in FAMILIES
                ]
            }
        if arguments["target"] == "candidate":
            candidate = _candidate(controller, arguments.get("attempt_id", ""))
            return {
                **candidate.model_dump(mode="json"),
                "development": controller.projection.avo.get("development", {}).get(
                    candidate.attempt_id
                ),
            }
        return {
            "candidates": [
                {"attempt_id": a.attempt_id, "hypothesis": a.hypothesis, "spec": a.strategy_spec}
                for a in controller.projection.attempts
            ],
            "development": controller.projection.avo.get("development", {}),
        }
    if name == "propose":
        if budget.candidates_used >= budget.max_candidates:
            raise ValueError(
                "candidate budget exhausted; inspect/develop/finish an existing candidate"
            )
        parent = goal.feedback_parent
        baseline_spec = (parent or {}).get("baseline", {}).get("strategy_spec", {})
        if parent and (
            arguments["family_key"] != baseline_spec.get("family")
            or arguments["direction"] != baseline_spec.get("direction")
        ):
            raise ValueError("parameter optimization must preserve source family and direction")
        family = next(f for f in FAMILIES if f.key == arguments["family_key"])
        parameters = {p.name: p for p in family.parameters}
        for key, pair in arguments["parameter_bounds"].items():
            if key not in parameters or not all(math.isfinite(v) for v in pair.values()):
                raise ValueError("unknown or nonfinite parameter")
            parameter = parameters[key]
            if not parameter.minimum <= pair["min"] <= pair["max"] <= parameter.maximum:
                raise ValueError("parameter range exceeds declared limits")
            if parameter.integral and any(int(v) != v for v in pair.values()):
                raise ValueError("parameter requires integer bounds")
        spec = _bounded_spec(
            arguments,
            objective=goal.objective,
            symbol=goal.symbols[0],
            timeframe=goal.timeframes[0],
        )
        if spec is None:
            raise ValueError("strategy spec rejected")
        model_request = next(
            event.payload
            for event in reversed(controller.projection.events)
            if event.event_type == "avo_model_requested"
        )
        proposal = ProviderProposal(
            spec,
            arguments["hypothesis"],
            str(model_request["provider"]),
            str(model_request["model"]),
            str(model_request["request_hash"]),
        )
        if parent:
            # Risk overlays remain source parameters; the model varies family parameters only.
            for key, value in baseline_spec.get("tunable_parameters", {}).items():
                if key not in parameters:
                    spec["parameter_bounds"][key] = {"min": value, "max": value}
            for key, value in baseline_spec.get("tunable_parameters", {}).items():
                spec["parameter_bounds"].setdefault(key, {"min": value, "max": value})
        candidate = BlueTeamQuant().propose_from_provider(proposal)
        if parent and candidate.strategy_spec["tunable_parameters"] == baseline_spec.get(
            "tunable_parameters"
        ):
            raise ValueError("parameter optimization must change at least one source parameter")
        if parent and candidate.strategy_spec["risk_overlays"] != baseline_spec.get(
            "risk_overlays"
        ):
            raise ValueError("parameter optimization cannot change source risk overlays")
        code_hash = hashlib.sha256(candidate.strategy_code.encode()).hexdigest()
        for old in controller.projection.attempts:
            if hashlib.sha256(old.strategy_code.encode()).hexdigest() == code_hash:
                return {"attempt_id": old.attempt_id, "duplicate": True, "code_sha256": code_hash}
        candidate.attempt_id = f"att_avo_{code_hash[:24]}"
        candidate.candidate_id = f"cand_avo_{code_hash[:24]}"
        candidate.strategy_spec["variation_operator"] = "avo"
        controller.apply_event("candidate_proposed", {"attempt": candidate.model_dump(mode="json")})
        return {"attempt_id": candidate.attempt_id, "code_sha256": code_hash}
    candidate = _candidate(controller, arguments["attempt_id"])
    final = name == "finish"
    development = controller.projection.avo.get("development", {})
    if final and candidate.attempt_id not in development:
        raise ValueError("develop this immutable candidate before final validation")
    reserve = 2 if goal.feedback_parent else 1
    if final and goal.feedback_parent and budget.max_backtests - budget.backtests_used < 2:
        raise ValueError("two backtests are required for the frozen baseline comparison")
    if budget.backtests_used >= budget.max_backtests - (0 if final else reserve):
        raise ValueError(f"backtest budget exhausted; final validation reserves {reserve} slots")
    if final and goal.feedback_parent:
        baseline = ARCCandidateAttemptV1.model_validate(goal.feedback_parent["baseline"])
        controller.apply_event("avo_baseline_requested", {"attempt_id": baseline.attempt_id})
        try:
            baseline_result = experiments.run(baseline, goal, purpose="final")
        except Exception as exc:
            raise ResearchStopped("avo_effect_unknown") from exc
        if not baseline_result.backtest_id:
            raise ResearchStopped("avo_effect_unknown")
        controller.apply_event("avo_baseline_result", asdict(baseline_result))
        # A baseline run may take minutes. Recheck ownership/time before the second effect.
        if check_owner is not None:
            check_owner()
        started = datetime.fromisoformat(controller.projection.avo["started_at"]).replace(
            tzinfo=UTC
        )
        if (datetime.now(UTC) - started).total_seconds() >= budget.max_wall_seconds:
            raise ResearchStopped("avo_wall_budget_exhausted")
    controller.apply_event(
        "avo_final_requested" if final else "avo_development_requested",
        {"attempt_id": candidate.attempt_id},
    )
    try:
        result = experiments.run(candidate, goal, purpose="final" if final else "development")
    except Exception as exc:
        raise ResearchStopped("avo_effect_unknown") from exc
    if final and goal.feedback_parent:
        from hypertrade.arc.feedback import compare_backtests

        baseline_receipt = controller.projection.avo["baseline_final"]
        comparison = compare_backtests(result.metrics, baseline_receipt)
        result = replace(
            result,
            passed=result.passed and comparison["passed"],
            metrics={**result.metrics, "baseline_comparison": comparison},
            reasons=list(result.reasons)
            + ([] if comparison["passed"] else ["baseline_not_improved"]),
        )
    payload = {
        "attempt_id": candidate.attempt_id,
        **asdict(result),
        "tool_call_id": (controller.projection.avo.get("pending") or {}).get("id"),
        "code_sha256": hashlib.sha256(candidate.strategy_code.encode()).hexdigest(),
        "purpose": "final" if final else "development",
    }
    if not result.backtest_id:
        controller.apply_event("avo_unknown_result", payload)
        raise ResearchStopped("avo_effect_unknown")
    if not final:
        controller.apply_event(
            "avo_development_result", {"attempt_id": candidate.attempt_id, "result": payload}
        )
        return payload
    controller.apply_event("bitpro_self_tested", payload)
    if result.passed:
        request_paper_review(controller)
    else:
        controller.apply_event("operator_needed", {"reason": "avo_final_validation_failed"})
    # Final numbers go to human evidence, never to another model research turn.
    return {"attempt_id": candidate.attempt_id, "research_finished": True}


def run_avo_research(
    mission_id: str,
    *,
    provider: ChatProvider | None = None,
    experiments: ARCSelfTestService | None = None,
) -> dict[str, Any]:
    with research_lock(mission_id) as check_owner:
        if check_owner is None:
            return {"status": "busy", "mission_id": mission_id}
        controller = get_controller(mission_id)
        if controller is None or controller.projection.goal is None:
            return {"status": "missing", "mission_id": mission_id}
        if not needs_research(controller.projection):
            return {"status": controller.projection.state, "mission_id": mission_id}
        try:
            _run(controller, provider, experiments or ARCSelfTestService(), check_owner)
        except ResearchStopped as exc:
            controller.apply_event(
                "operator_needed",
                {"reason": str(exc), "message": _STOP_MESSAGES.get(str(exc), "研究需要人工检查")},
            )
        except Exception:
            controller.apply_event("operator_needed", {"reason": "avo_runtime_interrupted"})
        return {"status": controller.projection.state, "mission_id": mission_id}


def _run(
    controller: ARCController,
    provider: ChatProvider | None,
    experiments: ARCSelfTestService,
    check_owner: Callable[[], None],
) -> None:
    goal, state = controller.projection.goal, controller.projection.avo
    assert goal is not None
    if (
        goal.research_mode != "avo"
        or not goal.paper_review_required
        or goal.research_windows is None
    ):
        raise ResearchStopped("avo_protocol_missing")
    if goal.success_criteria.required_validation_policy != "arc_windowed_v1":
        raise ResearchStopped("avo_validation_policy_unsupported")
    _recover_receipt(controller)
    if controller.projection.state not in RESEARCH_STATES:
        return
    state = controller.projection.avo
    pending = state.get("pending") or {}
    if pending.get("kind") == "tool":
        raise ResearchStopped("avo_effect_unknown")
    if state.get("final_window_consumed"):
        raise ResearchStopped("avo_fresh_validation_window_required")
    if pending.get("kind") == "model":
        # Model output was not journalled, so none of its tools ran. Its budget was
        # charged before dispatch; retrying consumes another call, never a free retry.
        controller.apply_event("avo_model_abandoned", {"reason": "unacknowledged_model_call"})
    if goal.model_name and goal.provider_name not in {"codex", "vide_coding"}:
        raise ResearchStopped("avo_provider_unavailable")
    if provider is None:
        try:
            provider = ProviderRuntime(get_settings()).get_chat_provider(
                selected=goal.provider_name, selected_model=goal.model_name
            )
        except Exception as exc:
            raise ResearchStopped("avo_provider_unavailable") from exc
    if provider is None:
        raise ResearchStopped("avo_provider_unavailable")
    if not state.get("messages"):
        controller.apply_event("goal_compiled", {"goal": goal.model_dump(mode="json")})
        controller.apply_event(
            "avo_initialized",
            {
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {
                        "role": "user",
                        "content": _json(
                            {
                                "objective": goal.objective,
                                "symbols": goal.symbols,
                                "timeframes": goal.timeframes,
                                "development_window": goal.research_windows.window("development"),
                                "budget": goal.budget.model_dump(mode="json"),
                                "criteria": goal.success_criteria.model_dump(mode="json"),
                            }
                        ),
                    },
                ]
            },
        )
    while controller.projection.state in RESEARCH_STATES:
        check_owner()
        state = controller.projection.avo
        if not state.get("awaiting"):
            _check_budget(controller, model=True)
            messages = [dict(message) for message in _context(state["messages"])]
            current_goal = controller.projection.goal
            assert current_goal is not None
            runtime_context = json.loads(messages[1]["content"])
            # Present the same post-reservation totals the ledger will have before dispatch.
            # Historical tool messages are evidence, never additional budget consumption.
            if current_goal.feedback_parent:
                runtime_context["optimization"] = {
                    "baseline_spec": current_goal.feedback_parent["baseline"]["strategy_spec"],
                    "paper_feedback": current_goal.feedback_parent["evidence"],
                    "rule": (
                        "Preserve source family/direction/risk overlays; "
                        "change family parameters only. "
                        "Finish compares baseline and candidate on the same frozen window."
                    ),
                }
            reserve = 2 if current_goal.feedback_parent else 1
            runtime_context["final_backtests_reserved"] = reserve
            budget = current_goal.budget.model_dump(mode="json")
            budget["model_calls_used"] += 1
            runtime_context["budget"] = budget
            runtime_context["budget_semantics"] = (
                "current_server_totals_including_history_and_this_model_request"
            )
            runtime_context["remaining"] = {
                "candidates": max(0, budget["max_candidates"] - budget["candidates_used"]),
                "model_calls": max(0, budget["max_model_calls"] - budget["model_calls_used"]),
                "tool_calls": max(0, budget["max_tool_calls"] - budget["tool_calls_used"]),
                "backtests": max(0, budget["max_backtests"] - budget["backtests_used"]),
                "development_backtests": max(
                    0, budget["max_backtests"] - budget["backtests_used"] - reserve
                ),
            }
            runtime_context["candidate_ids"] = [
                candidate.attempt_id for candidate in controller.projection.attempts
            ]
            # Refresh instructions too when resuming tasks initialized by an older worker.
            messages[0]["content"] = _SYSTEM
            messages[1]["content"] = _json(runtime_context)
            controller.apply_event(
                "avo_model_requested",
                {
                    "provider": provider.name,
                    "model": provider.model,
                    "request_hash": hashlib.sha256(
                        _json(
                            {
                                "messages": messages,
                                "tools": TOOLS,
                                "provider": provider.name,
                                "model": provider.model,
                            }
                        ).encode()
                    ).hexdigest(),
                    "budget_snapshot": runtime_context["budget"],
                },
            )
            try:
                response = provider.chat(messages, tools=TOOLS)
            except Exception as exc:
                raise ResearchStopped("avo_provider_unavailable") from exc
            calls = [asdict(call) for call in response.tool_calls]
            seen_ids = {
                event.payload.get("id")
                for event in controller.projection.events
                if event.event_type == "avo_tool_requested"
            }
            if (
                len(calls) > 4
                or len({call["id"] for call in calls}) != len(calls)
                or any(not call["id"] or call["id"] in seen_ids for call in calls)
            ):
                raise ResearchStopped("avo_invalid_tool_batch")
            message: dict[str, Any] = {
                "role": "assistant",
                "content": "" if calls else response.content[:1000] or "No action returned",
            }
            if calls:
                message["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": _json(call["arguments"])},
                    }
                    for call in calls
                ]
            controller.apply_event(
                "avo_model_replied",
                {
                    "calls": calls,
                    "usage": response.usage.to_dict(),
                    "message": message,
                },
            )
            if not calls:
                raise ResearchStopped("avo_model_returned_no_action")
        call = controller.projection.avo["awaiting"][0]
        _check_budget(controller)
        check_owner()
        controller.apply_event("avo_tool_requested", call)
        try:
            if call["name"] not in _PARAMETERS or len(_json(call["arguments"])) > 16_000:
                raise ValueError("tool or argument size denied")
            result = _perform(controller, call["name"], call["arguments"], experiments, check_owner)
            if len(_json(result)) > 24_000:
                result = {"status": "result_too_large", "hint": "inspect a single candidate"}
        except (ValueError, ValidationError, StrategyCodegenError) as exc:
            result = {"status": "rejected", "reason": str(exc)[:500]}
        controller.apply_event("avo_tool_finished", {"id": call["id"], "result": result})


def _recorded_receipt(projection: ARCMissionProjection) -> dict[str, Any] | None:
    pending = projection.avo.get("pending") or {}
    if pending.get("kind") != "tool":
        return None
    attempt_id = (pending.get("arguments") or {}).get("attempt_id")
    candidate = next((a for a in projection.attempts if a.attempt_id == attempt_id), None)
    if candidate is None:
        return None
    if pending.get("name") == "develop":
        records = [projection.avo.get("development", {}).get(attempt_id, {})]
    elif pending.get("name") == "finish":
        records = list(reversed(projection.self_test_records))
    else:
        return None
    for record in records:
        if (
            record.get("tool_call_id") == pending.get("id")
            and record.get("attempt_id") == attempt_id
            and record.get("backtest_id")
            and record.get("code_sha256")
            == hashlib.sha256(candidate.strategy_code.encode()).hexdigest()
        ):
            return dict(record)
    return None


def needs_research(projection: ARCMissionProjection) -> bool:
    if projection.goal is None or projection.goal.research_mode != "avo":
        return False
    return projection.state in RESEARCH_STATES or (
        projection.state in {"paper_authorizing", "paper_review_ready", "needs_operator"}
        and _recorded_receipt(projection) is not None
    )


def _recover_receipt(controller: ARCController) -> None:
    """Finish journalling only an exact action/code-bound receipt. Never reuse stale feedback."""
    result = _recorded_receipt(controller.projection)
    if result is None:
        return
    pending = controller.projection.avo["pending"]
    if pending["name"] == "finish":
        if result.get("passed"):
            if controller.projection.state != "paper_review_ready":
                controller.apply_event("candidate_validated", result)
                request_paper_review(controller)
        else:
            controller.apply_event("operator_needed", {"reason": "avo_final_validation_failed"})
        result = {"attempt_id": result["attempt_id"], "research_finished": True}
    controller.apply_event(
        "avo_tool_finished", {"id": pending["id"], "result": result, "recovered": True}
    )


def run_pending_avo_once() -> dict[str, Any]:
    for mission_id in list_mission_ids():
        controller = get_controller(mission_id)
        if controller is not None and needs_research(controller.projection):
            result = run_avo_research(mission_id)
            if result["status"] != "busy":
                return result
    return {"status": "idle"}
