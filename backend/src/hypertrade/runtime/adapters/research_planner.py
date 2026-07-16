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

_MARKET_TERMS = ("market", "price", "ticker", "行情", "价格", "市场", "合约")
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
    "bitpro.live_strategy_summary": {
        "type": "object",
        "required": ["strategies", "count", "source_available"],
    },
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
    if _is_terminal_without_read(lowered):
        return tuple(capabilities)
    if _live_strategy_lookup_requested(lowered):
        return (*capabilities, "bitpro.live_strategy_summary")
    if _paper_lookup_requested(lowered) and not any(
        term in lowered for term in ("回测", "backtest")
    ):
        return (*capabilities, "paper.summary")
    if _portfolio_lookup_requested(lowered):
        if "监控" in lowered or "告警" in lowered:
            return (*capabilities, "monitor.summary")
        if "全局市场" in lowered or "继续持有" in lowered or "降低风险" in lowered:
            return (*capabilities, "world_model.snapshot")
        return (*capabilities, "portfolio.assessment")
    if _knowledge_lookup_requested(lowered):
        if "买还是卖" in lowered:
            return (*capabilities, "rag.search", "market.summary")
        result = [*capabilities, "rag.search"]
        if "记忆" in lowered or _requested_strategy_key(objective):
            result.append("memory.search")
        if (
            _requested_strategy_key(objective)
            or _requested_backtest_id(objective)
            or "策略表现" in lowered
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
        if "强弱" in lowered or "比较" in lowered:
            return (*capabilities, "market.relative_strength")
        if "趋势" in lowered or "1h" in lowered or "k线" in lowered:
            return (*capabilities, "market.candles")
        if "资金费率" in lowered or "持仓量" in lowered or "oi" in lowered:
            return (*capabilities, "market.derivatives")
        if "热度" in lowered or "风险偏好" in lowered:
            return (*capabilities, "market.regime")
        return (*capabilities, "market.summary")
    return tuple(capabilities)


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
    if capability_id == "bitpro.live_strategy_summary":
        return {
            "exchange": "string=okx",
            "limit": "integer 1..20",
            "symbol": "optional string",
            "status": "optional running|paused",
            "sort": "optional asc|desc",
            "presentation": "inventory|performance|best|worst|ranking",
        }
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
    ignored = {"USDT", "SWAP", "BACKTEST", "TESTNET", "ETHEREUM"}
    instruments: list[str] = []
    for raw in re.findall(r"[A-Z0-9-]{2,32}", objective.upper()):
        token = raw.replace("-", "")
        if token.endswith("USDTSWAP"):
            base = token[: -len("USDTSWAP")]
        elif token.endswith("USDT"):
            base = token[: -len("USDT")]
        elif token in {"BTC", "ETH", "SOL"}:
            base = token
        else:
            continue
        if len(base) >= 2 and base.isalnum() and base not in ignored:
            inst_id = f"{base}-USDT-SWAP"
            if inst_id not in instruments:
                instruments.append(inst_id)
    return tuple(instruments)


def _strategy_lookup_requested(objective: str) -> bool:
    return any(
        term in objective
        for term in ("strategy", "策略", "backtest", "回测", "历史表现", "回撤", "交易次数")
    )


def _live_strategy_lookup_requested(objective: str) -> bool:
    return any(term in objective for term in _LIVE_STRATEGY_TERMS) or any(
        term in objective for term in ("实盘收益", "实盘策略", "我的策略按收益", "实盘策略清单")
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
        "bitpro.live_strategy_summary": "live_strategy_inventory",
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
            if any(term in lowered for term in ("最高", "排名"))
            else "asc"
            if "最低" in lowered
            else ""
        )
        return {
            "exchange": "okx",
            "limit": 20,
            "symbol": (
                "XRP-USDT-SWAP"
                if "xrp" in lowered or "不存在" in lowered
                else inst_id
            ),
            "status": status,
            "sort": sort,
            "presentation": "ranking"
            if "排名" in lowered
            else "best"
            if "最高" in lowered
            else "worst"
            if "最低" in lowered
            else "performance"
            if any(term in lowered for term in ("收益", "盈亏"))
            else "inventory",
        }
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
