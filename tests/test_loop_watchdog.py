"""Loop watchdog: it names the call that blocks the worker's event loop, and the heartbeat that
reports it is not itself held up by the pool the blocking work shares."""

import asyncio
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypertrade import worker
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.runtime import heartbeat
from hypertrade.runtime.heartbeat import (
    HeartbeatRegistry,
    WorkerHeartbeat,
    flush_heartbeat,
    heartbeat_loop,
    read_worker_status,
)
from hypertrade.runtime.loop_watchdog import LoopWatchdog, format_stack

T0 = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
_REAL_SLEEP = asyncio.sleep


def _watchdog(registry: HeartbeatRegistry) -> LoopWatchdog:
    return LoopWatchdog(registry, threshold_seconds=0.3, poll_seconds=0.05, resample_seconds=0.4)


def blocked_here(seconds: float) -> None:
    time.sleep(seconds)  # a synchronous call holding the event loop, like the ticker writes did


async def _watched(registry: HeartbeatRegistry, scenario: Any) -> None:
    dog = _watchdog(registry)
    dog.start()
    try:
        await scenario()
    finally:
        dog.stop()


# --- what the watchdog records -------------------------------------------------------------


def test_a_blocked_loop_is_reported_with_the_blocking_function_named() -> None:
    registry = HeartbeatRegistry()

    async def scenario() -> None:
        await _REAL_SLEEP(0.2)
        blocked_here(1.2)
        await _REAL_SLEEP(0.3)

    asyncio.run(_watched(registry, scenario))

    stall, total = registry.stall_snapshot()
    assert total == 1 and stall is not None
    assert stall["seconds"] >= 1.0, "the final duration is recorded when the loop answers again"
    assert "blocked_here" in stall["stack"][0], stall["stack"]  # deepest frame first
    assert all(re.fullmatch(r"[\w.\-]+:\d+ \w+", frame) for frame in stall["stack"])


def test_the_final_duration_is_recorded_when_the_loop_answers_again() -> None:
    # A huge resample interval means the stall is sampled exactly once, at ~0.3 s. Only the
    # end-of-stall update can then make the recorded duration the real one.
    registry = HeartbeatRegistry()
    dog = LoopWatchdog(registry, threshold_seconds=0.3, poll_seconds=0.05, resample_seconds=100.0)

    async def scenario() -> None:
        dog.start()
        try:
            await _REAL_SLEEP(0.1)
            blocked_here(1.2)
            await _REAL_SLEEP(0.3)
        finally:
            dog.stop()

    asyncio.run(scenario())

    stall, total = registry.stall_snapshot()
    assert total == 1 and stall is not None
    assert stall["seconds"] >= 1.0, stall["seconds"]


def test_a_healthy_loop_records_nothing() -> None:
    registry = HeartbeatRegistry()

    async def scenario() -> None:
        for _ in range(14):
            await _REAL_SLEEP(0.05)

    asyncio.run(_watched(registry, scenario))

    assert registry.stall_snapshot() == (None, 0)


def test_a_long_stall_is_one_episode_that_is_sampled_again() -> None:
    registry = HeartbeatRegistry()
    calls: list[tuple[bool, bool]] = []
    real = registry.note_stall

    def spy(seconds: float, stack: list[str] | None = None, **kwargs: Any) -> None:
        calls.append((stack is not None, bool(kwargs.get("new_episode"))))
        real(seconds, stack, **kwargs)

    registry.note_stall = spy  # type: ignore[method-assign]

    async def scenario() -> None:
        await _REAL_SLEEP(0.1)
        blocked_here(1.6)
        await _REAL_SLEEP(0.3)

    asyncio.run(_watched(registry, scenario))

    assert sum(1 for _, new in calls if new) == 1, "one stall is one episode"
    assert sum(1 for sampled, _ in calls if sampled) >= 2, "a long stall is re-sampled"
    assert registry.stall_snapshot()[1] == 1


