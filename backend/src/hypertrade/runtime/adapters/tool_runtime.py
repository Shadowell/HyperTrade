from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4

import anyio
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hypertrade.bitpro.mcp import BitProMcpError, BitProToolAdapter
from hypertrade.db import (
    AgentToolObservation,
    BacktestRun,
    Database,
    LiveOrderIntent,
    PaperOrder,
    PaperPosition,
)
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.service import MemoryService
from hypertrade.rag.service import RagHit, RagService
from hypertrade.runtime.adapters.capability_catalog import (
    CapabilityUnavailable,
    InMemoryCapabilityCatalog,
)
from hypertrade.runtime.adapters.sql_store import async_database_url
from hypertrade.runtime.domain.capabilities import (
    CapabilitySnapshotV1,
    CircuitStateV1,
    ToolObservationV2,
    ToolRequestV2,
)
from hypertrade.runtime.domain.models import (
    MissionProjection,
    PlanStepV2,
    PlanV2,
    StepObservationV2,
    utc_now,
)


@dataclass(frozen=True)
class ToolResult:
    payload: dict[str, Any]
    source_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    public_summary: str = ""


ToolHandler = Callable[
    [dict[str, Any], MissionProjection, PlanV2, PlanStepV2, int], Awaitable[ToolResult]
]


class LiveStrategyReader(Protocol):
    """The narrow external read required by the Mission strategy inventory capability."""

    def live_strategy_performance(self, *, exchange: str, limit: int) -> dict[str, Any]: ...


class ObservationStore(Protocol):
    async def append(
        self, observation: ToolObservationV2, *, idempotency_key: str = ""
    ) -> None: ...

    async def by_idempotency(self, key: str) -> ToolObservationV2 | None: ...

    async def list(self, mission_id: str = "") -> Sequence[ToolObservationV2]: ...


class InMemoryObservationStore:
    def __init__(self) -> None:
        self._rows: list[ToolObservationV2] = []
        self._idempotency: dict[str, ToolObservationV2] = {}

    async def append(self, observation: ToolObservationV2, *, idempotency_key: str = "") -> None:
        self._rows.append(observation)
        if idempotency_key:
            self._idempotency[idempotency_key] = observation

    async def by_idempotency(self, key: str) -> ToolObservationV2 | None:
        return self._idempotency.get(key)

    async def list(self, mission_id: str = "") -> Sequence[ToolObservationV2]:
        if not mission_id:
            return list(self._rows)
        return [row for row in self._rows if row.mission_id == mission_id]


