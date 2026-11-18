"""Application service joining canonical Turns to the governed Mission Runtime."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from hashlib import sha256
from typing import Any

import anyio

from hypertrade.db import Database, new_id
from hypertrade.memory.service import MemoryService
from hypertrade.runtime.application.entrypoint import (
    active_mission_permission_profile,
    mission_request_for_prompt,
    mission_run_projection,
)
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.application.thread_context import compile_thread_context
from hypertrade.runtime.domain.models import MissionStatus
from hypertrade.runtime.domain.thread_turn import (
    TERMINAL_TURN_STATUSES,
    ThreadProjectionV1,
    ThreadSnapshotV1,
    ThreadStatus,
    TurnProjectionV1,
    TurnStatus,
    content_hash,
)
from hypertrade.runtime.ports import MissionStore
from hypertrade.runtime.thread_ports import ThreadStore

_LOGGER = logging.getLogger(__name__)

_CONSOLIDATE_CAPABILITIES = frozenset(
    {"arc.evolution_status", "bitpro.variant_status", "bitpro.paper_snapshot"}
)
_REMEMBER_KEYWORDS = ("记住", "记下来", "保存记忆", "remember")

_MISSION_WAIT_STATES = {
    MissionStatus.WAITING_APPROVAL,
    MissionStatus.WAITING_INPUT,
    MissionStatus.PAUSED,
}
_MISSION_TERMINAL_STATES = {
    MissionStatus.CANCELED,
    MissionStatus.COMPLETED,
    MissionStatus.FAILED,
    MissionStatus.BUDGET_EXHAUSTED,
}


class ThreadTurnService:
    """Run one read-only Mission behind a durable canonical Turn."""

    def __init__(
        self,
        thread_store: ThreadStore,
        mission_store: MissionStore,
        mission_runtime: MissionRuntime,
        *,
        worker_enabled: bool,
        db: Database | None = None,
    ) -> None:
        self.thread_store = thread_store
        self.mission_store = mission_store
        self.mission_runtime = mission_runtime
        self.worker_enabled = worker_enabled
        self._db: Database | None = db
        self._tasks: set[asyncio.Task[None]] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._worker_id = new_id("turn_worker")
        self._active_tokens: dict[str, int] = {}

    async def create_thread(
        self,
        *,
        owner: str,
        title: str,
        retention: str,
    ) -> ThreadSnapshotV1:
        return await self.thread_store.create_thread(
            tenant_id="default",
            owner=owner,
            title=title,
            retention=retention,
        )

    async def list_threads(
        self,
        *,
        tenant_id: str = "default",
        status: str = "",
        limit: int = 20,
    ) -> Sequence[ThreadProjectionV1]:
        return await self.thread_store.list_threads(
            tenant_id=tenant_id,
            status=status,
            limit=limit,
        )

    async def start_turn(
        self,
        thread_id: str,
        *,
        client_message_id: str,
        text: str,
        actor: str,
    ) -> tuple[ThreadSnapshotV1, TurnProjectionV1, bool]:
        result = await self.thread_store.start_turn(
            thread_id,
            client_message_id=client_message_id,
            text=text,
            actor=actor,
        )
        _, turn, _ = result
        self.ensure_scheduled(thread_id, turn.turn_id)
        return result

    async def archive(self, thread_id: str, *, actor: str) -> ThreadSnapshotV1:
        snapshot = await self.thread_store.get(thread_id)
        if snapshot.thread is None:
            raise KeyError(thread_id)
        if snapshot.thread.status == ThreadStatus.ARCHIVED:
            return snapshot
        return await self.thread_store.append(
            thread_id,
            "thread.archived",
            actor=actor,
            idempotency_key=f"{thread_id}:archived",
            payload={},
        )

    def ensure_scheduled(self, thread_id: str, turn_id: str) -> None:
        key = f"{thread_id}:{turn_id}"
        if any(task.get_name() == key and not task.done() for task in self._tasks):
            return
        task = asyncio.create_task(self.execute_turn(thread_id, turn_id), name=key)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def execute_turn(self, thread_id: str, turn_id: str) -> None:
        key = f"{thread_id}:{turn_id}"
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            snapshot = await self.thread_store.get(thread_id)
            if snapshot.turn(turn_id).status in TERMINAL_TURN_STATUSES:
                return
            token = await self.thread_store.claim_turn(
                thread_id,
                turn_id,
                worker_id=self._worker_id,
            )
            self._active_tokens[key] = token
            try:
                await self._execute_locked(thread_id, turn_id)
            except Exception:  # noqa: BLE001 - public failure must be bounded and terminal
                await self._fail_turn(thread_id, turn_id)
            finally:
                self._active_tokens.pop(key, None)

    async def interrupt(self, thread_id: str, turn_id: str, *, actor: str) -> ThreadSnapshotV1:
        snapshot = await self.thread_store.get(thread_id)
        turn = snapshot.turn(turn_id)
        if turn.status in TERMINAL_TURN_STATUSES:
            return snapshot
        if turn.mission_id:
            mission = await self.mission_store.get(turn.mission_id)
            if mission.status not in _MISSION_TERMINAL_STATES:
                await self.mission_runtime.cancel(turn.mission_id, actor=actor)
        return await self.thread_store.append(
            thread_id,
            "turn.cancelled",
            actor=actor,
            idempotency_key=f"{turn_id}:terminal:cancelled",
            payload={"turn_id": turn_id, "reason": "operator_interrupt"},
        )

    async def _execute_locked(self, thread_id: str, turn_id: str) -> None:
        snapshot = await self.thread_store.get(thread_id)
        turn = snapshot.turn(turn_id)
        if turn.status in TERMINAL_TURN_STATUSES or turn.status in {
            TurnStatus.WAITING_INPUT,
            TurnStatus.WAITING_APPROVAL,
        }:
            return

        if turn.status == TurnStatus.ACCEPTED:
            snapshot = await self._append(
                thread_id,
                "turn.contextualization_started",
                actor="thread_runtime",
                idempotency_key=f"{turn_id}:context:start",
                payload={"turn_id": turn_id},
            )
            turn = snapshot.turn(turn_id)

        if turn.status == TurnStatus.CONTEXTUALIZING and not turn.resolved_context:
            context = compile_thread_context(snapshot, turn_id)
            snapshot = await self._append(
                thread_id,
                "turn.context_resolved",
                actor="thread_runtime",
                idempotency_key=f"{turn_id}:context:resolved",
                payload={
                    "turn_id": turn_id,
                    "resolved_context": context.model_dump(mode="json"),
                },
            )
            turn = snapshot.turn(turn_id)
            if context.input_gap:
                await self._append(
                    thread_id,
                    "turn.input_requested",
                    actor="thread_runtime",
                    idempotency_key=f"{turn_id}:input-gap",
                    payload={
                        "turn_id": turn_id,
                        "item_id": _stable_id("itm", turn_id, "input-gap"),
                        "content": {"message": context.input_gap},
                    },
                )
                return

        if turn.status == TurnStatus.CONTEXTUALIZING:
            objective = str(turn.resolved_context.get("normalized_objective") or "").strip()
            mission = await self.mission_runtime.create(
                mission_request_for_prompt(
                    objective,
                    actor="canonical_thread",
                    idempotency_key=f"thread:{thread_id}:turn:{turn_id}",
                )
            )
            snapshot = await self._append(
                thread_id,
                "turn.started",
                actor="thread_runtime",
                idempotency_key=f"{turn_id}:started",
                policy_snapshot_hash=content_hash(
                    {"permission_profile": active_mission_permission_profile()}
                ),
                payload={"turn_id": turn_id, "mission_id": mission.mission_id},
            )
            turn = snapshot.turn(turn_id)

        if not turn.mission_id:
            raise RuntimeError("canonical Turn has no linked Mission")
        mission = await self.mission_store.get(turn.mission_id)
        if mission.status not in _MISSION_TERMINAL_STATES | _MISSION_WAIT_STATES:
            mission = (
                await self._await_worker(mission.mission_id)
                if self.worker_enabled
                else await self.mission_runtime.run(mission.mission_id)
            )
        if mission.status == MissionStatus.WAITING_INPUT:
            await self._append(
                thread_id,
                "turn.input_requested",
                actor="thread_runtime",
                idempotency_key=f"{turn_id}:mission-input",
                payload={
                    "turn_id": turn_id,
                    "item_id": _stable_id("itm", turn_id, "mission-input"),
                    "content": {"message": "Mission 需要补充输入后才能继续。"},
                },
            )
            return
        if mission.status == MissionStatus.WAITING_APPROVAL:
            await self._append(
                thread_id,
                "turn.approval_requested",
                actor="thread_runtime",
                idempotency_key=f"{turn_id}:mission-approval",
                payload={
                    "turn_id": turn_id,
                    "item_id": _stable_id("itm", turn_id, "mission-approval"),
                    "content": {"message": "Mission 需要授权后才能继续。"},
                },
            )
            return
        await self._deliver_mission(thread_id, turn_id, mission)

    async def _await_worker(self, mission_id: str) -> Any:
        while True:
            mission = await self.mission_store.get(mission_id)
            if mission.status in _MISSION_TERMINAL_STATES | _MISSION_WAIT_STATES:
                return mission
            await asyncio.sleep(0.25)

    async def _deliver_mission(self, thread_id: str, turn_id: str, mission: Any) -> None:
        response = await mission_run_projection(mission, self.mission_store)
        completion_proof = mission.completion_proof
        completion_valid = (
            mission.status == MissionStatus.COMPLETED
            and completion_proof is not None
            and completion_proof.passed
            and completion_proof.mission_version + 1 == mission.version
        )
        attempts = response.get("report_json", {}).get("attempts", [])
        for index, attempt in enumerate(attempts if isinstance(attempts, list) else []):
            if not isinstance(attempt, dict):
                continue
            item_id = _stable_id("itm", turn_id, "tool", str(index))
            capability = str(attempt.get("capability_id") or "governed_read")
            await self._append(
                thread_id,
                "tool_call.started",
                actor="thread_runtime",
                idempotency_key=f"{turn_id}:tool:{index}:started",
                payload={
                    "turn_id": turn_id,
                    "item_id": item_id,
                    "content": {"capability_id": capability},
                },
            )
            await self._append(
                thread_id,
                "tool_call.completed",
                actor="thread_runtime",
                idempotency_key=f"{turn_id}:tool:{index}:completed",
                payload={
                    "turn_id": turn_id,
                    "item_id": item_id,
                    "content": {
                        "capability_id": capability,
                        "status": str(attempt.get("status") or "unknown"),
                    },
                },
            )
        operator_response = response.get("report_json", {}).get("operator_response", {})
        evidence = (
            operator_response.get("evidence", []) if isinstance(operator_response, dict) else []
        )
        unknowns = (
            operator_response.get("unknowns", []) if isinstance(operator_response, dict) else []
        )
        if evidence:
            await self._append(
                thread_id,
                "evidence_ready.completed",
                actor="thread_runtime",
                idempotency_key=f"{turn_id}:evidence",
                payload={
                    "turn_id": turn_id,
                    "item_id": _stable_id("itm", turn_id, "evidence"),
                    "content": {"evidence": evidence[:20]},
                },
            )
        if not evidence and not unknowns:
            unknowns = ["No grounded evidence was produced."]
        await self._append(
            thread_id,
            "agent_message.completed",
            actor="thread_runtime",
            idempotency_key=f"{turn_id}:answer",
            payload={
                "turn_id": turn_id,
                "item_id": _stable_id("itm", turn_id, "answer"),
                "content": {
                    "text": str(response.get("report_markdown") or ""),
                    "mission_id": mission.mission_id,
                    "operator_response": operator_response,
                    "unknowns": unknowns,
                },
            },
        )
        if completion_valid:
            await self._consolidate_memory(
                thread_id=thread_id,
                turn_id=turn_id,
                mission=mission,
                attempts=attempts,
                operator_response=operator_response,
                evidence=evidence,
            )
        terminal = "turn.completed" if completion_valid else "turn.failed"
        await self._append(
            thread_id,
            terminal,
            actor="thread_runtime",
            idempotency_key=f"{turn_id}:terminal:{terminal}",
            payload={
                "turn_id": turn_id,
                "mission_status": mission.status.value,
                "completion_proof_id": (
                    completion_proof.proof_id if completion_valid else ""
                ),
            },
        )

    def _resolve_memory_db(self) -> Database | None:
        if self._db is not None and hasattr(self._db, "session"):
            return self._db
        executor = getattr(self.mission_runtime, "executor", None)
        executor_db = getattr(executor, "db", None)
        if executor_db is not None and hasattr(executor_db, "session"):
            return executor_db  # type: ignore[no-any-return]
        for store in (self.mission_store, self.thread_store):
            engine = getattr(store, "engine", None)
            if engine is None:
                continue
            try:
                raw_url = engine.url.render_as_string(hide_password=False)
            except Exception:  # noqa: BLE001
                continue
            sync_url = raw_url.replace("sqlite+aiosqlite:", "sqlite:", 1)
            if sync_url == "sqlite:///:memory:":
                continue
            self._db = Database(sync_url)
            return self._db
        return None

    async def _consolidate_memory(
        self,
        *,
        thread_id: str,
        turn_id: str,
        mission: Any,
        attempts: Any,
        operator_response: Any,
        evidence: Any,
    ) -> None:
        db = self._resolve_memory_db()
        if db is None:
            return
        try:
            snapshot = await self.thread_store.get(thread_id)
            turn = snapshot.turn(turn_id)
            resolved_ctx = turn.resolved_context if isinstance(turn.resolved_context, dict) else {}
            user_text = ""
            if turn.input_item_id:
                try:
                    item = snapshot.item(turn.input_item_id)
                    user_text = str(item.content.get("text") or "").strip()
                except KeyError:
                    user_text = ""
            if not user_text:
                user_text = str(resolved_ctx.get("normalized_objective") or "").strip()

            attempts_list = attempts if isinstance(attempts, list) else []
            evidence_list = evidence if isinstance(evidence, list) else []
            explicit_remember = any(
                keyword in user_text.casefold() for keyword in _REMEMBER_KEYWORDS
            )
            used_observed_cap = any(
                isinstance(attempt, dict)
                and str(attempt.get("capability_id") or "") in _CONSOLIDATE_CAPABILITIES
                and str(attempt.get("status") or "") == "succeeded"
                for attempt in attempts_list
            )
            already_wrote_memory = any(
                isinstance(attempt, dict)
                and str(attempt.get("capability_id") or "") == "memory.write"
                and str(attempt.get("status") or "") == "succeeded"
                for attempt in attempts_list
            )

            if explicit_remember and already_wrote_memory:
                return
            if not explicit_remember and not (used_observed_cap and evidence_list):
                return

            evidence_summary = "；".join(
                str(row.get("summary") or "").strip()
                for row in evidence_list[:2]
                if isinstance(row, dict) and str(row.get("summary") or "").strip()
            )
            decision = (
                str(operator_response.get("decision") or "").strip()
                if isinstance(operator_response, dict)
                else ""
            )
            if explicit_remember:
                kind = "operator_note"
                raw_summary = (
                    f"{user_text} — {evidence_summary}"
                    if evidence_summary
                    else (user_text or decision)
                )
            else:
                kind = "strategy_observation"
                raw_summary = evidence_summary or decision

            summary = " ".join(raw_summary.split())[:400]
            if len(summary) < 3:
                return

            tags: list[str] = ["thread_turn"]
            resolved_subject = str(resolved_ctx.get("resolved_subject") or "").strip()
            if resolved_subject and resolved_subject not in tags:
                tags.append(resolved_subject)
            raw_refs = resolved_ctx.get("subject_refs")
            if isinstance(raw_refs, list):
                for ref in raw_refs:
                    cleaned = str(ref).strip()
                    if cleaned and cleaned not in tags:
                        tags.append(cleaned)

            source_run_id = str(turn.mission_id or getattr(mission, "mission_id", "") or "")[:32]
            await anyio.to_thread.run_sync(
                lambda: MemoryService(db).write(
                    content=summary,
                    kind=kind,
                    source_run_id=source_run_id,
                    source_tool="thread_turn.consolidate",
                    tags=tags,
                )
            )
        except Exception as exc:  # noqa: BLE001 - consolidation must never fail turn delivery
            _LOGGER.debug("thread_turn memory consolidation skipped: %s", exc)

    async def _append(
        self,
        thread_id: str,
        event_type: str,
        *,
        payload: dict[str, object],
        actor: str,
        idempotency_key: str = "",
        causation_id: str = "",
        policy_snapshot_hash: str = "",
    ) -> ThreadSnapshotV1:
        turn_id = str(payload.get("turn_id") or "")
        token = self._active_tokens.get(f"{thread_id}:{turn_id}", 0)
        if not token:
            raise PermissionError("canonical Turn worker has no fencing token")
        return await self.thread_store.append(
            thread_id,
            event_type,
            payload=payload,
            actor=actor,
            idempotency_key=idempotency_key,
            causation_id=causation_id or f"fence:{token}",
            policy_snapshot_hash=policy_snapshot_hash,
            fencing_token=token,
        )

    async def _fail_turn(self, thread_id: str, turn_id: str) -> None:
        try:
            snapshot = await self.thread_store.get(thread_id)
            turn = snapshot.turn(turn_id)
            if turn.status in TERMINAL_TURN_STATUSES:
                return
            await self._append(
                thread_id,
                "turn.failed",
                actor="thread_runtime",
                idempotency_key=f"{turn_id}:terminal:runtime-failure",
                payload={"turn_id": turn_id, "code": "thread_runtime_failure"},
            )
        except Exception:  # noqa: BLE001 - no second public failure path is safe here
            return


def _stable_id(prefix: str, *parts: str) -> str:
    digest = sha256(":".join(parts).encode()).hexdigest()[:20]
    return f"{prefix}_{digest}"