def test_two_separate_stalls_are_two_episodes() -> None:
    registry = HeartbeatRegistry()

    async def scenario() -> None:
        await _REAL_SLEEP(0.1)
        blocked_here(0.8)
        await _REAL_SLEEP(0.5)
        blocked_here(0.8)
        await _REAL_SLEEP(0.3)

    asyncio.run(_watched(registry, scenario))

    assert registry.stall_snapshot()[1] == 2


def test_a_stack_holds_locations_only_never_source_text_or_values() -> None:
    def deep() -> list[str]:
        api_key = "sk-live-SECRET-0123456789"  # noqa: F841 - a local the stack must not expose
        return format_stack(sys._getframe(), limit=50)

    stack = deep()

    assert stack[0].endswith(" deep") and "SECRET" not in " ".join(stack)
    assert all(re.fullmatch(r"[\w.\-]+:\d+ [\w<>]+", frame) for frame in stack), stack
    assert len(format_stack(sys._getframe(), limit=3)) == 3


def test_asyncio_internals_are_left_out_of_the_stack() -> None:
    async def inside() -> tuple[list[str], list[str]]:
        raw = [
            f"{Path(f.filename).name}:{f.lineno} {f.name}"
            for f in traceback.extract_stack(sys._getframe())
            if "/asyncio/" in f.filename
        ]
        return raw, format_stack(sys._getframe(), limit=50)

    raw, formatted = asyncio.run(inside())

    assert raw, "the test needs asyncio frames on the stack to prove they are filtered"
    assert not set(raw) & set(formatted)


def test_the_watchdog_stops_cleanly_and_exits_when_its_loop_closes() -> None:
    registry = HeartbeatRegistry()
    dog = _watchdog(registry)
    loop = asyncio.new_event_loop()
    dog.start(loop)
    assert dog._thread is not None and dog._thread.is_alive()
    dog.stop()
    assert not dog._thread.is_alive()

    other = _watchdog(registry)
    other.start(loop)
    loop.close()  # the worker is shutting down: the watchdog must not raise or linger
    assert other._thread is not None
    other._thread.join(timeout=2.0)
    assert not other._thread.is_alive()
    other.stop()


# --- the record that /api/healthz shows ----------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path}/stall.db")
    database.create_all()
    return database


def test_a_stall_reaches_the_healthz_view(db: Database) -> None:
    registry = HeartbeatRegistry()
    registry.note_stall(
        95.9, ["client.py:140 ingest_rest_once", "repository.py:80 upsert_ticker_snapshot"],
        new_episode=True, now=T0,
    )
    flush_heartbeat(db, worker_id="worker", started_at=T0, registry=registry, now=T0)

    (view,) = read_worker_status(db, now=T0 + timedelta(seconds=60))["instances"]

    assert view["stalls_total"] == 1
    assert view["last_stall"] == {
        "seconds": 95.9,
        "age_seconds": 60.0,
        "running": ["client.py:140 ingest_rest_once", "repository.py:80 upsert_ticker_snapshot"],
    }


def test_the_final_duration_updates_a_stall_without_losing_its_stack_and_never_shrinks() -> None:
    registry = HeartbeatRegistry()
    registry.note_stall(5.0, ["a.py:1 f"], new_episode=True)

    registry.note_stall(96.0)
    registry.note_stall(10.0)

    stall, total = registry.stall_snapshot()
    assert stall is not None and stall["seconds"] == 96.0 and stall["stack"] == ["a.py:1 f"]
    assert total == 1


def test_a_note_without_a_prior_stall_is_ignored() -> None:
    registry = HeartbeatRegistry()
    registry.note_stall(3.0)
    assert registry.stall_snapshot() == (None, 0)


def test_a_stored_stack_is_bounded() -> None:
    registry = HeartbeatRegistry()
    registry.note_stall(9.0, [f"f.py:{i} {'x' * 400}" for i in range(80)], new_episode=True)

    stall, _ = registry.stall_snapshot()

    assert stall is not None
    assert len(stall["stack"]) == 12 and all(len(frame) <= 160 for frame in stall["stack"])


