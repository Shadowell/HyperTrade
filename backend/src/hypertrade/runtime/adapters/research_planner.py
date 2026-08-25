"""Governed planners for the Mission Runtime.

The planner is deliberately separated from execution. A model may propose a
bounded read-only plan, but the deterministic fallback and Mission policy still
own capability selection, permission scope and completion semantics.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from hashlib import sha256
from typing import Any

import anyio

from hypertrade.providers.chat import ChatProvider
from hypertrade.runtime.adapters.capability_catalog import CatalogCapabilityPolicy
from hypertrade.runtime.domain.models import (
    MissionProjection,
    PlanDiffV1,
    PlanStepV2,
    PlanV2,
    ReplanRequestV1,
)

logger = logging.getLogger(__name__)

_MARKET_TERMS = ("market", "price", "ticker", "行情", "价格", "市场", "合约")
# Chinese asset names never contain the ASCII ticker, so the verbatim-symbol gate
# needs an explicit, closed alias table. Only aliases listed here may validate a
# model-returned symbol against a Chinese objective; anything else still fails.
_MARKET_SYMBOL_ALIASES: dict[str, tuple[str, ...]] = {
    "BTC": ("比特币", "比特幣", "大饼"),
    "ETH": ("以太坊", "以太币", "以太"),
    "SOL": ("索拉纳", "索尔"),
    "XRP": ("瑞波币", "瑞波"),
    "DOGE": ("狗狗币", "狗狗"),
    "LTC": ("莱特币",),
    "BNB": ("币安币",),
    "ADA": ("艾达币",),
    "DOT": ("波卡币", "波卡"),
    "AVAX": ("雪崩币",),
    "LINK": ("链币",),
    "TRX": ("波场币", "波场"),
    "SHIB": ("柴犬币",),
    "PEPE": ("佩佩币",),
}
_MARKET_SYMBOL_STOPWORDS = frozenset(
    {
        "BACKTEST",
        "CONTRACT",
        "CRYPTO",
        "FUTURES",
        "MARKET",
        "OKX",
        "PERPETUAL",
        "PRICE",
        "SWAP",
        "TESTNET",
        "TICKER",
        "USD",
        "USDT",
    }
)
_BARE_MARKET_SYMBOL = re.compile(
    r"(?<![A-Z0-9])([A-Z][A-Z0-9]{1,19})\s*(?:的\s*)?(?:价格|行情|合约|永续)",
    re.IGNORECASE,
)
_PAPER_TERMS = ("paper", "模拟盘", "持仓", "仓位")
_LIVE_STRATEGY_TERMS = ("实盘策略", "真实策略", "live strategy", "live strategies")
_KNOWLEDGE_TERMS = ("知识库", "知识", "证据", "依据", "research", "研究")
_PORTFOLIO_TERMS = ("组合", "权重", "相关性", "全局市场", "监控", "告警", "暴露")
_DIRECT_CLARIFICATION_TERMS = ("现在怎么办", "看看这个策略", "分析他的交易数据")
_CAPABILITY_SCHEMAS: dict[str, dict[str, Any]] = {
    "runtime.objective_inspection": {
        "type": "object",
        "required": ["objective_hash"],
    },
    "market.summary": {"type": "object", "required": ["items", "count"]},
    "market.relative_strength": {"type": "object", "required": ["items", "count"]},
    "market.candles": {"type": "object", "required": ["items", "count"]},
    "market.derivatives": {"type": "object", "required": ["items", "count"]},
    "market.regime": {"type": "object", "required": ["items", "count"]},
    "rag.search": {"type": "object", "required": ["hits", "count"]},
    "memory.search": {"type": "object", "required": ["items", "count"]},
    "strategy.performance_summary": {
        "type": "object",
        "required": ["items", "count", "found"],
    },
    "strategy.compare": {"type": "object", "required": ["items", "count", "found"]},
    "strategy.draft": {"type": "object", "required": ["items", "count"]},
    "bitpro.live_strategy_summary": {
        "type": "object",
        "required": ["strategies", "count", "source_available"],
    },
    "bitpro.order_history": {"type": "object", "required": ["items", "count"]},
    "bitpro.meta": {"type": "object", "required": ["items", "count"]},
    "paper.summary": {"type": "object", "required": ["positions", "orders", "count"]},
    "portfolio.assessment": {"type": "object", "required": ["items", "count"]},
    "world_model.snapshot": {"type": "object", "required": ["items", "count"]},
    "monitor.summary": {"type": "object", "required": ["items", "count"]},
    "execution.intent_summary": {"type": "object", "required": ["items", "count"]},
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

    Provider output is transient and never stored. The model first extracts a
    constrained semantic intent; the policy envelope then validates entities
    against the user text and maps them to reviewed read capabilities. Invalid,
    unavailable or over-scoped output falls back to deterministic parsing; the
    runtime does not turn a model parse failure into an executable tool request.
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
            return _apply_provider_intent(response.content, mission=mission, fallback=fallback)
        except Exception:  # noqa: BLE001 - untrusted provider boundary falls back safely
            return fallback


_INSTRUMENT_ARGUMENT_KEYS = frozenset({"inst_id", "symbol", "inst_ids"})
_LLM_PLAN_MAX_STEPS = 8
_LLM_PLAN_MAX_ARGUMENT_CHARS = 200


class LlmPlanV2Planner:
    """LLM proposes the step DAG; deterministic contracts validate every step.

    Unlike :class:`ProviderBackedResearchPlanner` (model only extracts intent
    entities), this planner lets the model choose WHICH reviewed read
    capabilities to use, in what order, and with which bounded arguments. The
    trust boundary is unchanged: capabilities must resolve inside the reviewed
    read-only envelope, arguments must satisfy the catalog JSON Schema,
    market entities must be copied verbatim from the objective, and any
    validation failure falls back to the deterministic plan. Dispatch still
    re-validates through CatalogCapabilityPolicy and GovernedToolExecutor.
    """

    def __init__(
        self,
        *,
        provider: ChatProvider | None,
        fallback: DeterministicResearchPlanner | None = None,
        capabilities: Sequence[Any] | None = None,
    ) -> None:
        from hypertrade.runtime.adapters.capability_catalog import builtin_capabilities

        self.provider = provider
        self.fallback = fallback or DeterministicResearchPlanner()
        definitions = tuple(capabilities) if capabilities else builtin_capabilities()
        self._envelope: dict[str, dict[str, Any]] = {}
        # Construction keeps every capability admissible under SOME mission
        # profile (read + research_write); paper/testnet/live scopes are never
        # planner-visible. Per-mission filtering happens in
        # _envelope_for_profile at plan time.
        admissible_scopes = frozenset().union(
            *CatalogCapabilityPolicy._PROFILE_ALLOWED_SCOPES.values()
        )
        for definition in definitions:
            if (
                getattr(definition, "scope", "read") not in admissible_scopes
                or getattr(definition, "approval", "none") != "none"
            ):
                continue
            self._envelope[str(definition.capability_id)] = {
                "title": str(getattr(definition, "title", "")),
                "description": str(getattr(definition, "description", "")),
                "scope": str(getattr(definition, "scope", "read")),
                "input_schema": dict(getattr(definition, "input_schema", {}) or {}),
                "output_schema": dict(getattr(definition, "output_schema", {}) or {}),
            }

    def _envelope_for_profile(self, permission_profile_ref: str) -> dict[str, dict[str, Any]]:
        """Capabilities visible to the planner under the mission's profile.

        Mirrors CatalogCapabilityPolicy._PROFILE_ALLOWED_SCOPES so the model
        can never plan a step the dispatcher would deny.
        """
        from hypertrade.runtime.adapters.capability_catalog import CatalogCapabilityPolicy

        allowed = CatalogCapabilityPolicy._PROFILE_ALLOWED_SCOPES.get(
            permission_profile_ref, frozenset({"read"})
        )
        return {
            capability_id: spec
            for capability_id, spec in self._envelope.items()
            if spec.get("scope", "read") in allowed
        }

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
        if self.provider is None or not self._envelope:
            return fallback
        profile_envelope = self._envelope_for_profile(mission.permission_profile_ref)
        if not profile_envelope:
            return fallback
        messages = _llm_plan_messages(
            mission, fallback, previous, request, envelope=profile_envelope
        )
        # One proposal + one bounded repair round; anything worse falls back.
        for attempt in range(2):
            try:
                response = await anyio.to_thread.run_sync(self.provider.chat, messages)
                return _apply_provider_plan(
                    response.content,
                    mission=mission,
                    fallback=fallback,
                    previous=previous,
                    request=request,
                    envelope=profile_envelope,
                )
            except _PlanValidationError as exc:
                if attempt == 1:
                    logger.warning(
                        "mission LLM plan rejected after repair: %s",
                        exc.reason[:200],
                    )
                    return fallback
                messages = [
                    *messages,
                    {"role": "assistant", "content": exc.content},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "plan_rejected": exc.reason,
                                "instruction": (
                                    "Return a corrected JSON plan that satisfies every "
                                    "constraint. JSON only, no prose."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
            except Exception as exc:  # noqa: BLE001 - untrusted provider boundary falls back safely
                logger.warning(
                    "mission LLM plan provider call failed: %s", str(exc)[:200]
                )
                return fallback
        return fallback


class _PlanValidationError(ValueError):
    """Carries the raw model content so the repair round can quote it."""

    def __init__(self, reason: str, content: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.content = content


def _llm_plan_messages(
    mission: MissionProjection,
    fallback: PlanV2,
    previous: PlanV2 | None,
    request: ReplanRequestV1 | None,
    *,
    envelope: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    del fallback  # the deterministic plan is the safety net, not model context
    system = {
        "role": "system",
        "content": (
            "You are the HyperTrade mission planner. Return JSON only, no prose. "
            "Propose a short read-only research plan as "
            '{"goal_interpretation": string, "steps": [{"step_id": string, '
            '"title": string, "capability_id": string, "arguments": object, '
            '"depends_on": [string]}]}. '
            "Rules: use ONLY the listed capability ids; step arguments must obey each "
            "capability input_schema; the first step must be runtime.objective_inspection "
            "with the objective argument; market instrument ids must be copied verbatim "
            "from the objective; keep the plan under 8 steps; step_id must be "
            "snake_case and unique; depends_on must reference earlier step ids only; "
            "never propose writes, approvals, or capabilities outside the list. "
            "When suggested_capabilities is non-empty, include EVERY listed capability "
            "exactly once with its required arguments — the deterministic router "
            "matched them to the objective's own words. "
            "When suggested_instruments is non-empty, market steps must pass them via "
            "inst_id/inst_ids — the router resolved them from the objective, including "
            "Chinese asset names."
        ),
    }
    payload: dict[str, Any] = {
        "objective": mission.objective,
        "constraints": list(mission.constraints),
        "max_steps": min(mission.budget.max_steps_per_plan, _LLM_PLAN_MAX_STEPS),
        "suggested_capabilities": [
            capability_id
            for capability_id in _capabilities_for_objective(mission.objective)
            if capability_id != "runtime.objective_inspection"
        ],
        "suggested_instruments": list(_requested_market_instruments(mission.objective)),
        "capabilities": [
            {
                "capability_id": capability_id,
                "title": spec["title"],
                "description": spec["description"],
                "input_schema": spec["input_schema"],
            }
            for capability_id, spec in sorted(envelope.items())
        ],
    }
    if previous is not None:
        payload["replan"] = {
            "trigger": request.trigger if request is not None else "user_steer",
            "summary": request.summary if request is not None else "",
            "failed_step_id": request.failed_step_id if request is not None else "",
            "previous_version": previous.version,
            "previous_steps": [
                {"step_id": step.step_id, "capability_id": step.capability_id}
                for step in previous.steps
            ],
        }
    return [system, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def _apply_provider_plan(
    content: str,
    *,
    mission: MissionProjection,
    fallback: PlanV2,
    previous: PlanV2 | None,
    request: ReplanRequestV1 | None,
    envelope: dict[str, dict[str, Any]],
) -> PlanV2:
    """Validate a model-proposed DAG into a PlanV2, or raise _PlanValidationError."""

    try:
        raw = json.loads(_json_object(content))
    except (json.JSONDecodeError, ValueError) as exc:
        raise _PlanValidationError("response is not a JSON object", content) from exc
    if not isinstance(raw, dict):
        raise _PlanValidationError("plan response must be an object", content)
    goal = str(raw.get("goal_interpretation", "")).strip()
    if not (3 <= len(goal) <= 2000):
        raise _PlanValidationError("goal_interpretation must be 3..2000 chars", content)
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise _PlanValidationError("steps must be a non-empty array", content)
    max_steps = min(mission.budget.max_steps_per_plan, _LLM_PLAN_MAX_STEPS)
    if len(raw_steps) > max_steps:
        raise _PlanValidationError(f"plan exceeds {max_steps} steps", content)

    steps: list[PlanStepV2] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_steps):
        step = _validated_provider_step(
            item,
            index=index,
            envelope=envelope,
            objective=mission.objective,
            seen_ids=seen_ids,
            content=content,
        )
        steps.append(step)

    # The suggested capabilities come from the deterministic keyword router, so a
    # plan that drops them is a routing regression, not a style choice. Rejecting
    # sends the proposal through the repair round and, failing that, the
    # deterministic fallback — which routed these objectives correctly all along.
    # Research-profile missions are exempt: their authored-code plans legitimately
    # route through workspace capabilities the keyword router does not know, and
    # the executor still re-validates every step against the reviewed catalog.
    suggested = []
    if mission.permission_profile_ref not in ("research.v1",):
        suggested = [
            capability_id
            for capability_id in _capabilities_for_objective(mission.objective)
            if capability_id != "runtime.objective_inspection"
        ]
    if suggested:
        chosen = {step.capability_id for step in steps}
        missing = [capability_id for capability_id in suggested if capability_id not in chosen]
        if missing:
            raise _PlanValidationError(
                f"plan omits suggested capabilities: {','.join(missing)}",
                content,
            )

    version = previous.version + 1 if previous is not None else 1
    kept = tuple(
        step.step_id
        for step in (previous.steps if previous is not None else ())
        if step.step_id in {item.step_id for item in steps}
    )
    try:
        return PlanV2(
            plan_id=_plan_id(mission.mission_id, version),
            version=version,
            parent_version=previous.version if previous is not None else None,
            goal_interpretation=goal,
            assumptions=(
                "LLM proposed plan; every step re-validates against the reviewed "
                "capability catalog at dispatch.",
                "Only reviewed read capabilities may be dispatched.",
                "Completion is derived from validated observations, not model prose.",
                *(
                    (f"Replan trigger: {request.trigger}.",)
                    if request is not None
                    else ()
                ),
            ),
            completion_checks=tuple(item.criterion_id for item in mission.success_criteria),
            steps=tuple(steps),
            diff=PlanDiffV1(
                kept=kept,
                added=tuple(step.step_id for step in steps if step.step_id not in kept),
                removed=tuple(
                    step.step_id
                    for step in (previous.steps if previous is not None else ())
                    if step.step_id not in {item.step_id for item in steps}
                ),
                reason_code=request.trigger if request is not None else "llm_initial_plan",
            ),
        )
    except ValueError as exc:
        raise _PlanValidationError(f"plan failed contract validation: {exc}", content) from exc


def _validated_provider_step(
    item: Any,
    *,
    index: int,
    envelope: dict[str, dict[str, Any]],
    objective: str,
    seen_ids: set[str],
    content: str,
) -> PlanStepV2:
    from typing import NoReturn

    from jsonschema import Draft202012Validator
    from jsonschema import ValidationError as JsonSchemaValidationError

    def _reject(reason: str) -> NoReturn:
        raise _PlanValidationError(f"step[{index}]: {reason}", content)

    if not isinstance(item, dict):
        _reject("step must be an object")
    capability_id = str(item.get("capability_id", ""))
    spec = envelope.get(capability_id)
    if spec is None:
        _reject(f"capability {capability_id!r} is outside the reviewed read-only envelope")
    step_id = str(item.get("step_id", ""))
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", step_id):
        _reject("step_id must be snake_case")
    if step_id in seen_ids:
        _reject("duplicate step_id")
    title = str(item.get("title", "")).strip()
    if not (3 <= len(title) <= 240):
        _reject("title must be 3..240 chars")
    raw_arguments = item.get("arguments")
    if not isinstance(raw_arguments, dict):
        _reject("arguments must be an object")
    try:
        Draft202012Validator(spec["input_schema"]).validate(raw_arguments)
    except JsonSchemaValidationError as exc:
        _reject(f"arguments violate {capability_id} input_schema: {exc.message[:160]}")
    arguments: dict[str, Any] = {}
    for key, value in raw_arguments.items():
        if isinstance(value, str) and len(value) > _LLM_PLAN_MAX_ARGUMENT_CHARS:
            _reject(f"argument {key} exceeds {_LLM_PLAN_MAX_ARGUMENT_CHARS} chars")
        arguments[str(key)] = value
    strict_instruments = capability_id.startswith("market.")
    for key in sorted(set(arguments) & _INSTRUMENT_ARGUMENT_KEYS):
        values = arguments[key] if isinstance(arguments[key], list) else [arguments[key]]
        for value in values:
            if not isinstance(value, str):
                _reject(f"argument {key} must contain string instruments")
            if _validated_provider_market_instrument(value, objective) is not None:
                continue
            # BitPro research tools legitimately normalize a partial user
            # mention ("SOL") into the full instrument ("SOL-USDT-SWAP"): that
            # is derivation, not hallucination. Accept it when the base asset
            # appears verbatim in the objective. market.* data tools keep the
            # strict verbatim rule.
            base_asset = value.split("-", 1)[0].strip().upper()
            if not strict_instruments and base_asset and base_asset in str(objective).upper():
                continue
            _reject(
                f"instrument {value!r} for {key} is not verbatim in the objective"
            )
    depends_on_raw = item.get("depends_on", [])
    if not isinstance(depends_on_raw, list) or any(
        not isinstance(dep, str) for dep in depends_on_raw
    ):
        _reject("depends_on must be an array of step ids")
    seen_ids.add(step_id)
    return PlanStepV2(
        step_id=step_id,
        title=title,
        depends_on=tuple(str(dep) for dep in depends_on_raw),
        capability_id=capability_id,
        arguments=arguments,
        expected_output_schema=dict(spec["output_schema"]),
        read_only=spec.get("scope", "read") == "read",
        requires_approval=False,
    )


def build_mission_planner(settings: Any, provider: ChatProvider | None) -> Any:
    """Mission planner factory: LLM DAG proposal with deterministic safety net.

    The flag-off and no-provider paths preserve the exact pre-existing behavior
    so operators can revert without code changes.
    """
    fallback = DeterministicResearchPlanner()
    if provider is None:
        return fallback
    if not bool(getattr(settings, "mission_llm_planner_enabled", False)):
        return ProviderBackedResearchPlanner(provider=provider, fallback=fallback)
    return LlmPlanV2Planner(provider=provider, fallback=fallback)


def _capabilities_for_objective(objective: str) -> tuple[str, ...]:
    lowered = objective.casefold()
    capabilities = ["runtime.objective_inspection"]
    if _is_terminal_without_read(lowered):
        return tuple(capabilities)
    if _strategy_draft_requested(lowered):
        return (*capabilities, "strategy.draft")
    if _bitpro_meta_requested(lowered):
        return (*capabilities, "bitpro.meta")
    if _execution_intent_lookup_requested(lowered) and not _paper_lookup_requested(lowered):
        return (*capabilities, "execution.intent_summary")
    if _live_order_history_requested(lowered):
        return (*capabilities, "bitpro.order_history")
    if _live_strategy_lookup_requested(lowered):
        return (*capabilities, "bitpro.live_strategy_summary")
    if _paper_lookup_requested(lowered) and not any(
        term in lowered for term in ("回测", "backtest")
    ):
        capabilities.append("paper.summary")
        if _execution_intent_lookup_requested(lowered):
            capabilities.append("execution.intent_summary")
        return tuple(capabilities)
    if _portfolio_lookup_requested(lowered):
        if "监控" in lowered or "告警" in lowered:
            return (*capabilities, "monitor.summary")
        if "全局市场" in lowered or "继续持有" in lowered or "降低风险" in lowered:
            return (*capabilities, "world_model.snapshot")
        return (*capabilities, "portfolio.assessment")
    if _knowledge_lookup_requested(lowered):
        if "记忆" in lowered and "来源" in lowered:
            return (*capabilities, "memory.search")
        if "历史记忆" in lowered:
            return (*capabilities, "memory.search")
        if "记忆" in lowered and "没有记录" in lowered:
            return (*capabilities, "memory.search", "strategy.performance_summary")
        if "知识库里有" in lowered:
            return (*capabilities, "rag.search")
        if _market_lookup_requested(lowered):
            capabilities.append(_market_capability(lowered))
        if "买还是卖" in lowered:
            capabilities.append("rag.search")
            return tuple(dict.fromkeys(capabilities))
        result = [*capabilities, "rag.search"]
        strategy_requested = _strategy_lookup_requested(lowered)
        if "记忆" in lowered or _requested_strategy_key(objective) or strategy_requested:
            result.append("memory.search")
        if (
            _requested_strategy_key(objective)
            or _requested_backtest_id(objective)
            or "策略表现" in lowered
            or strategy_requested
        ):
            result.append("strategy.performance_summary")
        return tuple(dict.fromkeys(result))
    if _strategy_lookup_requested(lowered):
        if len(_requested_strategy_keys(objective)) >= 2:
            return (*capabilities, "strategy.compare")
        return (*capabilities, "strategy.performance_summary")
    if _paper_lookup_requested(lowered):
        return (*capabilities, "paper.summary")
    if _market_lookup_requested(lowered):
        return (*capabilities, _market_capability(lowered))
    return tuple(capabilities)


def _market_capability(lowered: str) -> str:
    if "强弱" in lowered or "比较" in lowered:
        return "market.relative_strength"
    if "趋势" in lowered or "1h" in lowered or "k线" in lowered:
        return "market.candles"
    if "资金费率" in lowered or "持仓量" in lowered or "oi" in lowered:
        return "market.derivatives"
    if "热度" in lowered or "风险偏好" in lowered:
        return "market.regime"
    return "market.summary"


def _steps_for_objective(objective: str) -> Sequence[PlanStepV2]:
    steps: list[PlanStepV2] = [_objective_step(objective)]
    previous = "inspect_objective"
    for capability_id in _capabilities_for_objective(objective)[1:]:
        step = PlanStepV2(
            step_id=_step_id_for_capability(capability_id),
            title=_step_title(capability_id),
            depends_on=(previous,),
            capability_id=capability_id,
            arguments=_step_arguments(capability_id, objective),
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
    allowed_capabilities = [str(item["capability_id"]) for item in allowed]
    instruction = {
        "role": "system",
        "content": (
            "Return JSON only. Extract the user's semantic intent; do not propose a plan, tool, "
            "permission or action. Return exactly {\"intent\": {\"kind\": string, "
            "\"assets\": [string]}}. For a one-symbol current-price request, use kind "
            "\"market_quote\" and copy the symbol exactly from the user message. Otherwise use "
            "a descriptive kind and an empty assets array when no explicit asset was requested. "
            "Never invent an asset, never infer a trade action, and never include text outside "
            "JSON."
        ),
    }
    user = {
        "role": "user",
        "content": json.dumps(
            {
                "objective": mission.objective,
                "constraints": list(mission.constraints),
                "allowed_read_capabilities": allowed_capabilities,
            },
            ensure_ascii=False,
        ),
    }
    return [instruction, user]


def _apply_provider_intent(
    content: str,
    *,
    mission: MissionProjection,
    fallback: PlanV2,
) -> PlanV2:
    """Use a validated model entity only inside the existing read-only envelope."""

    raw = json.loads(_json_object(content))
    if not isinstance(raw, dict):
        raise ValueError("intent response must be an object")
    intent = raw.get("intent")
    if not isinstance(intent, dict) or str(intent.get("kind", "")) != "market_quote":
        return fallback
    assets = intent.get("assets")
    if not isinstance(assets, list) or len(assets) != 1 or not isinstance(assets[0], str):
        return fallback
    inst_id = _validated_provider_market_instrument(assets[0], mission.objective)
    if inst_id is None:
        return fallback
    for step in fallback.steps:
        if step.capability_id == "market.summary":
            # The model only supplies a user-verbatim entity. This immutable plan
            # already chose the reviewed read capability, scope and dependencies.
            arguments = {**step.arguments, "inst_id": inst_id}
            return fallback.model_copy(
                update={
                    "steps": tuple(
                        item.model_copy(update={"arguments": arguments})
                        if item.step_id == step.step_id
                        else item
                        for item in fallback.steps
                    ),
                    "assumptions": (
                        *fallback.assumptions,
                        "Provider-extracted market symbol was validated against the objective.",
                    ),
                }
            )
    return fallback


def _input_schema_for(capability_id: str) -> dict[str, Any]:
    if capability_id == "runtime.objective_inspection":
        return {"objective": "string"}
    if capability_id == "market.summary":
        return {"limit": "integer 1..50"}
    if capability_id == "bitpro.live_strategy_summary":
        return {
            "exchange": "string=okx",
            "limit": "integer 1..20",
            "symbol": "optional string",
            "status": "optional running|paused",
            "sort": "optional asc|desc",
            "presentation": "inventory|performance|best|worst|ranking",
        }
    if capability_id == "strategy.draft":
        return {
            "prompt": "string 1..800",
            "symbol": "optional string instrument id",
            "timeframe": "optional string like 1H",
        }
    if capability_id == "bitpro.order_history":
        return {"limit": "integer 1..20", "symbol": "optional string"}
    if capability_id == "bitpro.meta":
        return {}
    return {"query": "string", "limit": "integer"}


def _is_terminal_without_read(lowered: str) -> bool:
    return (
        any(term in lowered for term in _DIRECT_CLARIFICATION_TERMS)
        or "不存在可验证的" in lowered
        or ("没有策略收益数据" in lowered and "调仓" in lowered)
    )


def _market_lookup_requested(lowered: str) -> bool:
    return any(term in lowered for term in _MARKET_TERMS) or bool(
        _requested_market_instruments(lowered)
    )


def _paper_lookup_requested(lowered: str) -> bool:
    return "持仓量" not in lowered and any(term in lowered for term in _PAPER_TERMS)


def _execution_intent_lookup_requested(lowered: str) -> bool:
    return (
        "testnet" in lowered
        or "测试网" in lowered
        or ("订单" in lowered and any(term in lowered for term in ("批准", "审批", "待")))
    )


def _knowledge_lookup_requested(lowered: str) -> bool:
    return any(term in lowered for term in _KNOWLEDGE_TERMS) or "记忆" in lowered


def _portfolio_lookup_requested(lowered: str) -> bool:
    return (
        any(term in lowered for term in _PORTFOLIO_TERMS)
        or "我的策略按收益" in lowered
        or "降低风险" in lowered
    )


def _requested_market_instrument(objective: str) -> str | None:
    instruments = _requested_market_instruments(objective)
    return instruments[-1] if instruments else None


def _requested_market_instruments(objective: str) -> tuple[str, ...]:
    instruments: list[str] = []

    def append(raw: str, *, allow_bare: bool = False) -> None:
        inst_id = _market_instrument_from_token(raw, allow_bare=allow_bare)
        if inst_id and inst_id not in instruments:
            instruments.append(inst_id)

    for raw in re.findall(r"[A-Z0-9][A-Z0-9_-]{1,31}", objective.upper()):
        append(raw)
    # A free-form prompt like “看下 LAB 的价格” has no quote suffix. Accept a
    # bare symbol only when adjacent to an explicit market noun; generic prose
    # such as “当前市场怎么样” remains an all-market summary.
    for match in _BARE_MARKET_SYMBOL.finditer(objective):
        append(match.group(1), allow_bare=True)
    # Chinese asset names resolve deterministically too, so a ticker question
    # keeps working when no provider is configured to name the symbol.
    for base, aliases in _MARKET_SYMBOL_ALIASES.items():
        if any(alias in objective for alias in aliases):
            append(base, allow_bare=True)
    return tuple(instruments)


def _validated_provider_market_instrument(asset: str, objective: str) -> str | None:
    """Accept a model entity only when it is a verbatim, explicit user symbol."""

    raw = asset.strip()
    if not raw or not re.fullmatch(r"[A-Za-z0-9_/-]{2,32}", raw):
        return None
    # Do not let an untrusted provider add an instrument that was absent from the
    # operator objective. A token boundary rejects a partial hallucination such
    # as extracting ETH from the unrelated word ETHEREUM.
    if not re.search(
        rf"(?<![A-Z0-9]){re.escape(raw)}(?![A-Z0-9])",
        objective,
        flags=re.IGNORECASE,
    ):
        # Chinese operators name assets in Chinese: “比特币现在多少钱” carries no
        # ASCII token for the model to copy. A closed alias table keeps the
        # anti-hallucination gate intact — only a listed alias, matched inside the
        # objective, validates the model's symbol; invented symbols still fail.
        token = re.sub(r"[-_/]", "", raw).upper()
        base = token[: -len("USDTSWAP")] if token.endswith("USDTSWAP") else (
            token[: -len("USDT")] if token.endswith("USDT") else token
        )
        aliases = _MARKET_SYMBOL_ALIASES.get(base, ())
        if not aliases or not any(alias in objective for alias in aliases):
            return None
    return _market_instrument_from_token(raw, allow_bare=True)


def _market_instrument_from_token(raw: str, *, allow_bare: bool = False) -> str | None:
    token = re.sub(r"[-_/]", "", raw).upper()
    if token.endswith("USDTSWAP"):
        base = token[: -len("USDTSWAP")]
    elif token.endswith("USDT"):
        base = token[: -len("USDT")]
    elif allow_bare or token in {"BTC", "ETH", "SOL"}:
        base = token
    else:
        return None
    if (
        len(base) < 2
        or len(base) > 20
        or not base.isalnum()
        or base in _MARKET_SYMBOL_STOPWORDS
    ):
        return None
    return f"{base}-USDT-SWAP"


def _strategy_lookup_requested(objective: str) -> bool:
    return any(
        term in objective
        for term in ("strategy", "策略", "backtest", "回测", "历史表现", "回撤", "交易次数")
    )


def _live_strategy_lookup_requested(objective: str) -> bool:
    return any(term in objective for term in _LIVE_STRATEGY_TERMS) or any(
        term in objective for term in ("实盘收益", "实盘策略", "我的策略按收益", "实盘策略清单")
    )


_STRATEGY_DRAFT_VERBS = (
    "做一个",
    "做个",
    "写一个",
    "写个",
    "生成",
    "设计一个",
    "设计个",
    "草稿",
    "回测一个",
    "回测个",
    "做什么策略",
    "适合做什么",
)


def _strategy_draft_requested(lowered: str) -> bool:
    """“做一个策略” wants a draft, not a lookup of past performance."""
    if "策略" not in lowered and "strategy" not in lowered:
        return False
    return any(term in lowered for term in _STRATEGY_DRAFT_VERBS)


def _live_order_history_requested(lowered: str) -> bool:
    return (
        "订单" in lowered
        and "实盘" in lowered
        and not _execution_intent_lookup_requested(lowered)
    )


def _bitpro_meta_requested(lowered: str) -> bool:
    if "bitpro" not in lowered:
        return False
    return any(
        term in lowered
        for term in ("支持哪些", "哪些能力", "什么能力", "能力清单", "健康", "服务状态")
    )


def _requested_strategy_key(objective: str) -> str:
    match = re.search(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", objective.casefold())
    return match.group(1) if match else ""


def _requested_backtest_id(objective: str) -> str:
    match = re.search(r"\bbacktest_id\s*=\s*([a-z0-9_-]+)\b", objective.casefold())
    if match:
        return match.group(1)
    numbered = re.search(r"(?<!\d)(\d{1,12})\s*(?:号)?\s*回测", objective)
    return numbered.group(1) if numbered else ""


def _requested_strategy_keys(objective: str) -> tuple[str, ...]:
    matches = re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", objective.casefold())
    return tuple(dict.fromkeys(matches))


def _step_id_for_capability(capability_id: str) -> str:
    return {
        "market.summary": "market_snapshot",
        "market.relative_strength": "market_relative_strength",
        "market.candles": "market_candles",
        "market.derivatives": "market_derivatives",
        "market.regime": "market_regime",
        "rag.search": "research_evidence",
        "memory.search": "memory_context",
        "strategy.performance_summary": "strategy_performance",
        "strategy.compare": "strategy_compare",
        "strategy.draft": "strategy_draft",
        "bitpro.live_strategy_summary": "live_strategy_inventory",
        "bitpro.order_history": "live_order_history",
        "bitpro.meta": "bitpro_meta",
        "paper.summary": "paper_summary",
        "portfolio.assessment": "portfolio_assessment",
        "world_model.snapshot": "world_model_snapshot",
        "monitor.summary": "monitor_summary",
        "execution.intent_summary": "intent_summary",
    }[capability_id]


def _step_title(capability_id: str) -> str:
    return f"Read verified {capability_id} data"


def _step_arguments(capability_id: str, objective: str) -> dict[str, Any]:
    lowered = objective.casefold()
    inst_ids = _requested_market_instruments(objective)
    inst_id = inst_ids[-1] if inst_ids else ""
    if "不存在的" in lowered and capability_id.startswith("market."):
        inst_id = "__MISSING__-USDT-SWAP"
    if capability_id == "market.summary":
        return {"limit": 10, **({"inst_id": inst_id} if inst_id else {})}
    if capability_id == "market.relative_strength":
        return {"inst_ids": list(inst_ids[:2]), "bar": "1H"}
    if capability_id == "market.candles":
        return {"inst_id": inst_id, "bar": "1H"}
    if capability_id == "market.derivatives":
        return {"inst_id": inst_id}
    if capability_id in {"market.regime", "world_model.snapshot"}:
        return {"limit": 10}
    if capability_id == "rag.search":
        return {"query": _knowledge_query(objective), "limit": 5}
    if capability_id == "memory.search":
        query = (
            "__unrecorded_strategy__"
            if "没有记录" in lowered
            else _requested_strategy_key(objective)
        )
        return {"query": query, "limit": 10}
    if capability_id == "strategy.performance_summary":
        strategy_key = _requested_strategy_key(objective)
        if "半导体" in objective and "ema" in lowered:
            strategy_key = "semiconductor_ema5_20"
        return {
            "strategy_key": (
                "__unrecorded_strategy__"
                if "没有记录" in lowered
                else strategy_key
            ),
            "backtest_id": _requested_backtest_id(objective),
            "limit": 3,
        }
    if capability_id == "strategy.compare":
        return {"strategy_keys": list(_requested_strategy_keys(objective)[:4]), "limit": 10}
    if capability_id == "bitpro.live_strategy_summary":
        status = "paused" if "暂停" in lowered else "running" if "运行" in lowered else ""
        sort = (
            "desc"
            if any(term in lowered for term in ("最高", "最好", "最佳", "排名"))
            else "asc"
            if any(term in lowered for term in ("最低", "最差"))
            else ""
        )
        result: dict[str, Any] = {
            "exchange": "okx",
            "limit": 20,
        }
        symbol = (
            "XRP-USDT-SWAP" if "xrp" in lowered or "不存在" in lowered else inst_id
        )
        presentation = (
            "ranking"
            if "排名" in lowered
            else "best"
            if any(term in lowered for term in ("最高", "最好", "最佳"))
            else "worst"
            if any(term in lowered for term in ("最低", "最差"))
            else "performance"
            if any(term in lowered for term in ("收益", "盈亏"))
            else "inventory"
        )
        if symbol:
            result["symbol"] = symbol
        if status:
            result["status"] = status
        if sort:
            result["sort"] = sort
        if presentation != "inventory":
            result["presentation"] = presentation
        return result
    if capability_id == "strategy.draft":
        return {
            "prompt": objective[:800],
            "symbol": inst_id or "BTC-USDT-SWAP",
            "timeframe": "1H",
        }
    if capability_id == "bitpro.order_history":
        order_args: dict[str, Any] = {"limit": 5}
        if inst_id:
            order_args["symbol"] = inst_id
        return order_args
    if capability_id == "bitpro.meta":
        return {}
    if capability_id == "paper.summary":
        focus = (
            "anomaly"
            if "异常" in lowered
            else "orders"
            if "订单" in lowered
            else "pnl"
            if "盈亏" in lowered
            else "risk"
            if "风险" in lowered or "哪个策略表现最好" in lowered
            else "summary"
        )
        return {"focus": focus, "inst_id": inst_id, "limit": 10}
    if capability_id == "portfolio.assessment":
        return {"focus": "exposure" if "暴露" in lowered else "allocation", "inst_id": inst_id}
    if capability_id == "monitor.summary":
        return {}
    return {"environment": "testnet", "limit": 10}


def _knowledge_query(objective: str) -> str:
    if "风控" in objective:
        return "风控 止损"
    if key := _requested_strategy_key(objective):
        return key
    if "火星套利" in objective:
        return "火星套利"
    return objective[:500]


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
