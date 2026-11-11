"""Worker liveness: per-loop outcomes kept in memory and flushed to one database row.

The API and the worker are separate processes that share only the database, so `/api/healthz` can
learn that the worker is alive, which of its loops keep failing and how late its event loop runs
only from a row the worker keeps fresh. Before this, a worker whose loops had all stopped doing
useful work looked exactly like a healthy one.

Recorded per loop: last success and last failure time, the failure streak, totals, supervisor
restarts and the last failure's *type*. Exception messages are never stored: they can carry
credentials or customer data. Recorded per process: the worst lateness of the flush timer since
the previous flush (event-loop lag). A synchronous call that blocks the loop for 40 seconds shows
up there as roughly 40, which is how a stalled worker is told apart from an idle one.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import math
import os
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.orm import Mapped, mapped_column

from hypertrade.build_info import get_build_info
from hypertrade.db import Base, Database, TimestampMixin
from hypertrade.runtime.stall_evidence import process_stats

logger = logging.getLogger("hypertrade.heartbeat")

FLUSH_INTERVAL_SECONDS = 30.0
# The reported event-loop lag is the worst of this many recent flush windows (~5 minutes), so a
# reader polling every minute still sees a spike instead of the next window's zero.
LAG_WINDOWS = 10
# Six missed flushes. A synchronous call can legitimately hold the event loop for a while (the
# lag is reported separately), so one slow tick must not flag the worker.
STALE_AFTER_SECONDS = 180.0
# A row this old belongs to a worker that was retired, not to one that stopped.
FORGET_AFTER_SECONDS = 24 * 3600.0
# Consecutive failures after which a loop counts as failing rather than unlucky.
FAILING_STREAK = 3
# Frames kept of a stall's stack (the watchdog already trims; this bounds what is stored).
STALL_STACK_FRAMES = 12
# What a stall's evidence may hold: it is rebuilt from a JSON column on every read, so it is bounded
# on the way in and again on the way out.
_EVIDENCE_STRING = 160
_EVIDENCE_ITEMS = 12
_EVIDENCE_KEYS = 16
_EVIDENCE_DEPTH = 4
# Integers beyond this are not counters; JSON readers and databases cannot be trusted with them.
_EVIDENCE_INT_LIMIT = 2**63
# Distinct causes the stall counters keep (the set the watchdog uses is far smaller).
_STALL_CAUSE_KEYS = 16
DEFAULT_WORKER_ID = "worker"


class WorkerHeartbeat(Base, TimestampMixin):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    build_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    components_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    process_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


def default_worker_id() -> str:
    """One row per worker. Set HYPERTRADE_WORKER_ID when running more than one replica."""
    return (os.environ.get("HYPERTRADE_WORKER_ID") or DEFAULT_WORKER_ID).strip()[:64]


def _iso(moment: datetime | None) -> str:
    return (moment or datetime.now(UTC)).isoformat()


class HeartbeatRegistry:
    """Thread-safe, in-memory outcomes; the heartbeat loop flushes a snapshot to the database."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._components: dict[str, dict[str, Any]] = {}
        self._lag_window = 0.0
        self._lag_history: deque[float] = deque(maxlen=LAG_WINDOWS)
        self._last_stall: dict[str, Any] | None = None
        self._stalls_total = 0
        self._stall_causes: dict[str, int] = {}

    def _entry(self, component: str) -> dict[str, Any]:
        return self._components.setdefault(
            component,
            {
                "last_ok_at": None,
                "last_error_at": None,
                "last_error_type": None,
                "consecutive_failures": 0,
                "failures_total": 0,
                "restarts_total": 0,
            },
        )

    def record_success(self, component: str, *, now: datetime | None = None) -> None:
        with self._lock:
            entry = self._entry(component)
            entry["last_ok_at"] = _iso(now)
            entry["consecutive_failures"] = 0

    def record_failure(
        self,
        component: str,
        exc: BaseException,
        *,
        restarted: bool = False,
        now: datetime | None = None,
    ) -> None:
        with self._lock:
            entry = self._entry(component)
            entry["last_error_at"] = _iso(now)
            entry["last_error_type"] = type(exc).__name__  # the type only, never the message
            entry["consecutive_failures"] += 1
            entry["failures_total"] += 1
            if restarted:
                entry["restarts_total"] += 1

    def note_loop_lag(self, seconds: float) -> None:
        with self._lock:
            self._lag_window = max(self._lag_window, seconds)

    def note_stall(
        self,
        seconds: float,
        stack: list[str] | None = None,
        *,
        new_episode: bool = False,
        now: datetime | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        """Record what the loop watchdog saw while the event loop was blocked.

        ``stack`` (deepest frame first) is given when a stall is sampled; calling again with only
        ``seconds`` updates the duration of the last stall once it has ended. ``evidence`` (see
        ``stall_evidence``) explains the stall that has just ended and is attached to it.
        """
        with self._lock:
            if new_episode:
                self._stalls_total += 1
            if stack is not None:
                self._last_stall = {
                    "at": _iso(now),
                    "seconds": round(seconds, 1),
                    "stack": [str(frame)[:160] for frame in stack[:STALL_STACK_FRAMES]],
                }
            elif self._last_stall is not None:
                self._last_stall["seconds"] = round(max(seconds, self._last_stall["seconds"]), 1)
            if evidence is not None and self._last_stall is not None:
                self._last_stall["evidence"] = _clean(evidence)

    def note_stall_cause(self, cause: str) -> None:
        """Count a finished stall under the cause the watchdog gave it."""
        key = str(cause)[:32]
        with self._lock:
            if key in self._stall_causes or len(self._stall_causes) < _STALL_CAUSE_KEYS:
                self._stall_causes[key] = self._stall_causes.get(key, 0) + 1

    def stall_causes(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stall_causes)

    def stall_snapshot(self) -> tuple[dict[str, Any] | None, int]:
        with self._lock:
            return (deepcopy(self._last_stall), self._stalls_total)

    def snapshot(self, *, close_window: bool = False) -> tuple[dict[str, dict[str, Any]], float]:
        """Loop outcomes plus the worst event-loop lag over the recent flush windows.

        ``close_window`` ends the current lag window (the flush does this); without it the
        snapshot is a read-only view.
        """
        with self._lock:
            if close_window:
                self._lag_history.append(self._lag_window)
                self._lag_window = 0.0
            lag = max([*self._lag_history, self._lag_window])
            return deepcopy(self._components), lag


HEARTBEATS = HeartbeatRegistry()


def flush_heartbeat(
    db: Database,
    *,
    worker_id: str,
    started_at: datetime,
    registry: HeartbeatRegistry = HEARTBEATS,
    now: datetime | None = None,
    stats: Callable[[], dict[str, Any]] | None = None,
) -> bool:
    """Upsert this worker's row. Never raises: liveness reporting must not stop the worker."""
    components, lag = registry.snapshot(close_window=True)
    last_stall, stalls_total = registry.stall_snapshot()
    try:
        process = _clean((stats or process_stats)())
    except Exception:
        logger.debug("process statistics could not be read", exc_info=True)
        process = None
    try:
        with db.session() as session:
            session.merge(
                WorkerHeartbeat(
                    worker_id=worker_id,
                    started_at=started_at,
                    heartbeat_at=now or datetime.now(UTC),
                    build_sha=get_build_info().sha,
                    components_json=components,
                    process_json={
                        "event_loop_lag_max_seconds": round(lag, 3),
                        "last_stall": last_stall,
                        "stalls_total": stalls_total,
                        "stall_causes": registry.stall_causes(),
                        "process": process,
                    },
                )
            )
    except Exception:
        logger.warning("worker heartbeat could not be written", exc_info=True)
        return False
    return True


async def heartbeat_loop(
    db: Database,
    *,
    registry: HeartbeatRegistry = HEARTBEATS,
    interval_seconds: float = FLUSH_INTERVAL_SECONDS,
    worker_id: str | None = None,
) -> None:
    """Flush the registry every ``interval_seconds`` and measure how late the timer fires."""
    identity = worker_id or default_worker_id()
    started_at = datetime.now(UTC)
    loop = asyncio.get_running_loop()
    # Written from a thread so a slow database never blocks the event loop it is measuring, and
    # from a thread of its own: in the shared pool the flush would queue behind long ARC / AVO
    # steps and a busy worker would look dead.
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hypertrade-heartbeat")
    flush = functools.partial(
        flush_heartbeat, db, worker_id=identity, started_at=started_at, registry=registry
    )
    try:
        while True:
            await loop.run_in_executor(executor, flush)
            # Lag is how much later than requested the timer fires, so the due time is taken
            # right before sleeping: the database write above must not count as event-loop lag.
            due = loop.time() + interval_seconds
            await asyncio.sleep(interval_seconds)
            registry.note_loop_lag(max(0.0, loop.time() - due))
    finally:
        executor.shutdown(wait=False)


def _aware(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _age_seconds(iso: Any, now: datetime) -> float | None:
    if not isinstance(iso, str):
        return None
    try:
        return round(max(0.0, (now - _aware(datetime.fromisoformat(iso))).total_seconds()), 1)
    except ValueError:
        return None


def _clean(value: Any, depth: int = 0) -> Any:
    """``value`` limited to JSON scalars, short strings and small lists and dicts.

    A stall's evidence is rebuilt from a JSON column on every read and published unauthenticated,
    so what reaches ``/api/healthz`` is bounded here whatever the column holds: numbers that JSON
    cannot carry (NaN, infinity, an integer too big to be a counter) become null, strings are cut,
    containers are capped and nested no deeper than ``_EVIDENCE_DEPTH``.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, int):  # a bool is an int and stays what it is
        return value if -_EVIDENCE_INT_LIMIT < value < _EVIDENCE_INT_LIMIT else None
    if isinstance(value, str):
        return value[:_EVIDENCE_STRING]
    if depth >= _EVIDENCE_DEPTH:
        return None
    if isinstance(value, list | tuple):
        return [_clean(item, depth + 1) for item in value[:_EVIDENCE_ITEMS]]
    if isinstance(value, dict):
        return {
            str(key)[:48]: _clean(item, depth + 1)
            for key, item in list(value.items())[:_EVIDENCE_KEYS]
        }
    return None


def _stall_view(raw: Any, now: datetime) -> dict[str, Any] | None:
    """The watchdog's last stall as stored, re-validated: it came out of a JSON column."""
    if not isinstance(raw, dict) or not isinstance(raw.get("seconds"), int | float):
        return None
    stack = raw.get("stack")
    view: dict[str, Any] = {
        "seconds": raw["seconds"],
        "age_seconds": _age_seconds(raw.get("at"), now),
        "running": [str(frame)[:160] for frame in stack[:STALL_STACK_FRAMES]]
        if isinstance(stack, list)
        else [],
    }
    # What explains the stall (cause, threads, CPU, garbage collection, host), once it has ended.
    evidence = _clean(raw.get("evidence"))
    if isinstance(evidence, dict):
        for key, value in evidence.items():
            view.setdefault(key, value)
    return view


def _count(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _process_view(raw: Any) -> dict[str, Any] | None:
    cleaned = _clean(raw) if isinstance(raw, dict) else None
    return cleaned if isinstance(cleaned, dict) else None


def _safely(build: Callable[[], Any]) -> Any:
    """What ``build`` returns, or None: this part of a worker row is diagnostics only, and
    ``/api/healthz`` must answer whatever a row holds."""
    try:
        return build()
    except Exception:
        logger.warning("part of a worker heartbeat could not be read", exc_info=True)
        return None


def _counts(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    counts = {str(key)[:32]: _count(value) for key, value in list(raw.items())[:_STALL_CAUSE_KEYS]}
    return {key: value if 0 <= value < _EVIDENCE_INT_LIMIT else 0 for key, value in counts.items()}


def _instance_view(row: WorkerHeartbeat, now: datetime, stale_after: float) -> dict[str, Any]:
    heartbeat_age = max(0.0, (now - _aware(row.heartbeat_at)).total_seconds())
    stale = heartbeat_age > stale_after
    components: dict[str, dict[str, Any]] = {}
    raw = row.components_json if isinstance(row.components_json, dict) else {}
    for name in sorted(raw):
        entry = raw[name] if isinstance(raw[name], dict) else {}
        components[name] = {
            "last_ok_age_seconds": _age_seconds(entry.get("last_ok_at"), now),
            "last_error_age_seconds": _age_seconds(entry.get("last_error_at"), now),
            "last_error_type": entry.get("last_error_type"),
            "consecutive_failures": _count(entry.get("consecutive_failures")),
            "failures_total": _count(entry.get("failures_total")),
            "restarts_total": _count(entry.get("restarts_total")),
        }
    process = row.process_json if isinstance(row.process_json, dict) else {}
    lag = process.get("event_loop_lag_max_seconds")
    return {
        "worker_id": row.worker_id,
        "stale": stale,
        "heartbeat_age_seconds": round(heartbeat_age, 1),
        "uptime_seconds": round(max(0.0, (now - _aware(row.started_at)).total_seconds()), 1),
        "build_sha": row.build_sha,
        "event_loop_lag_max_seconds": lag if isinstance(lag, int | float) else None,
        "stalls_total": _count(process.get("stalls_total")),
        "stall_causes": _safely(lambda: _counts(process.get("stall_causes"))) or {},
        "last_stall": _safely(lambda: _stall_view(process.get("last_stall"), now)),
        "process": _safely(lambda: _process_view(process.get("process"))),
        "failing_components": [
            name
            for name, view in components.items()
            if view["consecutive_failures"] >= FAILING_STREAK
        ],
        "components": components,
    }


def read_worker_status(
    db: Database,
    *,
    now: datetime | None = None,
    stale_after_seconds: float = STALE_AFTER_SECONDS,
    forget_after_seconds: float = FORGET_AFTER_SECONDS,
) -> dict[str, Any]:
    """What `/api/healthz` reports about the worker: alive, stale or unknown, never raising.

    ``unknown`` means no worker has reported (a development database, or the first moments after
    a deploy) and must not be treated as unhealthy; ``stale`` means one reported before but has
    stopped.
    """
    moment = now or datetime.now(UTC)
    try:
        with db.session() as session:
            rows = list(
                session.scalars(select(WorkerHeartbeat).order_by(WorkerHeartbeat.worker_id))
            )
    except Exception:
        logger.warning("worker heartbeats could not be read", exc_info=True)
        return {"status": "unknown", "reason": "unreadable", "instances": []}

    instances = [
        _instance_view(row, moment, stale_after_seconds)
        for row in rows
        if (moment - _aware(row.heartbeat_at)).total_seconds() <= forget_after_seconds
    ]
    if not instances:
        return {"status": "unknown", "instances": []}
    live = [item for item in instances if not item["stale"]]
    return {
        "status": "alive" if live else "stale",
        "failing_components": sorted(
            {name for item in live for name in item["failing_components"]}
        ),
        "instances": instances,
    }
