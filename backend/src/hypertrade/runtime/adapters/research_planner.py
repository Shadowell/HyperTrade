"""Governed planners for the Mission Runtime.

The planner is deliberately separated from execution. A model may propose a
bounded read-only plan, but the deterministic fallback and Mission policy still
own capability selection, permission scope and completion semantics.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from hashlib import sha256
from typing import Any

import anyio

from hypertrade.providers.chat import ChatProvider
from hypertrade.runtime.domain.models import (
    MissionProjection,
    PlanDiffV1,
    PlanStepV2,
    PlanV2,
    ReplanRequestV1,
)

_MARKET_TERMS = (
    "market",
    "price",
    "ticker",
    "行情",
    "价格",
    "市场",
    "btc",
    "eth",
    "sol",
)
_RESEARCH_TERMS = (
    "research",
    "strategy",
    "hypothesis",
    "evidence",
    "研究",
    "策略",
    "假设",
    "证据",
    "回测",
)
_CAPABILITY_SCHEMAS: dict[str, dict[str, Any]] = {
    "runtime.objective_inspection": {
        "type": "object",
        "required": ["objective_hash"],
    },
    "market.summary": {"type": "object", "required": ["items", "count"]},
    "rag.search": {"type": "object", "required": ["hits", "count"]},
    "memory.search": {"type": "object", "required": ["items", "count"]},
}


class DeterministicResearchPlanner:
    """Safe baseline planner for a small, reviewed research capability set.

    It is useful whenever a provider is unavailable or a provider proposal does
    not validate. Its choices are intentionally conservative and only contain
    capability ids that must still pass CatalogCapabilityPolicy at dispatch.
    """

    async def plan(self, mission: MissionProjection) -> PlanV2:
        return self._build(mission, version=1, previous=None, request=None)

    async def replan(
        self,
        mission: MissionProjection,
        previous: PlanV2,
        request: ReplanRequestV1,
    ) -> PlanV2:
        return self._build(
            mission,
            version=previous.version + 1,
            previous=previous,
            request=request,
        )

    def _build(
        self,
        mission: MissionProjection,
        *,
        version: int,
        previous: PlanV2 | None,
        request: ReplanRequestV1 | None,
    ) -> PlanV2:
        failed = request.failed_step_id if request is not None else ""
        steps = _without_step_and_rewire(_steps_for_objective(mission.objective), failed)
        if not steps:
            # An objective inspection is always a safe, source-bound terminal
            # fallback. It keeps the Mission auditable instead of fabricating a
            # provider answer after a failed data capability.
            steps = [_objective_step(mission.objective)]
        kept: tuple[str, ...] = ()
        removed: tuple[str, ...] = ()
        if previous is not None:
            next_ids = {step.step_id for step in steps}
            kept = tuple(step.step_id for step in previous.steps if step.step_id in next_ids)
            removed = tuple(step.step_id for step in previous.steps if step.step_id not in next_ids)
        assumptions: tuple[str, ...] = (
            "Only reviewed read capabilities may be dispatched.",
            "Completion is derived from validated observations, not model prose.",
        )
        if request is not None:
            assumptions += (f"Replan trigger: {request.trigger}.",)
        return PlanV2(
            plan_id=_plan_id(mission.mission_id, version),
            version=version,
            parent_version=previous.version if previous is not None else None,
            goal_interpretation=mission.objective,
            assumptions=assumptions,
            completion_checks=tuple(item.criterion_id for item in mission.success_criteria),
            steps=tuple(steps),
            diff=PlanDiffV1(
                kept=kept,
                added=tuple(step.step_id for step in steps if step.step_id not in kept),
                removed=removed,
                reason_code=request.trigger if request is not None else "initial_plan",
            ),
        )


class ProviderBackedResearchPlanner:
    """Use a provider only to propose a plan inside a fixed trusted envelope.

    Provider output is transient and never stored. Invalid, unavailable or
    over-scoped proposals fall back to the deterministic planner; the runtime
    does not turn a model parse failure into an executable tool request.
    """

    def __init__(
        self,
        *,
        provider: ChatProvider | None,
        fallback: DeterministicResearchPlanner | None = None,
    ) -> None:
        self.provider = provider
        self.fallback = fallback or DeterministicResearchPlanner()

    async def plan(self, mission: MissionProjection) -> PlanV2:
        fallback = await self.fallback.plan(mission)
        return await self._propose(mission, fallback, previous=None, request=None)

    async def replan(
        self,
        mission: MissionProjection,
        previous: PlanV2,
        request: ReplanRequestV1,
    ) -> PlanV2:
        fallback = await self.fallback.replan(mission, previous, request)
        return await self._propose(mission, fallback, previous=previous, request=request)

    async def _propose(
        self,
        mission: MissionProjection,
        fallback: PlanV2,
        *,
        previous: PlanV2 | None,
        request: ReplanRequestV1 | None,
    ) -> PlanV2:
        if self.provider is None:
            return fallback
        try:
            response = await anyio.to_thread.run_sync(
                self.provider.chat,
                _planner_messages(mission, fallback, previous, request),
            )
            return _parse_provider_plan(
                response.content,
                mission=mission,
                fallback=fallback,
                previous=previous,
                request=request,
            )
        except Exception:  # noqa: BLE001 - untrusted provider boundary falls back safely
            return fallback


def _capabilities_for_objective(objective: str) -> tuple[str, ...]:
    lowered = objective.casefold()
    capabilities = ["runtime.objective_inspection"]
    if any(term in lowered for term in _MARKET_TERMS):
        capabilities.append("market.summary")
    if any(term in lowered for term in _RESEARCH_TERMS):
        capabilities.extend(("rag.search", "memory.search"))
    return tuple(dict.fromkeys(capabilities))


def _steps_for_objective(objective: str) -> Sequence[PlanStepV2]:
    steps: list[PlanStepV2] = [_objective_step(objective)]
    previous = "inspect_objective"
    for capability_id in _capabilities_for_objective(objective)[1:]:
        if capability_id == "market.summary":
            arguments: dict[str, Any] = {"limit": 10}
            if inst_id := _requested_market_instrument(objective):
                arguments["inst_id"] = inst_id
            step = PlanStepV2(
                step_id="market_snapshot",
                title="Read the bounded current market summary",
                depends_on=(previous,),
                capability_id=capability_id,
                arguments=arguments,
                expected_output_schema=_CAPABILITY_SCHEMAS[capability_id],
            )
        elif capability_id == "rag.search":
            step = PlanStepV2(
                step_id="research_evidence",
                title="Retrieve curated research evidence",
                depends_on=(previous,),
                capability_id=capability_id,
                arguments={"query": objective[:500], "limit": 5},
                expected_output_schema=_CAPABILITY_SCHEMAS[capability_id],
            )
        else:
            step = PlanStepV2(
                step_id="memory_context",
                title="Retrieve governed prior research memory",
                depends_on=(previous,),
                capability_id=capability_id,
                arguments={"query": objective[:500], "limit": 10},
                expected_output_schema=_CAPABILITY_SCHEMAS[capability_id],
            )
        steps.append(step)
        previous = step.step_id
    return steps


def _objective_step(objective: str) -> PlanStepV2:
    return PlanStepV2(
        step_id="inspect_objective",
        title="Validate the research objective and read-only constraints",
        capability_id="runtime.objective_inspection",
        arguments={"objective": objective},
        expected_output_schema=_CAPABILITY_SCHEMAS["runtime.objective_inspection"],
    )


def _without_step_and_rewire(
    candidates: Sequence[PlanStepV2], failed_step_id: str
) -> list[PlanStepV2]:
    """Remove an unavailable step without leaving a dangling dependency edge."""

    selected = [step for step in candidates if step.step_id != failed_step_id]
    rewired: list[PlanStepV2] = []
    for step in selected:
        rewired.append(
            step.model_copy(update={"depends_on": (rewired[-1].step_id,) if rewired else ()})
        )
    return rewired


def _planner_messages(
    mission: MissionProjection,
    fallback: PlanV2,
    previous: PlanV2 | None,
    request: ReplanRequestV1 | None,
) -> list[dict[str, Any]]:
    allowed = [
        {
            "capability_id": capability_id,
            "input_schema": _input_schema_for(capability_id),
            "output_schema": _CAPABILITY_SCHEMAS[capability_id],
        }
        for capability_id in _capabilities_for_objective(mission.objective)
    ]
    instruction = {
        "role": "system",
        "content": (
            "Return JSON only. Propose a bounded read-only research plan. "
            "Use only listed capabilities, no new ids, no write operation, no approval, "
            "and no more steps than the fallback. Return keys goal_interpretation, "
            "assumptions and steps. "
            "Every step has step_id, title, depends_on, capability_id and arguments."
        ),
    }
    user = {
        "role": "user",
        "content": json.dumps(
            {
                "objective": mission.objective,
                "constraints": list(mission.constraints),
                "allowed_capabilities": allowed,
                "fallback_plan": {
                    "steps": [step.model_dump(mode="json") for step in fallback.steps]
                },
                "previous_plan": (
                    [step.model_dump(mode="json") for step in previous.steps]
                    if previous is not None
                    else []
                ),
                "replan_request": request.model_dump(mode="json") if request else None,
            },
            ensure_ascii=False,
        ),
    }
    return [instruction, user]


def _parse_provider_plan(
    content: str,
    *,
    mission: MissionProjection,
    fallback: PlanV2,
    previous: PlanV2 | None,
    request: ReplanRequestV1 | None,
) -> PlanV2:
    raw = json.loads(_json_object(content))
    if not isinstance(raw, dict):
        raise ValueError("planner response must be an object")
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) != len(fallback.steps):
        raise ValueError("planner response must retain every deterministic baseline step")
    allowed = set(_capabilities_for_objective(mission.objective))
    for item, baseline in zip(raw_steps, fallback.steps, strict=True):
        if not isinstance(item, dict):
            raise ValueError("planner step must be an object")
        capability_id = str(item.get("capability_id", ""))
        if capability_id not in allowed:
            raise ValueError("planner selected an unreviewed capability")
        arguments = item.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("planner step arguments must be an object")
        proposed_dependencies = tuple(str(value) for value in item.get("depends_on", []))
        if (
            str(item.get("step_id", "")) != baseline.step_id
            or capability_id != baseline.capability_id
            or proposed_dependencies != baseline.depends_on
            or arguments != baseline.arguments
        ):
            raise ValueError("planner cannot alter deterministic step identity or arguments")
    # A provider may be consulted, but catalog-derived dispatch remains immutable:
    # no model output can omit, reorder, or retarget an approved data read.
    return fallback


def _input_schema_for(capability_id: str) -> dict[str, Any]:
    if capability_id == "runtime.objective_inspection":
        return {"objective": "string"}
    if capability_id == "market.summary":
        return {"limit": "integer 1..50"}
    return {"query": "string", "limit": "integer"}


def _requested_market_instrument(objective: str) -> str | None:
    """Normalize an explicit ticker without treating arbitrary prose as a symbol."""

    for raw in re.findall(r"(?<![A-Z0-9])([A-Z0-9-]{2,32})(?![A-Z0-9])", objective.upper()):
        token = raw.replace("-", "")
        if token.endswith("USDTSWAP"):
            base = token[: -len("USDTSWAP")]
        elif token.endswith("USDT"):
            base = token[: -len("USDT")]
        elif token in {"BTC", "ETH", "SOL"}:
            base = token
        else:
            continue
        if len(base) >= 2 and base.isalnum():
            return f"{base}-USDT-SWAP"
    return None


def _json_object(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        cleaned = "\n".join(lines[1:-1]).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("planner response contains no JSON object")
    return cleaned[start : end + 1]


def _plan_id(mission_id: str, version: int) -> str:
    return f"plan_{sha256(f'{mission_id}:{version}'.encode()).hexdigest()[:20]}"
