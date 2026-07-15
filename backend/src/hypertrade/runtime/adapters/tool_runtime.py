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

from hypertrade.db import AgentToolObservation, Database
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.service import MemoryService
from hypertrade.rag.service import RagService
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


ToolHandler = Callable[
    [dict[str, Any], MissionProjection, PlanV2, PlanStepV2, int], Awaitable[ToolResult]
]


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
        return _step_observation(observation)

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


def builtin_handlers(db: Database, *, knowledge_dir: str) -> dict[str, ToolHandler]:
    limiter = anyio.CapacityLimiter(8)

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

        def read() -> list[dict[str, str]]:
            return [
                {
                    "inst_id": row.inst_id,
                    "last": str(row.last),
                    "volume_ccy_24h": str(row.volume_ccy_24h),
                    "change_utc0_pct": str(row.change_utc0_pct),
                }
                for row in MarketRepository(db).latest_tickers(limit=limit)
            ]

        items = await anyio.to_thread.run_sync(read, limiter=limiter)
        return ToolResult(
            payload={"items": items, "count": len(items)},
            source_refs=("hypertrade_db:market_tickers",),
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
        items = [
            {
                "memory_id": row.id,
                "kind": row.kind,
                "tags": row.tags,
                "confidence": str(row.confidence),
            }
            for row in rows
        ]
        return ToolResult(
            payload={"items": items, "count": len(items)},
            source_refs=tuple(f"memory:{row.id}" for row in rows) or ("memory:no_matches",),
        )

    return {
        "runtime.objective_inspection": objective,
        "market.summary": market_summary,
        "rag.search": rag_search,
        "memory.search": memory_search,
    }


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
    summary: str = "Capability completed with a schema-valid observation.",
) -> StepObservationV2:
    status = "succeeded" if observation.status in {"succeeded", "replayed"} else "failed"
    return StepObservationV2.model_validate(
        {
            "status": status,
            "summary": summary,
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