def test_garbage_in_the_stored_json_is_tolerated(db: Database) -> None:
    with db.session() as session:
        session.add(
            WorkerHeartbeat(
                worker_id="worker",
                started_at=T0,
                heartbeat_at=T0,
                components_json={},
                process_json={"last_stall": "garbage", "stalls_total": "many"},
            )
        )
        session.add(
            WorkerHeartbeat(
                worker_id="worker-2",
                started_at=T0,
                heartbeat_at=T0,
                components_json={},
                # a dict, but not what the watchdog writes; a bool is not a count
                process_json={
                    "last_stall": {"seconds": "long", "stack": "x"},
                    "stalls_total": True,
                },
            )
        )

    views = read_worker_status(db, now=T0 + timedelta(seconds=5))["instances"]

    assert len(views) == 2
    assert all(v["last_stall"] is None and v["stalls_total"] == 0 for v in views)


# --- the heartbeat does not depend on the shared thread pool -------------------------------


def test_the_heartbeat_flush_does_not_queue_behind_a_saturated_default_executor(
    db: Database,
) -> None:
    registry = HeartbeatRegistry()

    async def scenario() -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        release = threading.Event()
        # a long ARC / AVO step holding the only thread of the shared pool
        blocker = loop.run_in_executor(None, release.wait)
        task = asyncio.create_task(
            heartbeat_loop(db, registry=registry, interval_seconds=0.05, worker_id="w")
        )
        await _REAL_SLEEP(0.4)
        status = read_worker_status(db)
        release.set()
        await blocker
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return status

    status = asyncio.run(scenario())

    assert status["status"] == "alive", "the heartbeat must keep flushing while the pool is busy"


def test_the_heartbeat_flush_runs_on_its_own_named_thread(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    names: list[str] = []
    real = heartbeat.flush_heartbeat

    def spy(*args: Any, **kwargs: Any) -> bool:
        names.append(threading.current_thread().name)
        return real(*args, **kwargs)

    monkeypatch.setattr(heartbeat, "flush_heartbeat", spy)

    async def scenario() -> None:
        task = asyncio.create_task(
            heartbeat_loop(db, registry=HeartbeatRegistry(), interval_seconds=0.05, worker_id="w")
        )
        await _REAL_SLEEP(0.2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())

    assert names and all(name.startswith("hypertrade-heartbeat") for name in names)


# --- main() runs the watchdog ---------------------------------------------------------------


class _SpyWatchdog:
    events: list[str] = []

    def __init__(self, registry: Any) -> None:
        pass

    def start(self, loop: Any = None) -> None:
        _SpyWatchdog.events.append("start")

    def stop(self) -> None:
        _SpyWatchdog.events.append("stop")


def _main_with(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, loops: Any) -> None:
    _SpyWatchdog.events = []
    settings = Settings(DEEPSEEK_API_KEY="", DATABASE_URL=f"sqlite:///{tmp_path}/main.db")
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "LoopWatchdog", _SpyWatchdog)
    monkeypatch.setattr(worker, "build_loops", loops)


def test_main_starts_the_watchdog_and_stops_it_when_the_loops_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def finished() -> None:
        return None

    _main_with(monkeypatch, tmp_path, lambda db, settings: [("done", finished)])

    asyncio.run(worker.main())

    assert _SpyWatchdog.events == ["start", "stop"]


def test_main_stops_the_watchdog_even_when_building_the_loops_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(db: Database, settings: Settings) -> list[Any]:
        raise RuntimeError("bad configuration")

    _main_with(monkeypatch, tmp_path, broken)

    with pytest.raises(RuntimeError, match="bad configuration"):
        asyncio.run(worker.main())

    assert _SpyWatchdog.events == ["start", "stop"]
