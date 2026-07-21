"""Ports for the canonical Thread/Turn protocol."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from hypertrade.runtime.domain.thread_turn import (
    ThreadEventV1,
    ThreadSnapshotV1,
    TurnProjectionV1,
)


class ThreadStore(Protocol):
    async def create_thread(
        self,
        *,
        tenant_id: str,
        owner: str,
        title: str,
        retention: str,
    ) -> ThreadSnapshotV1: ...

    async def get(self, thread_id: str) -> ThreadSnapshotV1: ...

    async def start_turn(
        self,
        thread_id: str,
        *,
        client_message_id: str,
        text: str,
        actor: str,
    ) -> tuple[ThreadSnapshotV1, TurnProjectionV1, bool]: ...

    async def claim_turn(self, thread_id: str, turn_id: str, *, worker_id: str) -> int: ...

    async def append(
        self,
        thread_id: str,
        event_type: str,
        *,
        payload: dict[str, object],
        actor: str,
        idempotency_key: str = "",
        causation_id: str = "",
        policy_snapshot_hash: str = "",
        fencing_token: int = 0,
    ) -> ThreadSnapshotV1: ...

    async def events(
        self,
        thread_id: str,
        *,
        after: int = 0,
        limit: int = 500,
    ) -> Sequence[ThreadEventV1]: ...

    async def dispose(self) -> None: ...
