"""Application service joining canonical Turns to the governed Mission Runtime."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from typing import Any

from hypertrade.db import new_id
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
    ThreadSnapshotV1,
    ThreadStatus,
    TurnProjectionV1,
    TurnStatus,
    content_hash,
)
from hypertrade.runtime.ports import MissionStore
from hypertrade.runtime.thread_ports import ThreadStore

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
    ) -> None:
        self.thread_store = thread_store
        self.mission_store = mission_store
        self.mission_runtime = mission_runtime
        self.worker_enabled = worker_enabled
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