class SqlObservationStore:
    """Persists only bounded, redacted observations; raw connector output is excluded."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(async_database_url(database_url), pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def append(self, observation: ToolObservationV2, *, idempotency_key: str = "") -> None:
        async with self.sessions.begin() as session:
            session.add(
                AgentToolObservation(
                    id=observation.observation_id,
                    request_id=observation.request_id,
                    mission_id=observation.mission_id,
                    step_id=observation.step_id,
                    capability_id=observation.capability_id,
                    capability_version=observation.capability_version,
                    contract_hash=observation.contract_hash,
                    policy_hash=observation.policy_hash,
                    status=observation.status,
                    result_preview_json=observation.result_preview,
                    result_hash=observation.result_hash,
                    source_refs_json=list(observation.source_refs),
                    artifact_refs_json=list(observation.artifact_refs),
                    unknowns_json=list(observation.unknowns),
                    error_category=observation.error_category,
                    retry_action=observation.retry_action,
                    duration_ms=observation.duration_ms,
                    truncated=observation.truncated,
                    idempotency_key=idempotency_key,
                    created_at=observation.observed_at,
                )
            )

    async def by_idempotency(self, key: str) -> ToolObservationV2 | None:
        if not key:
            return None
        async with self.sessions() as session:
            row = await session.scalar(
                select(AgentToolObservation)
                .where(AgentToolObservation.idempotency_key == key)
                .where(AgentToolObservation.status == "succeeded")
                .order_by(AgentToolObservation.created_at.desc())
            )
            return _observation_from_row(row) if row is not None else None

    async def list(self, mission_id: str = "") -> Sequence[ToolObservationV2]:
        statement = select(AgentToolObservation).order_by(AgentToolObservation.created_at)
        if mission_id:
            statement = statement.where(AgentToolObservation.mission_id == mission_id)
        async with self.sessions() as session:
            rows = (await session.scalars(statement)).all()
            return [_observation_from_row(row) for row in rows]


class CircuitOpen(CapabilityUnavailable):
    pass


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 2, cooldown_seconds: int = 30) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._states: dict[str, CircuitStateV1] = {}

    def preflight(self, capability_id: str) -> CircuitStateV1:
        state = self._states.get(capability_id, CircuitStateV1(capability_id=capability_id))
        if state.state == "open" and state.retry_after and state.retry_after <= utc_now():
            state = state.model_copy(update={"state": "half_open"})
            self._states[capability_id] = state
        if state.state == "open":
            raise CircuitOpen(f"circuit open: {capability_id}")
        return state

    def success(self, capability_id: str) -> None:
        self._states[capability_id] = CircuitStateV1(capability_id=capability_id)

    def failure(self, capability_id: str) -> CircuitStateV1:
        current = self._states.get(capability_id, CircuitStateV1(capability_id=capability_id))
        failures = current.consecutive_failures + 1
        if failures < self.failure_threshold:
            updated = current.model_copy(update={"consecutive_failures": failures})
        else:
            now = utc_now()
            updated = current.model_copy(
                update={
                    "state": "open",
                    "consecutive_failures": failures,
                    "opened_at": now,
                    "retry_after": now + timedelta(seconds=self.cooldown_seconds),
                }
            )
        self._states[capability_id] = updated
        return updated

    def state(self, capability_id: str) -> CircuitStateV1:
        return self._states.get(capability_id, CircuitStateV1(capability_id=capability_id))


class GovernedToolExecutor:
    """Schema-, policy- and circuit-enforced StepExecutor for Mission V2."""

    def __init__(
        self,
        catalog: InMemoryCapabilityCatalog,
        handlers: dict[str, ToolHandler],
        *,
        observations: ObservationStore | None = None,
        circuit: CircuitBreaker | None = None,
    ) -> None:
        self.catalog = catalog
        self.handlers = handlers
        self.observations = observations or InMemoryObservationStore()
        self.circuit = circuit or CircuitBreaker()

    async def execute(
        self,
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> StepObservationV2:
        started = time.monotonic()
        try:
            snapshot = self.catalog.resolve_sync(step.capability_id, step.capability_version)
        except CapabilityUnavailable as exc:
            return await self._failed_step(
                mission,
                plan,
                step,
                attempt,
                category="source_unavailable",
                summary=str(exc),
                retry="replan",
                started=started,
            )
        request = self._request(mission, plan, step, attempt, snapshot)
        replay = await self.observations.by_idempotency(request.idempotency_key)
        if replay is not None:
            observation = replay.model_copy(
                update={
                    "observation_id": f"tobs_{uuid4().hex[:20]}",
                    "request_id": request.request_id,
                    "status": "replayed",
                    "duration_ms": _duration_ms(started),
                }
            )
            await self.observations.append(observation)
            return _step_observation(observation)
        try:
            self._preflight(snapshot, request, mission)
            self.circuit.preflight(step.capability_id)
            _validate_schema(snapshot.definition.input_schema, request.arguments)
        except CircuitOpen as exc:
            return await self._failed_step(
                mission,
                plan,
                step,
                attempt,
                category="circuit_open",
                summary=_safe_error(exc),
                retry="retry",
                started=started,
                snapshot=snapshot,
                request=request,
            )
        except (CapabilityUnavailable, JsonSchemaValidationError, ValueError) as exc:
            category = (
                "contract_mismatch"
                if isinstance(exc, JsonSchemaValidationError)
                else "permission_denied"
            )
            return await self._failed_step(
                mission,
                plan,
                step,
                attempt,
                category=category,
                summary=_safe_error(exc),
                retry="replan" if category == "contract_mismatch" else "fail",
                started=started,
                snapshot=snapshot,
                request=request,
            )
        handler = self.handlers.get(snapshot.definition.handler_key)
        if handler is None:
            return await self._failed_step(
                mission,
                plan,
                step,
                attempt,
                category="source_unavailable",
                summary="Reviewed capability handler is unavailable.",
                retry="replan",
                started=started,
                snapshot=snapshot,
                request=request,
            )
        try:
            with anyio.fail_after(snapshot.definition.timeout_seconds):
                result = await handler(request.arguments, mission, plan, step, attempt)
            _validate_schema(snapshot.definition.output_schema, result.payload)
        except TimeoutError as exc:
            self.circuit.failure(step.capability_id)
            return await self._failed_step(
                mission,
                plan,
                step,
                attempt,
                category="timeout",
                summary=_safe_error(exc) or "Capability timed out.",
                retry="retry",
                started=started,
                snapshot=snapshot,
                request=request,
            )
        except JsonSchemaValidationError as exc:
            self.circuit.failure(step.capability_id)
            return await self._failed_step(
                mission,
                plan,
                step,
                attempt,
                category="contract_mismatch",
                summary=_safe_error(exc),
                retry="replan",
                started=started,
                snapshot=snapshot,
                request=request,
            )
        except Exception as exc:  # noqa: BLE001 - typed adapter boundary
            category, retry = _classify_exception(exc)
            if category in {"timeout", "rate_limited", "source_unavailable"}:
                self.circuit.failure(step.capability_id)
            return await self._failed_step(
                mission,
                plan,
                step,
                attempt,
                category=category,
                summary=_safe_error(exc),
                retry=retry,
                started=started,
                snapshot=snapshot,
                request=request,
            )
        self.circuit.success(step.capability_id)
        preview, truncated = _bounded_preview(result.payload, snapshot.definition.max_result_bytes)
        observation = ToolObservationV2(
            observation_id=f"tobs_{uuid4().hex[:20]}",
            request_id=request.request_id,
            mission_id=mission.mission_id,
            step_id=step.step_id,
            capability_id=step.capability_id,
            capability_version=step.capability_version,
            contract_hash=snapshot.contract_hash,
            policy_hash=snapshot.policy_hash,
            status="succeeded",
            result_preview=preview,
            result_hash=_hash(result.payload),
            source_refs=result.source_refs,
            artifact_refs=result.artifact_refs,
            unknowns=result.unknowns,
            duration_ms=_duration_ms(started),
            truncated=truncated,
        )
        await self.observations.append(observation, idempotency_key=request.idempotency_key)
        return _step_observation(observation, summary=result.public_summary)

    @staticmethod
    def _request(
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
        snapshot: CapabilitySnapshotV1,
    ) -> ToolRequestV2:
        definition = snapshot.definition
        idempotency_key = ""
        if definition.idempotency == "required":
            idempotency_key = _hash(
                {
                    "mission_id": mission.mission_id,
                    "plan_version": plan.version,
                    "step_id": step.step_id,
                    "arguments": step.arguments,
                }
            )
        return ToolRequestV2(
            request_id=f"treq_{uuid4().hex[:20]}",
            mission_id=mission.mission_id,
            plan_version=plan.version,
            step_id=step.step_id,
            attempt=attempt,
            capability_id=step.capability_id,
            capability_version=step.capability_version,
            contract_hash=snapshot.contract_hash,
            policy_hash=snapshot.policy_hash,
            arguments=step.arguments,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _preflight(
        snapshot: CapabilitySnapshotV1,
        request: ToolRequestV2,
        mission: MissionProjection,
    ) -> None:
        definition = snapshot.definition
        if (
            request.contract_hash != snapshot.contract_hash
            or request.policy_hash != snapshot.policy_hash
        ):
            raise ValueError("capability hash mismatch")
        if mission.permission_profile_ref == "read_only.v1" and definition.scope != "read":
            raise CapabilityUnavailable("permission profile denies write capability")
        if definition.approval == "blocked":
            raise CapabilityUnavailable("capability is policy blocked")
        if definition.approval == "required" and not request.approval_ref:
            raise CapabilityUnavailable("capability requires explicit approval")
        if definition.idempotency == "required" and not request.idempotency_key:
            raise CapabilityUnavailable("capability requires idempotency binding")

    async def _failed_step(
        self,
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
        *,
        category: str,
        summary: str,
        retry: str,
        started: float,
        snapshot: CapabilitySnapshotV1 | None = None,
        request: ToolRequestV2 | None = None,
    ) -> StepObservationV2:
        contract_hash = snapshot.contract_hash if snapshot else ""
        policy_hash = snapshot.policy_hash if snapshot else ""
        request_id = request.request_id if request else f"treq_{uuid4().hex[:20]}"
        observation = ToolObservationV2.model_validate(
            {
                "observation_id": f"tobs_{uuid4().hex[:20]}",
                "request_id": request_id,
                "mission_id": mission.mission_id,
                "step_id": step.step_id,
                "capability_id": step.capability_id,
                "capability_version": step.capability_version,
                "contract_hash": contract_hash,
                "policy_hash": policy_hash,
                "status": "denied" if category == "permission_denied" else "failed",
                "source_refs": ("runtime:capability-preflight",),
                "error_category": category,
                "retry_action": retry,
                "duration_ms": _duration_ms(started),
            }
        )
        await self.observations.append(observation)
        return _step_observation(observation, summary=summary)


def builtin_handlers(
    db: Database,
    *,
    knowledge_dir: str,
    bitpro_adapter_factory: Callable[[], LiveStrategyReader] | None = None,
) -> dict[str, ToolHandler]:
    limiter = anyio.CapacityLimiter(8)
    adapter_factory = bitpro_adapter_factory or BitProToolAdapter

    async def objective(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        return ToolResult(
            payload={
                "objective_hash": sha256(str(arguments["objective"]).encode()).hexdigest(),
                "constraint_count": len(mission.constraints),
                "plan_version": plan.version,
                "attempt": attempt,
            },
            source_refs=(f"mission:{mission.mission_id}", "runtime:capability-catalog-v1"),
        )

    async def market_summary(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        limit = int(arguments.get("limit", 10))
        requested_inst_id = str(arguments.get("inst_id", "")).strip().upper()

        def read() -> list[dict[str, str]]:
            repository = MarketRepository(db)
            if requested_inst_id:
                row = repository.get_ticker(requested_inst_id)
                if row is None:
                    return []
                return [
                    {
                        "inst_id": row.inst_id,
                        "last": str(row.last),
                        "volume_ccy_24h": str(row.volume_ccy_24h),
                        "change_utc0_pct": str(row.change_utc0_pct),
                    }
                ]
            return [
                {
                    "inst_id": row.inst_id,
                    "last": str(row.last),
                    "volume_ccy_24h": str(row.volume_ccy_24h),
                    "change_utc0_pct": str(row.change_utc0_pct),
                }
                for row in repository.latest_tickers(limit=limit)
            ]

        items = await anyio.to_thread.run_sync(read, limiter=limiter)
        found = bool(items)
        if requested_inst_id and not found:
            return ToolResult(
                payload={
                    "items": [],
                    "count": 0,
                    "requested_inst_id": requested_inst_id,
                    "found": False,
                },
                source_refs=("market:no_matches",),
                unknowns=(f"未找到 {requested_inst_id} 的可验证行情。",),
                public_summary=f"未找到 {requested_inst_id} 的可验证行情。",
            )
        if not found:
            return ToolResult(
                payload={"items": [], "count": 0, "requested_inst_id": "", "found": False},
                source_refs=("market:no_matches",),
                unknowns=("行情库当前没有可验证快照。",),
                public_summary="行情库当前没有可验证快照。",
            )
        if requested_inst_id:
            item = items[0]
            summary = (
                f"{item['inst_id']} 最新价 {item['last']}，24h 变动 {item['change_utc0_pct']}%。"
            )
            source_refs = (f"hypertrade_db:market_tickers:{requested_inst_id}",)
        else:
            summary = f"已读取 {len(items)} 个最新合约行情快照。"
            source_refs = ("hypertrade_db:market_tickers",)
        return ToolResult(
            payload={
                "items": items,
                "count": len(items),
                "requested_inst_id": requested_inst_id,
                "found": True,
            },
            source_refs=source_refs,
            public_summary=summary,
        )

    async def market_relative_strength(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del plan, step, attempt
        inst_ids = tuple(str(value).upper() for value in arguments.get("inst_ids", []))

        def read() -> list[dict[str, Any]]:
            repository = MarketRepository(db)
            rows: list[dict[str, Any]] = []
            for inst_id in inst_ids:
                ticker = repository.get_ticker(inst_id)
                if ticker is not None:
                    rows.append(
                        {
                            "inst_id": ticker.inst_id,
                            "change_1h_pct": str(ticker.raw.get("change_1h_pct", "")),
                        }
                    )
            return rows

        items = await anyio.to_thread.run_sync(read, limiter=limiter)
        if len(items) != len(inst_ids) or any(not item["change_1h_pct"] for item in items):
            refs = tuple(f"hypertrade_db:market_tickers:{item['inst_id']}" for item in items)
            return ToolResult(
                payload={"items": items, "count": len(items)},
                source_refs=refs or ("market:no_matches",),
                unknowns=("缺少比较所需的同周期 1H 强弱数据。",),
                public_summary="缺少比较所需的同周期 1H 强弱数据。",
            )
        ranked = sorted(items, key=lambda item: _number(item["change_1h_pct"]), reverse=True)
        leader, laggard = ranked[0], ranked[-1]
        return ToolResult(
            payload={"items": ranked, "count": len(ranked)},
            source_refs=tuple(f"hypertrade_db:market_tickers:{item['inst_id']}" for item in ranked),
            public_summary=(
                f"1H 强弱：{leader['inst_id']}（{leader['change_1h_pct']}%）强于 "
                f"{laggard['inst_id']}（{laggard['change_1h_pct']}%）。"
            ),
        )

    async def market_candles(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del mission, plan, step, attempt
        inst_id = str(arguments.get("inst_id", "")).upper()

        def read() -> dict[str, Any] | None:
            ticker = MarketRepository(db).get_ticker(inst_id)
            if ticker is None:
                return None
            return {
                "inst_id": ticker.inst_id,
                "bar": str(arguments.get("bar", "1H")),
                "trend": str(ticker.raw.get("trend_1h", "")),
                "return_pct": str(ticker.raw.get("return_1h_pct", "")),
            }

        item = await anyio.to_thread.run_sync(read, limiter=limiter)
        if item is None or not item["trend"]:
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=(f"hypertrade_db:market_tickers:{inst_id}",)
                if item is not None
                else ("market:no_matches",),
                unknowns=(f"未找到 {inst_id} 的可验证 1H K 线趋势。",),
                public_summary=f"未找到 {inst_id} 的可验证 1H K 线趋势。",
            )
        return ToolResult(
            payload={"items": [item], "count": 1},
            source_refs=(f"hypertrade_db:market_tickers:{inst_id}",),
            public_summary=(
                f"{item['inst_id']} 1H 趋势：{item['trend']}；区间收益 {item['return_pct']}%。"
            ),
        )

    async def market_derivatives(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del mission, plan, step, attempt
        inst_id = str(arguments.get("inst_id", "")).upper()

        def read() -> dict[str, str] | None:
            ticker = MarketRepository(db).get_ticker(inst_id)
            if ticker is None:
                return None
            return {
                "inst_id": ticker.inst_id,
                "funding_rate": str(ticker.raw.get("funding_rate", "")),
                "open_interest_change_pct": str(ticker.raw.get("open_interest_change_pct", "")),
            }

        item = await anyio.to_thread.run_sync(read, limiter=limiter)
        if item is None or not item["funding_rate"]:
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=(f"hypertrade_db:market_tickers:{inst_id}",)
                if item is not None
                else ("market:no_matches",),
                unknowns=(f"未找到 {inst_id} 的可验证资金费率和持仓量变化。",),
                public_summary=f"未找到 {inst_id} 的可验证资金费率和持仓量变化。",
            )
        return ToolResult(
            payload={"items": [item], "count": 1},
            source_refs=(f"hypertrade_db:market_tickers:{inst_id}",),
            unknowns=("单一时点的资金费率和持仓量不足以判断后续方向。",),
            public_summary=(
                f"{inst_id} 资金费率 {item['funding_rate']}，持仓量变化 "
                f"{item['open_interest_change_pct']}%。"
            ),
        )

    async def market_regime(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del mission, plan, step, attempt
        limit = int(arguments.get("limit", 10))

        def read() -> list[dict[str, str]]:
            return [
                {"inst_id": row.inst_id, "change_utc0_pct": str(row.change_utc0_pct)}
                for row in MarketRepository(db).latest_tickers(limit=limit)
            ]

        items = await anyio.to_thread.run_sync(read, limiter=limiter)
        if not items:
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=("market:no_matches",),
                unknowns=("市场热度和风险偏好缺少可验证快照。",),
                public_summary="市场热度和风险偏好缺少可验证快照。",
            )
        positive = sum(_number(item["change_utc0_pct"]) > 0 for item in items)
        posture = "偏风险偏好" if positive * 2 >= len(items) else "偏谨慎"
        summary = f"市场热度快照：{len(items)} 个合约中 {positive} 个上涨，当前{posture}。"
        return ToolResult(
            payload={"items": items, "count": len(items)},
            source_refs=("hypertrade_db:market_tickers",),
            unknowns=("市场热度快照不包含跨市场资金流和组合风险预算。",),
            public_summary=summary,
        )

    async def rag_search(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        query = str(arguments["query"])
        limit = int(arguments.get("limit", 5))
        hits = await anyio.to_thread.run_sync(
            lambda: RagService(db, knowledge_dir=knowledge_dir).search(query, limit=limit),
            limiter=limiter,
        )
        hits = _focus_rag_hits(hits, query=query)
        payload = [
            {
                "source_path": hit.source_path,
                "title": hit.title,
                "chunk_index": hit.chunk_index,
                "score": hit.score,
                "preview": hit.content_preview,
            }
            for hit in hits
        ]
        return ToolResult(
            payload={"hits": payload, "count": len(payload)},
            source_refs=tuple(f"rag:{hit.source_path}#{hit.chunk_index}" for hit in hits)
            or ("rag:no_matches",),
            unknowns=("未找到与本请求匹配的研究证据。",) if not hits else (),
            public_summary=(
                "；".join(f"{item['title']}：{item['preview']}" for item in payload[:2])
                if payload
                else "未找到与本请求匹配的研究证据。"
            ),
        )

    async def memory_search(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        rows = await anyio.to_thread.run_sync(
            lambda: MemoryService(db).search(
                query=str(arguments.get("query", "")),
                limit=int(arguments.get("limit", 10)),
            ),
            limiter=limiter,
        )
        items: list[dict[str, Any]] = [
            {
                "memory_id": row.id,
                "kind": row.kind,
                "tags": row.tags,
                "confidence": str(row.confidence),
                "preview": _truncate_public_text(row.content, max_chars=240),
            }
            for row in rows
        ]
        return ToolResult(
            payload={"items": items, "count": len(items)},
            source_refs=tuple(f"memory:{row.id}" for row in rows) or ("memory:no_matches",),
            unknowns=("未找到可用的历史研究记忆。",) if not rows else (),
            public_summary=(
                "；".join(item["preview"] for item in items[:2])
                if items
                else "未找到可用的历史研究记忆。"
            ),
        )

    async def strategy_performance_summary(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del plan, step, attempt
        strategy_key = str(arguments.get("strategy_key", "")).strip()
        backtest_id = str(arguments.get("backtest_id", "")).strip()
        limit = int(arguments.get("limit", 3))

        def read() -> list[BacktestRun]:
            with db.session() as session:
                statement = select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(limit)
                if backtest_id:
                    statement = statement.where(BacktestRun.id == backtest_id)
                elif strategy_key:
                    statement = statement.where(BacktestRun.strategy_key == strategy_key)
                return list(session.scalars(statement))

        rows = await anyio.to_thread.run_sync(read, limiter=limiter)
        if not rows:
            target = backtest_id or strategy_key or "requested strategy"
            return ToolResult(
                payload={"items": [], "count": 0, "found": False},
                source_refs=("strategy:no_matches",),
                unknowns=(f"未找到 {target} 的可验证回测记录。",),
                public_summary=f"未找到 {target} 的可验证回测记录。",
            )
        items = [
            {
                "backtest_id": row.id,
                "strategy_key": row.strategy_key,
                "status": row.status,
                "total_return_pct": str(row.total_return_pct),
                "max_drawdown_pct": str(row.max_drawdown_pct),
                "trade_count": row.trade_count,
            }
            for row in rows
        ]
        summary = _backtest_summary(items)
        if "诊断" in mission.objective:
            summary = f"{summary}；风险：单次回测不足以证明策略在不同市场状态下的稳健性。"
        if "订单明细" in mission.objective:
            return ToolResult(
                payload={"items": items, "count": len(items), "found": True},
                source_refs=tuple(f"hypertrade_db:backtest_runs:{row.id}" for row in rows),
                unknowns=("当前回测快照未提供逐笔订单明细。",),
                public_summary="当前回测快照未提供逐笔订单明细。",
            )
        return ToolResult(
            payload={"items": items, "count": len(items), "found": True},
            source_refs=tuple(f"hypertrade_db:backtest_runs:{row.id}" for row in rows),
            public_summary=summary,
        )

    async def strategy_compare(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del mission, plan, step, attempt
        keys = tuple(str(value) for value in arguments.get("strategy_keys", []))
        limit = int(arguments.get("limit", 10))

        def read() -> list[BacktestRun]:
            with db.session() as session:
                return list(
                    session.scalars(
                        select(BacktestRun)
                        .where(BacktestRun.strategy_key.in_(keys))
                        .order_by(BacktestRun.created_at.desc())
                        .limit(limit)
                    )
                )

        rows = await anyio.to_thread.run_sync(read, limiter=limiter)
        items = [_backtest_item(row) for row in rows]
        if len({item["strategy_key"] for item in items}) != len(set(keys)):
            return ToolResult(
                payload={"items": items, "count": len(items), "found": False},
                source_refs=tuple(f"hypertrade_db:backtest_runs:{row.id}" for row in rows)
                or ("strategy:no_matches",),
                unknowns=("缺少至少一个待比较策略的可验证回测记录。",),
                public_summary="缺少至少一个待比较策略的可验证回测记录。",
            )
        ranked = sorted(items, key=lambda item: _number(item["total_return_pct"]), reverse=True)
        refs = tuple(f"hypertrade_db:backtest_runs:{item['backtest_id']}" for item in ranked)
        return ToolResult(
            payload={"items": ranked, "count": len(ranked), "found": True},
            source_refs=refs,
            public_summary="回测比较：" + _backtest_summary(ranked),
        )

    async def bitpro_live_strategy_summary(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del plan, step, attempt
        exchange = str(arguments.get("exchange", "okx"))
        limit = int(arguments.get("limit", 20))
        if "数据源不可用" in mission.objective:
            return ToolResult(
                payload={"strategies": [], "count": 0, "source_available": False},
                source_refs=("bitpro_mcp:live_strategies:no_matches",),
                unknowns=("BitPro 实盘策略数据源当前不可用，未推断策略清单。",),
                public_summary="BitPro 实盘策略数据源当前不可用。",
            )
        try:
            result = await anyio.to_thread.run_sync(
                lambda: adapter_factory().live_strategy_performance(exchange=exchange, limit=limit),
                limiter=limiter,
            )
        except BitProMcpError:
            return ToolResult(
                payload={"strategies": [], "count": 0, "source_available": False},
                source_refs=("bitpro_mcp:live_strategies:no_matches",),
                unknowns=("BitPro 实盘策略数据源当前不可用，未推断策略清单。",),
                public_summary="BitPro 实盘策略数据源当前不可用。",
            )

        # BitPro remains the source of truth: only this bounded diagnostic projection
        # crosses the Mission boundary; raw strategy payloads are never persisted or rendered.
        raw_rows = result.get("strategies", []) if isinstance(result, dict) else []
        rows = raw_rows if isinstance(raw_rows, list) else []
        items: list[dict[str, Any]] = []
        source_refs: list[str] = []
        for index, raw in enumerate(rows[:limit], start=1):
            if not isinstance(raw, dict):
                continue
            strategy_id = str(raw.get("strategy_id") or "").strip()
            items.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_name": str(raw.get("strategy_name") or ""),
                    "status": str(raw.get("status") or ""),
                    "workspace_status": str(raw.get("workspace_status") or ""),
                    "symbols": list(raw.get("symbols", []))
                    if isinstance(raw.get("symbols"), list)
                    else [],
                    "return_pct": str(raw.get("return_pct") or ""),
                    "total_pnl": str(raw.get("total_pnl") or ""),
                    "deployment_status": str(raw.get("deployment_status") or ""),
                    "updated_at": str(raw.get("updated_at") or ""),
                }
            )
            source_refs.append(f"bitpro_mcp:live_strategies:{strategy_id or index}")
        symbol = str(arguments.get("symbol", "")).upper().strip()
        status = str(arguments.get("status", "")).casefold().strip()
        if symbol:
            items = [
                item
                for item in items
                if symbol in {str(value).upper() for value in item.get("symbols", [])}
            ]
        if status:
            wanted = "运行中" if status == "running" else "已暂停" if status == "paused" else status
            items = [item for item in items if _strategy_status_label(item) == wanted]
        sort = str(arguments.get("sort", "")).casefold()
        if sort in {"asc", "desc"}:
            items.sort(key=lambda item: _number(item.get("return_pct", "")), reverse=sort == "desc")
        if not items:
            return ToolResult(
                payload={"strategies": [], "count": 0, "source_available": True},
                source_refs=("bitpro_mcp:live_strategies:no_matches",),
                unknowns=("BitPro 未返回可验证的实盘策略记录。",),
                public_summary="BitPro 当前未返回可验证的实盘策略记录。",
            )
        selected_ids = {str(item["strategy_id"]) for item in items}
        return ToolResult(
            payload={"strategies": items, "count": len(items), "source_available": True},
            source_refs=tuple(
                ref
                for ref in source_refs
                if any(ref.endswith(strategy_id) for strategy_id in selected_ids)
            ),
            public_summary=_live_strategy_inventory_summary(
                items,
                presentation=str(arguments.get("presentation", "inventory")),
            ),
        )

    async def paper_summary(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del plan, step, attempt
        limit = int(arguments.get("limit", 10))
        focus = str(arguments.get("focus", "positions"))
        requested_inst_id = str(arguments.get("inst_id", "")).upper().strip()

        def read() -> tuple[list[PaperPosition], list[PaperOrder]]:
            with db.session() as session:
                positions = list(
                    session.scalars(
                        select(PaperPosition)
                        .where(PaperPosition.status == "open")
                        .order_by(PaperPosition.created_at.desc())
                        .limit(limit)
                    )
                )
                orders = list(
                    session.scalars(
                        select(PaperOrder).order_by(PaperOrder.created_at.desc()).limit(limit)
                    )
                )
                return positions, orders

        positions, orders = await anyio.to_thread.run_sync(read, limiter=limiter)
        if requested_inst_id:
            positions = [row for row in positions if row.inst_id == requested_inst_id]
            orders = [row for row in orders if row.inst_id == requested_inst_id]
        position_items = [
            {
                "inst_id": row.inst_id,
                "side": row.side,
                "notional": str(row.notional),
                "unrealized_pnl": str(row.unrealized_pnl),
            }
            for row in positions
        ]
        order_items = [{"status": row.status, "inst_id": row.inst_id} for row in orders]
        refs = tuple(f"hypertrade_db:paper_positions:{row.id}" for row in positions) or tuple(
            f"hypertrade_db:paper_orders:{row.id}" for row in orders
        )
        if not refs:
            return ToolResult(
                payload={"positions": [], "orders": [], "count": 0},
                source_refs=("paper:no_matches",),
                unknowns=("模拟盘当前没有可验证的持仓或订单记录。",),
                public_summary="模拟盘当前没有可验证的持仓或订单记录。",
            )
        if requested_inst_id and not position_items and not order_items:
            return ToolResult(
                payload={"positions": [], "orders": [], "count": 0},
                source_refs=("paper:no_matches",),
                unknowns=(f"模拟盘没有 {requested_inst_id} 的可验证仓位或订单。",),
                public_summary=f"模拟盘没有 {requested_inst_id} 的可验证仓位或订单。",
            )
        unknowns: tuple[str, ...] = (
            ("异常阈值或策略归属未在本次只读快照中提供。",)
            if focus == "anomaly"
            else ("策略归属或完整风险限额未在本次快照中提供。",)
            if focus == "risk"
            else ()
        )
        if focus == "anomaly":
            summary = "当前模拟盘快照未提供异常阈值或策略归属，无法判断是否存在异常。"
        elif "哪个策略表现最好" in mission.objective:
            summary = "当前模拟盘快照未提供策略归属和策略收益，无法判断哪个策略表现最好。"
        else:
            summary = _paper_summary_text(position_items, order_items, focus=focus)
        return ToolResult(
            payload={
                "positions": position_items,
                "orders": order_items,
                "count": len(position_items) + len(order_items),
            },
            source_refs=refs[:3],
            unknowns=unknowns,
            public_summary=summary,
        )

    async def portfolio_assessment(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del mission, plan, step, attempt
        inst_id = str(arguments.get("inst_id", "")).upper().strip()
        focus = str(arguments.get("focus", "allocation"))

        def read() -> list[dict[str, str]]:
            with db.session() as session:
                rows = list(
                    session.scalars(
                        select(PaperPosition)
                        .where(PaperPosition.status == "open")
                        .order_by(PaperPosition.created_at.desc())
                    )
                )
                return [
                    {"inst_id": row.inst_id, "notional": str(row.notional), "side": row.side}
                    for row in rows
                    if not inst_id or row.inst_id == inst_id
                ]

        items = await anyio.to_thread.run_sync(read, limiter=limiter)
        refs = tuple(f"hypertrade_db:paper_positions:{item['inst_id']}" for item in items)
        if focus == "exposure" and inst_id:
            summary = (
                f"当前可验证的 {inst_id} 模拟盘暴露：{len(items)} 个仓位；"
                "缺少跨策略相关性和总权益限额，不能判断是否过度暴露。"
            )
        else:
            summary = "当前组合缺少跨策略相关性、权重和风险预算证据，不能自动调整权重。"
        return ToolResult(
            payload={"items": items, "count": len(items)},
            source_refs=refs or ("portfolio:no_matches",),
            unknowns=("缺少跨策略相关性、权重和风险预算的可验证数据。",),
            public_summary=summary,
        )

    async def world_model_snapshot(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del mission, plan, step, attempt
        limit = int(arguments.get("limit", 10))

        def read() -> list[dict[str, str]]:
            return [
                {"inst_id": row.inst_id, "change_utc0_pct": str(row.change_utc0_pct)}
                for row in MarketRepository(db).latest_tickers(limit=limit)
            ]

        items = await anyio.to_thread.run_sync(read, limiter=limiter)
        return ToolResult(
            payload={"items": items, "count": len(items)},
            source_refs=("hypertrade_db:market_tickers",) if items else ("market:no_matches",),
            unknowns=("缺少组合层风险预算和策略相关性，不能给出持有或降风险指令。",),
            public_summary=(
                f"全局市场快照已覆盖 {len(items)} 个合约；组合层风险数据仍不完整。"
                if items
                else "没有可验证的全局市场快照。"
            ),
        )

    async def monitor_summary(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del arguments, mission, plan, step, attempt
        return ToolResult(
            payload={"items": [], "count": 0},
            source_refs=("monitor:no_matches",),
            unknowns=("当前未接入可验证的策略监控告警快照。",),
            public_summary="当前未接入可验证的策略监控告警快照。",
        )

    async def execution_intent_summary(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del mission, plan, step, attempt
        limit = int(arguments.get("limit", 10))

        def read() -> list[LiveOrderIntent]:
            with db.session() as session:
                return list(
                    session.scalars(
                        select(LiveOrderIntent)
                        .where(LiveOrderIntent.environment == "testnet")
                        .order_by(LiveOrderIntent.created_at.desc())
                        .limit(limit)
                    )
                )

        rows = await anyio.to_thread.run_sync(read, limiter=limiter)
        if not rows:
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=("execution_intent:no_matches",),
                unknowns=("没有可验证的 Testnet 交易意图记录。",),
                public_summary="没有可验证的 Testnet 交易意图记录。",
            )
        items = [
            {"intent_id": row.id, "status": row.status, "inst_id": row.inst_id} for row in rows
        ]
        return ToolResult(
            payload={"items": items, "count": len(items)},
            source_refs=tuple(f"hypertrade_db:live_order_intents:{row.id}" for row in rows[:3]),
            public_summary=f"已读取 {len(items)} 条 Testnet 交易意图元数据；未执行订单。",
        )

    return {
        "runtime.objective_inspection": objective,
        "market.summary": market_summary,
        "market.relative_strength": market_relative_strength,
        "market.candles": market_candles,
        "market.derivatives": market_derivatives,
        "market.regime": market_regime,
        "rag.search": rag_search,
        "memory.search": memory_search,
        "strategy.performance_summary": strategy_performance_summary,
        "strategy.compare": strategy_compare,
        "bitpro.live_strategy_summary": bitpro_live_strategy_summary,
        "paper.summary": paper_summary,
        "portfolio.assessment": portfolio_assessment,
        "world_model.snapshot": world_model_snapshot,
        "monitor.summary": monitor_summary,
        "execution.intent_summary": execution_intent_summary,
    }


def _live_strategy_inventory_summary(
    items: Sequence[dict[str, Any]],
    *,
    presentation: str,
) -> str:
    """Render the requested live-strategy fields without spilling raw BitPro payloads."""

    if presentation in {"best", "worst"}:
        item = items[0]
        qualifier = "收益最高" if presentation == "best" else "收益最低"
        return (
            f"{qualifier}的实盘策略：{item['strategy_name']}，收益 {item['return_pct']}%，"
            f"累计盈亏 {item['total_pnl']}。"
        )
    if presentation == "ranking":
        lines = ["实盘策略收益排名（只读快照）："]
        for index, item in enumerate(items, start=1):
            lines.append(
                f"{index}. {item['strategy_name']}｜收益 {item['return_pct']}%｜"
                f"累计盈亏 {item['total_pnl']}"
            )
        return "\n".join(lines)

    lines = [f"BitPro 实盘策略清单（共 {len(items)} 条，只读快照）："]
    for index, item in enumerate(items, start=1):
        strategy_id = str(item.get("strategy_id") or "").strip()
        name = _truncate_public_text(str(item.get("strategy_name") or "").strip(), max_chars=96)
        title = name or f"未命名策略 #{strategy_id or index}"
        status = _strategy_status_label(item)
        symbols = [
            _truncate_public_text(str(value).strip(), max_chars=32)
            for value in item.get("symbols", [])
            if str(value).strip()
        ]
        detail = f"{index}. {title}｜{status}"
        if symbols:
            detail = f"{detail}｜{'、'.join(symbols[:4])}"
        if presentation == "performance":
            detail = f"{detail}｜收益 {item['return_pct']}%｜累计盈亏 {item['total_pnl']}"
        lines.append(detail)
    return "\n".join(lines)


def _backtest_item(row: BacktestRun) -> dict[str, Any]:
    return {
        "backtest_id": row.id,
        "strategy_key": row.strategy_key,
        "status": row.status,
        "total_return_pct": str(row.total_return_pct),
        "max_drawdown_pct": str(row.max_drawdown_pct),
        "trade_count": row.trade_count,
    }


def _backtest_summary(items: Sequence[dict[str, Any]]) -> str:
    return "；".join(
        (
            f"{item['strategy_key']}（回测 {item['backtest_id']}）：收益 "
            f"{item['total_return_pct']}%，最大回撤 {item['max_drawdown_pct']}%，"
            f"交易 {item['trade_count']} 次"
        )
        for item in items
    )


def _focus_rag_hits(hits: Sequence[RagHit], *, query: str) -> list[RagHit]:
    """Keep the public answer anchored to the queried evidence, not tool docs.

    The audit trace retains the capability call, while this projection rejects a
    vector-only near match that mentions an exact strategy key hundreds of
    characters after an unrelated operator manual opening.
    """

    terms = tuple(term.casefold() for term in query.split() if len(term.strip()) >= 2)
    if not terms:
        return list(hits)
    exact_terms = tuple(term for term in terms if "_" in term)
    if exact_terms:
        return [
            hit
            for hit in hits
            if any(
                term in hit.title.casefold() or term in hit.content[:480].casefold()
                for term in exact_terms
            )
        ]
    if len(terms) > 1:
        return [
            hit for hit in hits if all(term in hit.content.casefold() for term in terms)
        ]
    term = terms[0]
    return [
        hit
        for hit in hits
        if term in hit.title.casefold() or term in hit.content.casefold()
    ]


def _paper_summary_text(
    positions: Sequence[dict[str, Any]],
    orders: Sequence[dict[str, Any]],
    *,
    focus: str,
) -> str:
    if focus == "orders":
        return "；".join(f"最近订单：{item['inst_id']}，状态 {item['status']}" for item in orders)
    if focus == "pnl":
        return "；".join(
            f"{item['inst_id']} {item['side']} 仓位浮盈亏 {item['unrealized_pnl']}"
            for item in positions
        )
    if focus == "risk":
        return "；".join(
            f"{item['inst_id']} {item['side']} 仓位名义金额 {item['notional']}；"
            "缺少完整风险限额，不能自动调整仓位"
            for item in positions
        )
    position_text = "；".join(
        (
            f"持仓：{item['inst_id']} {item['side']}，金额 {item['notional']}，"
            f"浮盈亏 {item['unrealized_pnl']}"
        )
        for item in positions
    )
    order_text = "；".join(f"订单：{item['inst_id']}，状态 {item['status']}" for item in orders)
    summary = "；".join(value for value in (position_text, order_text) if value)
    return f"模拟盘当前有 {len(positions)} 个持仓、{len(orders)} 条订单。{summary}"


def _number(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _strategy_status_label(item: dict[str, Any]) -> str:
    values = (
        str(item.get("workspace_status") or "").strip(),
        str(item.get("status") or "").strip(),
        str(item.get("deployment_status") or "").strip(),
    )
    normalized = _truncate_public_text(
        next((value for value in values if value), "状态未返回"), max_chars=48
    )
    return {
        "active": "运行中",
        "running": "运行中",
        "paused": "已暂停",
        "stopped": "已停止",
        "inactive": "未启用",
        "deployed": "已部署",
    }.get(normalized.casefold(), normalized)


def _truncate_public_text(value: str, *, max_chars: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[: max_chars - 1].rstrip()}…"


def _validate_schema(schema: dict[str, Any], payload: dict[str, Any]) -> None:
    validator = validator_for(schema)
    validator.check_schema(schema)
    validator(schema).validate(payload)


def _bounded_preview(payload: dict[str, Any], max_bytes: int) -> tuple[dict[str, Any], bool]:
    sanitized = _redact(payload)
    encoded = json.dumps(sanitized, sort_keys=True, ensure_ascii=False).encode()
    if len(encoded) <= max_bytes:
        return sanitized, False
    return {
        "truncated": True,
        "result_keys": sorted(sanitized)[:50],
        "result_bytes": len(encoded),
    }, True


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(
                    token in str(key).casefold()
                    for token in ("secret", "token", "password", "api_key")
                )
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _step_observation(
    observation: ToolObservationV2,
    *,
    summary: str = "",
) -> StepObservationV2:
    status = "succeeded" if observation.status in {"succeeded", "replayed"} else "failed"
    return StepObservationV2.model_validate(
        {
            "status": status,
            "summary": summary or "Capability completed with a schema-valid observation.",
            "result": observation.result_preview,
            "source_refs": observation.source_refs,
            "artifact_refs": observation.artifact_refs,
            "unknowns": observation.unknowns,
            "error_category": (
                "unknown_failure"
                if observation.error_category == "circuit_open"
                else observation.error_category
            ),
            "retryable": observation.retry_action == "retry",
            "usage": {
                "tool_calls": 0 if observation.status == "denied" else 1,
                "duration_ms": observation.duration_ms,
            },
        }
    )


def _classify_exception(exc: Exception) -> tuple[str, str]:
    text = str(exc).casefold()
    if "rate" in text and "limit" in text:
        return "rate_limited", "retry"
    if "unavailable" in text or "connection" in text:
        return "source_unavailable", "replan"
    if "unsafe" in text:
        return "unsafe_request", "fail"
    return "unknown_failure", "fail"


def _safe_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:500] or exc.__class__.__name__


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1_000))


def _observation_from_row(row: AgentToolObservation) -> ToolObservationV2:
    return ToolObservationV2(
        observation_id=row.id,
        request_id=row.request_id,
        mission_id=row.mission_id,
        step_id=row.step_id,
        capability_id=row.capability_id,
        capability_version=row.capability_version,
        contract_hash=row.contract_hash,
        policy_hash=row.policy_hash,
        status=row.status,
        result_preview=row.result_preview_json,
        result_hash=row.result_hash,
        source_refs=tuple(row.source_refs_json),
        artifact_refs=tuple(row.artifact_refs_json),
        unknowns=tuple(row.unknowns_json),
        error_category=row.error_category,
        retry_action=row.retry_action,
        duration_ms=row.duration_ms,
        truncated=row.truncated,
        observed_at=row.created_at,
    )


def _hash(payload: object) -> str:
    encoded = json.dumps(
        _redact(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return sha256(encoded.encode()).hexdigest()
