from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from math import isfinite
from typing import Any, Protocol, cast
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


def _fmt_num(value: Any) -> str:
    """Render a stored numeric for an operator-facing summary.

    Numeric columns arrive as fixed-precision Decimals ("77170.100000000000");
    reading that scale aloud is noise. normalize() strips trailing zeros and
    format(..., "f") keeps small magnitudes out of scientific notation.
    """
    from decimal import Decimal, InvalidOperation

    try:
        return format(Decimal(str(value)).normalize(), "f")
    except (InvalidOperation, ValueError):
        return str(value)


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
        from hypertrade.runtime.adapters.capability_catalog import CatalogCapabilityPolicy

        definition = snapshot.definition
        if (
            request.contract_hash != snapshot.contract_hash
            or request.policy_hash != snapshot.policy_hash
        ):
            raise ValueError("capability hash mismatch")
        allowed_scopes = CatalogCapabilityPolicy._PROFILE_ALLOWED_SCOPES.get(
            mission.permission_profile_ref, frozenset({"read"})
        )
        if definition.scope not in allowed_scopes:
            raise CapabilityUnavailable(
                f"permission profile {mission.permission_profile_ref} denies "
                f"{definition.scope} capability"
            )
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
                f"{item['inst_id']} 最新价 {_fmt_num(item['last'])}，"
                f"24h 变动 {_fmt_num(item['change_utc0_pct'])}%。"
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
            adapter = BitProToolAdapter()
            rows: list[dict[str, Any]] = []
            # 1h strength is computed from BitPro klines on demand; the ticker
            # snapshot carries no hourly change. Bounded to five symbols so a
            # comparison stays one bounded read per leg.
            for inst_id in inst_ids[:5]:
                change = ""
                try:
                    payload = adapter.market_klines(symbol=inst_id, timeframe="1h", limit=2)
                    candles = payload.get("candles") or []
                    if len(candles) >= 2:
                        prev = float(candles[0]["close"])
                        last = float(candles[-1]["close"])
                        if prev:
                            change = f"{(last - prev) / prev * 100.0:.2f}"
                except Exception:
                    change = ""
                if not change:
                    ticker = repository.get_ticker(inst_id)
                    stored = str((ticker.raw or {}).get("change_1h_pct", "")) if ticker else ""
                    change = stored
                if change:
                    rows.append({"inst_id": inst_id, "change_1h_pct": change})
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
                f"1H 强弱：{leader['inst_id']}（{_fmt_num(leader['change_1h_pct'])}%）强于 "
                f"{laggard['inst_id']}（{_fmt_num(laggard['change_1h_pct'])}%）。"
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
        bar = str(arguments.get("bar", "1H"))

        def read() -> dict[str, str]:
            # The local store keeps ticker snapshots only — candle-derived facts are
            # computed on demand from BitPro-owned klines, which own market data.
            adapter = BitProToolAdapter()
            payload = adapter.market_klines(symbol=inst_id, timeframe="1h", limit=25)
            candles = payload.get("candles") or []
            if len(candles) < 3:
                raise ValueError(f"BitPro returned only {len(candles)} klines")
            closes = [float(candle["close"]) for candle in candles]
            base = closes[0]
            change = (closes[-1] - base) / base * 100.0 if base else 0.0
            if closes[-1] > closes[-2] > closes[-3]:
                trend = "上行"
            elif closes[-1] < closes[-2] < closes[-3]:
                trend = "下行"
            else:
                trend = "震荡"
            return {
                "inst_id": inst_id,
                "bar": bar,
                "trend": trend,
                "return_pct": f"{change:.2f}",
                "bars": str(len(closes)),
            }

        detail = ""
        try:
            item: dict[str, str] | None = await anyio.to_thread.run_sync(
                read, limiter=limiter
            )
        except Exception as exc:
            item = None
            detail = f"{type(exc).__name__}: {exc}"[:140]
        if item is None:
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=(f"bitpro_mcp:market_klines:{inst_id}",),
                unknowns=(f"未找到 {inst_id} 的可验证 1H K 线趋势。",),
                public_summary=(
                    f"未找到 {inst_id} 的可验证 1H K 线趋势。"
                    + (f"（{detail}）" if detail else "")
                ),
            )
        return ToolResult(
            payload={"items": [item], "count": 1},
            source_refs=(f"bitpro_mcp:market_klines:{inst_id}",),
            public_summary=(
                f"{item['inst_id']} 1H 趋势：{item['trend']}；"
                f"区间收益 {_fmt_num(item['return_pct'])}%。"
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

        def read() -> dict[str, str]:
            # Funding rate and open interest are OKX public endpoints, read on
            # demand — the ticker snapshot never carried them. OI arrives as an
            # absolute size; a *change* percentage needs history we do not keep,
            # so that stays an explicit unknown instead of an invented number.
            import asyncio

            from hypertrade.config import get_settings
            from hypertrade.market.client import OkxRestClient

            async def fetch() -> dict[str, str]:
                client = OkxRestClient(get_settings())
                funding = await client.fetch_funding_rate(inst_id=inst_id)
                oi = await client.fetch_open_interest(inst_id=inst_id)
                # OKX returns camelCase fields (fundingRate / oi / oiCcy).
                return {
                    "funding_rate": str(
                        funding.get("fundingRate") or funding.get("funding_rate") or ""
                    ),
                    "open_interest": str(oi.get("oi", "") or oi.get("open_interest", "")),
                    "open_interest_ccy": str(oi.get("oiCcy", "") or ""),
                }

            return asyncio.run(fetch())

        try:
            item: dict[str, str] | None = await anyio.to_thread.run_sync(
                read, limiter=limiter
            )
        except Exception:
            item = None
        if item is None or not item.get("funding_rate"):
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=(f"okx_rest:funding_rate:{inst_id}",),
                unknowns=(f"未找到 {inst_id} 的可验证资金费率和持仓量。",),
                public_summary=f"未找到 {inst_id} 的可验证资金费率和持仓量。",
            )
        raw_oi = item.get("open_interest") or ""
        try:
            # OKX ships OI as a JSON float; contracts count in whole units.
            oi_text = f"，当前持仓量 {round(float(raw_oi)):,} 张" if raw_oi else ""
        except ValueError:
            oi_text = f"，当前持仓量 {raw_oi}" if raw_oi else ""
        return ToolResult(
            payload={"items": [item], "count": 1},
            source_refs=(f"okx_rest:funding_rate:{inst_id}",),
            unknowns=(
                "单一时点的资金费率和持仓量不足以判断后续方向；持仓量变化率缺少历史窗口。",
            ),
            public_summary=(
                f"{inst_id} 资金费率 {_fmt_num(item['funding_rate'])}{oi_text}。"
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
        presentation = str(arguments.get("presentation", "inventory"))
        if presentation in {"best", "worst", "ranking", "performance"} and any(
            _number_or_none(item.get("return_pct")) is None for item in items
        ):
            # A strategy inventory is not a performance ranking. Treat absent
            # return data as a data gap so the public answer never guesses a
            # winner from source order or turns a blank return into zero.
            return ToolResult(
                payload={"strategies": [], "count": 0, "source_available": True},
                source_refs=("bitpro_mcp:live_strategies:no_matches",),
                unknowns=(
                    f"BitPro 返回了 {len(items)} 条实盘策略记录，但未提供可比较的逐策略收益率；"
                    "无法确定表现最佳或最差的策略。",
                ),
                public_summary="BitPro 未返回可比较的实盘收益数据，无法完成策略排名。",
            )
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
                presentation=presentation,
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

    async def strategy_draft(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del plan, step, attempt
        prompt = str(arguments.get("prompt", "")).strip() or str(mission.objective)
        symbol = str(arguments.get("symbol", "")).upper().strip() or "BTC-USDT-SWAP"
        timeframe = str(arguments.get("timeframe", "1H"))

        def read() -> dict[str, Any]:
            # BitPro owns strategy generation; HyperTrade only frames the request
            # and relays the draft. No create, no backtest job, no paper action.
            return BitProToolAdapter().strategy_generate(
                prompt=prompt[:800], symbol=symbol, timeframe=timeframe
            )

        try:
            payload = await anyio.to_thread.run_sync(read, limiter=limiter)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"[:140]
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=(f"bitpro_mcp:strategy_generate:{symbol}",),
                unknowns=("BitPro 策略生成暂不可用。",),
                public_summary=f"BitPro 策略生成暂不可用（{detail}）。",
            )
        strategy = payload.get("strategy")
        if not isinstance(strategy, dict) or not strategy:
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=(f"bitpro_mcp:strategy_generate:{symbol}",),
                unknowns=("BitPro 未返回可用的策略草稿。",),
                public_summary="BitPro 未返回可用的策略草稿，请调整描述后重试。",
            )
        name = str(strategy.get("name") or strategy.get("strategy_name") or "draft")
        description = str(
            strategy.get("description") or strategy.get("logic") or ""
        )[:220]
        summary = f"已生成 {symbol} {timeframe} 策略草稿「{name}」。"
        if description:
            summary += f"逻辑要点：{description}"
        summary += "；草稿未入库、未回测，创建与回测需要操作员走受治理流程。"
        return ToolResult(
            payload={"items": [strategy], "count": 1},
            source_refs=(f"bitpro_mcp:strategy_generate:{symbol}",),
            unknowns=("草稿未经过回测验证，不构成收益承诺。",),
            public_summary=summary,
        )

    async def bitpro_order_history(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del mission, plan, step, attempt
        limit = max(1, min(int(arguments.get("limit", 5)), 20))
        symbol = str(arguments.get("symbol", "")).upper().strip() or None

        def read() -> dict[str, Any]:
            return BitProToolAdapter().live_order_history(
                exchange="okx", symbol=symbol, limit=limit
            )

        try:
            payload = await anyio.to_thread.run_sync(read, limiter=limiter)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"[:140]
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=("bitpro_mcp:trading_order_history",),
                unknowns=("BitPro 实盘订单历史暂不可用。",),
                public_summary=f"BitPro 实盘订单历史暂不可用（{detail}）。",
            )
        orders = payload.get("orders") or []
        if not orders:
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=("bitpro_mcp:trading_order_history",),
                unknowns=("查询窗口内没有实盘订单记录。",),
                public_summary="查询窗口内没有实盘订单记录。",
            )
        latest = orders[0]
        order_id = latest.get("order_id") or latest.get("id") or ""
        parts = [str(part) for part in (
            order_id,
            latest.get("symbol") or latest.get("inst_id"),
            latest.get("side"),
            latest.get("status"),
        ) if part]
        summary = f"最近一笔实盘订单：{' '.join(str(p) for p in parts)}。"
        if len(orders) > 1:
            summary += f"（共读取 {len(orders)} 条，按时间倒序）"
        return ToolResult(
            payload={"items": list(orders[:limit]), "count": len(orders)},
            source_refs=("bitpro_mcp:trading_order_history",),
            unknowns=("成交明细与手续费归属以 BitPro 对账为准。",),
            public_summary=summary,
        )

    async def bitpro_meta(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        del mission, plan, step, attempt

        def read() -> dict[str, Any]:
            adapter = BitProToolAdapter()
            capabilities = adapter.capabilities()
            health = adapter.health()
            return {"capabilities": capabilities, "health": health}

        try:
            payload = await anyio.to_thread.run_sync(read, limiter=limiter)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"[:140]
            return ToolResult(
                payload={"items": [], "count": 0},
                source_refs=("bitpro_mcp:capabilities",),
                unknowns=("BitPro 能力/健康预检暂不可用。",),
                public_summary=f"BitPro 能力/健康预检暂不可用（{detail}）。",
            )
        capabilities = payload.get("capabilities") or {}
        health = (payload.get("health") or {}).get("health") or {}
        version = str(capabilities.get("contract_version", ""))
        status = str(health.get("status", ""))
        # The capabilities payload is contract/transport/auth metadata; it does
        # not enumerate tools, so the summary only claims what it read.
        return ToolResult(
            payload={
                "items": [{
                    "contract_version": version,
                    "health_status": status,
                }],
                "count": 1,
            },
            source_refs=("bitpro_mcp:capabilities",),
            unknowns=("工具清单细节以 BitPro 能力文档为准。",),
            public_summary=(
                f"BitPro 契约 {version or '未知'}，健康状态 {status or '未知'}。"
            ),
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

    # ------------------------------------------------------------------
    # Authored-strategy capabilities (research.v1 profile).
    # The workspace is per-mission state; bootstrap contract files make
    # agent-authored BaseStrategy code testable under sandbox pytest.
    # ------------------------------------------------------------------
    workspaces: dict[str, Any] = {}

    def _workspace_for(mission: MissionProjection) -> Any:
        from hypertrade.agent.workspace import AgentWorkspace

        workspace = workspaces.get(mission.mission_id)
        if workspace is None:
            workspace = AgentWorkspace(run_id=mission.mission_id)
            workspaces[mission.mission_id] = workspace
        return workspace

    async def workspace_write_file(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        workspace = _workspace_for(mission)
        result = await anyio.to_thread.run_sync(
            lambda: workspace.write_file(
                path=str(arguments["path"]), content=str(arguments["content"])
            ),
            limiter=limiter,
        )
        if result.get("status") != "ok":
            raise ValueError(str((result.get("error") or {}).get("message", "write rejected")))
        return ToolResult(
            payload={
                "status": "ok",
                "path": result["path"],
                "workspace_files": result["workspace_files"],
            },
            source_refs=(f"mission:{mission.mission_id}", "sandbox:workspace"),
            public_summary=(
                f"已写入 {result['path']}（工作区共 {result['workspace_files']} 个文件）。"
            ),
        )

    async def workspace_run(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        workspace = _workspace_for(mission)
        raw_args = arguments.get("args")
        result = await anyio.to_thread.run_sync(
            lambda: workspace.run(
                command=str(arguments["command"]),
                args=[str(item) for item in raw_args] if isinstance(raw_args, list) else None,
            ),
            limiter=limiter,
        )
        if result.get("status") != "ok":
            raise ValueError(str((result.get("error") or {}).get("message", "run rejected")))
        commands = result.get("commands", [])
        first = commands[0] if isinstance(commands, list) and commands else {}
        failed = result.get("sandbox_status") != "validated"
        return ToolResult(
            payload={
                "sandbox_status": result.get("sandbox_status"),
                "commands": commands,
                "sandbox_run_id": result.get("sandbox_run_id", ""),
            },
            source_refs=(
                f"mission:{mission.mission_id}",
                f"sandbox:{result.get('sandbox_run_id', '')}",
            ),
            unknowns=("沙箱命令失败，请阅读 output_preview 修复后重跑。",) if failed else (),
            public_summary=(
                f"沙箱 {arguments['command']} 结果: {result.get('sandbox_status')}；"
                f"{str(first.get('output_preview', ''))[:300]}"
            ),
        )

    async def research_validate_strategy_code(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        import ast as ast_module
        from hashlib import sha256

        from hypertrade.research.codegen import static_code_rejections

        workspace = _workspace_for(mission)
        path = str(arguments["path"])
        read_result = await anyio.to_thread.run_sync(
            lambda: workspace.read_file(path), limiter=limiter
        )
        if read_result.get("status") != "ok":
            raise ValueError(str((read_result.get("error") or {}).get("message", "file missing")))
        code = str(read_result.get("content", ""))
        try:
            ast_module.parse(code, filename=path)
        except SyntaxError as exc:
            rejections = [f"invalid_python_syntax:{exc.lineno}"]
        else:
            rejections = static_code_rejections(code)
        passed = not rejections
        return ToolResult(
            payload={
                "passed": passed,
                "rejections": rejections,
                "content_hash": sha256(code.encode("utf-8")).hexdigest()[:16],
                "next_steps": (
                    "bitpro.strategy_create with this script_content, then "
                    "bitpro.backtest_start"
                    if passed
                    else "fix the rejected constructs and re-run this gate"
                ),
            },
            source_refs=(f"mission:{mission.mission_id}", "research:static-code-gate-v1"),
            unknowns=() if passed else ("静态门拒绝，见 rejections。",),
            public_summary=(
                f"静态门 {'通过' if passed else '拒绝'}: {path}"
                + (f"（{', '.join(rejections)}）" if rejections else "")
            ),
        )

    async def bitpro_strategy_create(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        # The factory type is the read-only protocol; the runtime object is the
        # full BitPro adapter. Write access is gated by the research.v1 profile
        # in _preflight, not by this local type.
        adapter = cast(Any, adapter_factory())
        # Provenance binding: when workspace_path is supplied the submitted
        # code IS the validated workspace file - the model cannot paraphrase
        # code between the static gate and the platform upload.
        workspace_path = str(arguments.get("workspace_path", "")).strip()
        script_content = str(arguments.get("script_content", ""))
        if workspace_path:
            from hashlib import sha256

            workspace = _workspace_for(mission)
            read_result = await anyio.to_thread.run_sync(
                lambda: workspace.read_file(workspace_path), limiter=limiter
            )
            if read_result.get("status") != "ok":
                raise ValueError(
                    f"workspace file {workspace_path} not found; run "
                    "research.validate_strategy_code on it first"
                )
            script_content = str(read_result.get("content", ""))
            content_hash = sha256(script_content.encode("utf-8")).hexdigest()[:16]
            if (
                arguments.get("validated_content_hash")
                and content_hash != str(arguments["validated_content_hash"])
            ):
                raise ValueError(
                    "workspace file changed since the static gate "
                    f"(now {content_hash}); re-run research.validate_strategy_code"
                )
        if len(script_content) < 20:
            raise ValueError(
                "supply workspace_path (preferred) or script_content with the "
                "full strategy code"
            )
        raw_symbols = arguments.get("symbols")
        created = await anyio.to_thread.run_sync(
            lambda: adapter.strategy_create(
                name=str(arguments["name"]),
                script_content=script_content,
                description=str(arguments.get("description", "")) or None,
                exchange=str(arguments.get("exchange", "okx")),
                symbols=(
                    [str(item) for item in raw_symbols]
                    if isinstance(raw_symbols, list)
                    else None
                ),
            ),
            limiter=limiter,
        )
        payload = created if isinstance(created, dict) else {}
        strategy_id = payload.get("strategy_id") or payload.get("id")
        if strategy_id is None:
            raise ValueError(f"BitPro strategy_create returned no strategy_id: {payload}")
        return ToolResult(
            payload={"strategy_id": strategy_id, "name": payload.get("name", arguments["name"])},
            source_refs=(f"bitpro:strategy:{strategy_id}",),
            public_summary=f"BitPro 策略已创建 strategy_id={strategy_id}。",
        )

    async def bitpro_backtest_start(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        adapter = cast(Any, adapter_factory())
        started_job = await anyio.to_thread.run_sync(
            lambda: adapter.backtest_start_job(
                strategy_id=int(arguments["strategy_id"]),
                start_date=str(arguments["start_date"]),
                end_date=str(arguments["end_date"]),
                initial_capital=float(arguments.get("initial_capital", 10_000.0)),
                exchange="okx",
                symbol=str(arguments.get("symbol", "")) or None,
                timeframe=str(arguments.get("timeframe", "")) or None,
                wait_for_result=True,
            ),
            limiter=limiter,
        )
        payload = started_job if isinstance(started_job, dict) else {}
        backtest_id = str(
            payload.get("backtest_id") or (payload.get("job") or {}).get("backtest_id", "")
        )
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        if not backtest_id and not metrics:
            raise ValueError(f"BitPro backtest_start returned no backtest_id: {str(payload)[:200]}")
        return ToolResult(
            payload={"backtest_id": backtest_id, "metrics": metrics},
            source_refs=(
                (f"bitpro:backtest:{backtest_id}",) if backtest_id else ("bitpro:backtest",)
            ),
            public_summary=(
                f"BitPro 回测完成 backtest_id={backtest_id}；"
                f"核心指标 {json.dumps(metrics, ensure_ascii=False)[:200]}"
            ),
        )

    async def bitpro_backtest_result(
        arguments: dict[str, Any],
        mission: MissionProjection,
        plan: PlanV2,
        step: PlanStepV2,
        attempt: int,
    ) -> ToolResult:
        adapter = cast(Any, adapter_factory())
        result = await anyio.to_thread.run_sync(
            lambda: adapter.backtest_get_result(
                backtest_id=str(arguments["backtest_id"]),
                sample_limit=int(arguments.get("sample_limit", 20)),
            ),
            limiter=limiter,
        )
        payload = result if isinstance(result, dict) else {}
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        return ToolResult(
            payload={"metrics": metrics, "items": payload.get("artifacts", [])[:10], "count": 1},
            source_refs=(f"bitpro:backtest:{arguments['backtest_id']}",),
            public_summary=f"已读取回测 {arguments['backtest_id']} 的真实指标。",
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
        "strategy.draft": strategy_draft,
        "bitpro.live_strategy_summary": bitpro_live_strategy_summary,
        "bitpro.order_history": bitpro_order_history,
        "bitpro.meta": bitpro_meta,
        "paper.summary": paper_summary,
        "portfolio.assessment": portfolio_assessment,
        "world_model.snapshot": world_model_snapshot,
        "monitor.summary": monitor_summary,
        "execution.intent_summary": execution_intent_summary,
        "workspace.write_file": workspace_write_file,
        "workspace.run": workspace_run,
        "research.validate_strategy_code": research_validate_strategy_code,
        "bitpro.strategy_create": bitpro_strategy_create,
        "bitpro.backtest_start": bitpro_backtest_start,
        "bitpro.backtest_result": bitpro_backtest_result,
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
            f"{item['inst_id']} {item['side']} 仓位浮盈亏 {_fmt_num(item['unrealized_pnl'])}"
            for item in positions
        )
    if focus == "risk":
        return "；".join(
            f"{item['inst_id']} {item['side']} 仓位名义金额 {_fmt_num(item['notional'])}；"
            "缺少完整风险限额，不能自动调整仓位"
            for item in positions
        )
    position_text = "；".join(
        (
            f"持仓：{item['inst_id']} {item['side']}，金额 {_fmt_num(item['notional'])}，"
            f"浮盈亏 {_fmt_num(item['unrealized_pnl'])}"
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


def _number_or_none(value: object) -> float | None:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


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
