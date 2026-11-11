"""Loop watchdog: it names the call that blocks the worker's event loop, and the heartbeat that
reports it is not itself held up by the pool the blocking work shares."""

import asyncio
import ctypes
import gc
import json
import re
import sys
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hypertrade import worker
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.runtime import heartbeat, loop_watchdog
from hypertrade.runtime.heartbeat import (
    HeartbeatRegistry,
    WorkerHeartbeat,
    flush_heartbeat,
    heartbeat_loop,
    read_worker_status,
)
from hypertrade.runtime.loop_watchdog import LoopWatchdog, _Episode, format_stack
from hypertrade.runtime.stall_evidence import GC_PAUSES, Counters, Dump

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


# --- why the loop stalled: the evidence ----------------------------------------------------
#
# In production the loop thread was parked at a different harmless place each time (an idle
# select, socket.gethostname()) for ~10 s: a victim. These tests make the real culprits (a thread
# holding the GIL, a long collection, a host that does not run the process) and check that the
# watchdog names them.

LINUX_THREAD_CLOCKS = sys.platform.startswith("linux")
ALL_CAUSES = {
    "gc",
    "loop_busy",
    "cpu_starved",
    "other_thread",
    "cpu_contention",
    "busy_pool",
    "native_threads",
    "host_pressure",
    "no_cpu",
    "loop_blocked",
    "unknown",
}

_libc = ctypes.PyDLL(None)  # unlike ctypes.CDLL, a call through a PyDLL keeps the GIL


class _Timespec(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]


def holds_the_gil(seconds: float) -> None:
    """One C call that keeps the GIL for ``seconds``: the loop and the watchdog both wait."""
    whole = int(seconds)
    spec = _Timespec(whole, int((seconds - whole) * 1e9))
    _libc.nanosleep(ctypes.byref(spec), None)


def start_gil_holder(seconds: float, release: threading.Event) -> threading.Thread:
    def gil_holder() -> None:
        holds_the_gil(seconds)
        release.wait(10)  # stay alive: its stack can still be sampled and its CPU still read

    thread = threading.Thread(target=gil_holder, name="gil-holder", daemon=True)
    thread.start()
    return thread


def _spin_count(seconds: float) -> int:
    """How many items ``sum(range(n))`` has to add up to take about ``seconds``."""
    started = time.perf_counter()
    sum(range(4_000_000))
    return int(4_000_000 * seconds / (time.perf_counter() - started))


def _stall_seconds(registry: HeartbeatRegistry) -> float:
    stall, _ = registry.stall_snapshot()
    assert stall is not None
    return float(stall["seconds"])


def _evidence(registry: HeartbeatRegistry) -> dict[str, Any]:
    stall, total = registry.stall_snapshot()
    assert total == 1 and stall is not None, (stall, total)
    return stall["evidence"]  # type: ignore[no-any-return]


def test_a_thread_holding_the_gil_is_named_by_a_dump_taken_during_the_stall() -> None:
    registry = HeartbeatRegistry()
    release = threading.Event()

    async def scenario() -> None:
        await _REAL_SLEEP(0.2)
        start_gil_holder(1.2, release)
        await _REAL_SLEEP(2.0)
        release.set()

    asyncio.run(_watched(registry, scenario))

    stall, total = registry.stall_snapshot()
    assert total == 1 and stall is not None, "the loop catching up first must not hide the stall"
    assert stall["seconds"] >= 0.9
    evidence = stall["evidence"]
    assert evidence["scope"] == "process", "the watchdog thread itself was held up"
    assert evidence["stack_source"] == "dump", "taken during the stall, not after it"
    holder = [t for t in evidence["threads"] if t["name"] == "gil-holder"]
    assert holder, evidence["threads"]
    assert holder[0]["stack"][0].endswith(" holds_the_gil") and "loop" not in holder[0]
    assert evidence["threads"][0]["loop"] is True, "the loop thread is marked"
    assert registry.stall_causes() == {evidence["cause"]: 1}


def test_a_thread_burning_cpu_inside_a_c_call_is_the_cause() -> None:
    registry = HeartbeatRegistry()
    spins = _spin_count(1.2)
    release = threading.Event()

    def cpu_hog() -> None:
        sum(range(spins))  # one C call: the GIL is held until it returns
        release.wait(10)  # a pool thread outlives its job

    async def scenario() -> None:
        await _REAL_SLEEP(0.2)
        threading.Thread(target=cpu_hog, name="cpu-hog", daemon=True).start()
        await _REAL_SLEEP(2.0)
        release.set()

    asyncio.run(_watched(registry, scenario))

    evidence = _evidence(registry)
    assert evidence["scope"] == "process" and evidence["stack_source"] == "dump"
    hog = [t for t in evidence["threads"] if t["name"] == "cpu-hog"]
    assert hog and hog[0]["stack"][0].endswith(" cpu_hog"), evidence["threads"]
    if LINUX_THREAD_CLOCKS:  # per-thread CPU time exists only on Linux (the production host)
        stall_seconds = _stall_seconds(registry)
        # a machine that is loaded (CI) gives the hog only part of a core, but still far more
        # than the loop thread, which waits for the GIL
        assert hog[0]["cpu_seconds"] >= 0.1
        assert evidence["threads"][0]["cpu_seconds"] < hog[0]["cpu_seconds"]
        # a loaded machine (CI) may give the hog well under a full core; the verdict needs half
        # of the stall (tests/test_stall_evidence.py pins the thresholds)
        if hog[0]["cpu_seconds"] >= 0.6 * stall_seconds:
            assert evidence["cause"] == "other_thread"
    else:
        assert evidence["cause"] == "unknown" and "cpu_seconds" not in hog[0]


class _SlowFinalizer:
    def __init__(self) -> None:
        self.cycle = self  # only the collector can free it

    def __del__(self) -> None:
        time.sleep(0.8)  # a long collection: the finalizer runs inside it


def test_a_long_garbage_collection_is_reported_with_its_pause() -> None:
    registry = HeartbeatRegistry()

    async def scenario() -> None:
        await _REAL_SLEEP(0.2)
        _SlowFinalizer()
        gc.collect()
        await _REAL_SLEEP(0.3)

    asyncio.run(_watched(registry, scenario))

    evidence = _evidence(registry)
    assert evidence["cause"] == "gc"
    assert evidence["gc"]["pause_seconds"] >= 0.7 and evidence["gc"]["max_pause_seconds"] >= 0.7
    assert evidence["gc"]["collections"] >= 1
    assert registry.stall_causes() == {"gc": 1}


def test_a_loop_blocked_in_a_call_is_a_loop_scope_stall_that_names_the_call() -> None:
    registry = HeartbeatRegistry()

    async def scenario() -> None:
        await _REAL_SLEEP(0.2)
        blocked_here(1.0)
        await _REAL_SLEEP(0.3)

    asyncio.run(_watched(registry, scenario))

    evidence = _evidence(registry)
    assert evidence["scope"] == "loop", "the watchdog kept running; only the loop did not answer"
    assert evidence["stack_source"] == "sample"
    loop_thread = evidence["threads"][0]
    assert loop_thread["loop"] is True and "blocked_here" in loop_thread["stack"][0]
    host = evidence["host"]
    pressured = host.get("steal_seconds", 0.0) >= 0.2 or any(
        host.get(f"{kind}_pressure_seconds", 0.0) >= 0.5 for kind in ("cpu", "memory", "io")
    )
    if pressured:  # a machine that is itself overloaded (CI) rightly says so
        assert evidence["cause"] in {"loop_blocked", "host_pressure"}
    else:
        assert evidence["cause"] == ("loop_blocked" if LINUX_THREAD_CLOCKS else "unknown")
    assert evidence["window_seconds"] >= 1.0


def test_a_hold_shorter_than_the_threshold_is_not_a_stall() -> None:
    registry = HeartbeatRegistry()

    async def scenario() -> None:
        await _REAL_SLEEP(0.2)
        holds_the_gil(0.1)  # the watchdog is late, but nowhere near the threshold (0.3 s)
        await _REAL_SLEEP(0.3)

    asyncio.run(_watched(registry, scenario))

    assert registry.stall_snapshot() == (None, 0) and registry.stall_causes() == {}


def test_the_stack_dump_is_due_before_a_stall_can_end() -> None:
    # The dump fires after this long without a poll. It has to be shorter than the time that makes
    # a stall (the threshold, poll included), or a hold-up just over the threshold is a stall
    # whose culprit nobody dumped.
    async def scenario() -> None:
        for threshold, poll in ((3.0, 0.5), (0.3, 0.05)):  # production's, and the tests'
            dog = LoopWatchdog(HeartbeatRegistry(), threshold_seconds=threshold, poll_seconds=poll)
            dog.start()
            try:
                assert dog._dump is not None
                assert dog._dump.timeout == pytest.approx(threshold - 2 * poll)
                assert dog._dump.timeout + poll < threshold
            finally:
                dog.stop()

    asyncio.run(scenario())


def test_a_hold_just_over_the_threshold_still_gets_a_stack_dump() -> None:
    registry = HeartbeatRegistry()
    release = threading.Event()

    async def scenario() -> None:
        await _REAL_SLEEP(0.2)
        start_gil_holder(0.31, release)  # 0.3 s is the threshold; the old dump timeout was 0.35 s
        await _REAL_SLEEP(1.0)
        release.set()

    asyncio.run(_watched(registry, scenario))

    evidence = _evidence(registry)
    assert evidence["scope"] == "process" and evidence["stack_source"] == "dump"
    assert any(t["name"] == "gil-holder" for t in evidence["threads"])


def test_reading_the_counters_never_makes_the_watchdog_late() -> None:
    # Each reading gives the GIL away a dozen times, which under load takes seconds: done on the
    # watchdog thread it would make the watchdog late, and a late watchdog is a stall.
    registry = HeartbeatRegistry()

    def slow() -> Counters:
        time.sleep(0.5)  # longer than the 0.3 s threshold
        return Counters(taken=time.monotonic())

    async def scenario() -> None:
        dog = _scripted(registry, slow)
        dog.start()
        try:
            for _ in range(32):  # 1.6 s of a healthy loop
                await _REAL_SLEEP(0.05)
        finally:
            dog.stop()

    asyncio.run(scenario())

    assert registry.stall_snapshot() == (None, 0)


def test_the_counters_are_read_on_a_thread_of_their_own() -> None:
    readers: set[str] = set()

    def probe() -> Counters:
        readers.add(threading.current_thread().name)
        time.sleep(0.15)  # the sampler is nearly always inside a reading, as under load
        return Counters(taken=time.monotonic())

    async def scenario() -> None:
        dog = _scripted(HeartbeatRegistry(), probe)
        dog.start()
        try:
            await _REAL_SLEEP(0.4)
            alive = {t.name for t in threading.enumerate()}
            assert {"loop-watchdog", "loop-watchdog-sampler"} <= alive
        finally:
            dog.stop()
        # stop() waits for both threads: nothing of the watchdog is left running behind it
        assert not {t.name for t in threading.enumerate()} & {
            "loop-watchdog",
            "loop-watchdog-sampler",
        }

    asyncio.run(scenario())

    assert readers == {"loop-watchdog-sampler"}


def test_a_failing_reading_does_not_end_the_sampler() -> None:
    readings: list[int] = []
    dog = _watchdog(HeartbeatRegistry())

    def flaky() -> None:
        readings.append(1)
        if len(readings) <= 2:
            raise RuntimeError("a reading that failed")

    dog._remember = flaky  # type: ignore[method-assign]

    async def scenario() -> None:
        dog.start()
        try:
            await _REAL_SLEEP(0.5)  # ten polls' worth of sampler turns
            assert dog._sampler is not None and dog._sampler.is_alive()
        finally:
            dog.stop()

    asyncio.run(scenario())

    assert len(readings) > 3, "the sampler went on after the first failures"


def test_a_watchdog_that_does_not_stop_in_time_leaves_its_dump_armed_not_closed() -> None:
    loop = asyncio.new_event_loop()
    dog = _watchdog(HeartbeatRegistry())
    release = threading.Event()
    dog._poll_once = lambda: release.wait(10)  # type: ignore[method-assign]
    dog._stop_join = 0.1
    try:
        dog.start(loop)
        dump = dog._dump
        assert dump is not None
        time.sleep(0.3)  # the watchdog thread is inside a poll that does not return

        dog.stop()

        assert dog._thread is not None and dog._thread.is_alive()
        assert dump.active, "closing the file under a poll that may re-arm it could reuse the fd"
    finally:
        release.set()
        if dog._thread is not None:
            dog._thread.join(timeout=2.0)
        if dump is not None:
            dump.close()
        loop.close()


class _Script:
    """Counters that change only as the test says: what the CPU, a thread and the host did."""

    def __init__(self, *threads: int) -> None:
        self.cpu_rate: dict[int, float] = {}
        self.process_rate = 0.0
        self.steal_rate = 0.0
        # every thread the test cares about is in each reading, at zero until it is made to burn,
        # as the real probe lists every thread
        self._cpu: dict[int, float] = dict.fromkeys(threads, 0.0)
        self._process = 0.0
        self._steal = 0.0
        self._last = time.monotonic()

    def __call__(self) -> Counters:
        now = time.monotonic()
        elapsed, self._last = now - self._last, now
        for ident, rate in self.cpu_rate.items():
            self._cpu[ident] = self._cpu.get(ident, 0.0) + rate * elapsed
        self._process += self.process_rate * elapsed
        self._steal += self.steal_rate * elapsed
        return Counters(
            taken=now,
            process_cpu=self._process,
            thread_cpu=dict(self._cpu),
            host={"steal_seconds": self._steal},
        )


def _scripted(registry: HeartbeatRegistry, script: Callable[[], Counters]) -> LoopWatchdog:
    return LoopWatchdog(
        registry,
        threshold_seconds=0.3,
        poll_seconds=0.05,
        resample_seconds=0.4,
        counters=script,
    )


def test_the_busiest_thread_is_named_and_the_stall_is_blamed_on_it() -> None:
    registry = HeartbeatRegistry()
    parked = threading.Event()
    busy = threading.Thread(target=parked.wait, name="busy-pool-thread", daemon=True)
    quiet = threading.Thread(target=parked.wait, name="quiet-pool-thread", daemon=True)
    busy.start()
    quiet.start()
    assert busy.ident is not None and quiet.ident is not None
    script = _Script(threading.get_ident(), busy.ident, quiet.ident)

    async def scenario() -> None:
        dog = _scripted(registry, script)
        dog.start()
        try:
            await _REAL_SLEEP(0.2)
            assert busy.ident is not None
            script.cpu_rate = {busy.ident: 1.0}  # it burns a core while the loop is blocked
            script.process_rate = 1.0
            blocked_here(1.0)
            script.cpu_rate, script.process_rate = {}, 0.0
            await _REAL_SLEEP(0.3)
        finally:
            dog.stop()
            parked.set()

    asyncio.run(scenario())

    evidence = _evidence(registry)
    # the watchdog kept running, so the busy thread did not hold the GIL: the loop is not blamed
    # on it ("other_thread"), only reported as having stalled while the pool was busy
    assert evidence["cause"] == "busy_pool" and evidence["scope"] == "loop"
    names = [t["name"] for t in evidence["threads"]]
    assert names[0] == "MainThread" and "busy-pool-thread" in names
    assert "quiet-pool-thread" not in names, "only threads that used CPU are named"
    culprit = evidence["threads"][names.index("busy-pool-thread")]
    assert 0.6 <= culprit["cpu_seconds"] <= 1.6


def test_a_process_that_did_not_run_is_reported_with_the_hosts_numbers() -> None:
    registry = HeartbeatRegistry()
    script = _Script()
    release = threading.Event()

    async def scenario() -> None:
        dog = _scripted(registry, script)
        dog.start()
        try:
            await _REAL_SLEEP(0.2)
            script.steal_rate = 0.5  # the hypervisor took half of the time; nothing used CPU
            start_gil_holder(1.0, release)
            await _REAL_SLEEP(1.8)
            script.steal_rate = 0.0
        finally:
            release.set()
            dog.stop()

    asyncio.run(scenario())

    evidence = _evidence(registry)
    assert evidence["cause"] == "host_pressure" and evidence["scope"] == "process"
    assert evidence["cpu"]["process_seconds"] < 0.2
    assert 0.3 <= evidence["host"]["steal_seconds"] <= 1.0


def test_a_process_that_did_not_run_and_no_host_counter_says_why_is_no_cpu() -> None:
    registry = HeartbeatRegistry()
    script = _Script()
    release = threading.Event()

    async def scenario() -> None:
        dog = _scripted(registry, script)
        dog.start()
        try:
            await _REAL_SLEEP(0.2)
            start_gil_holder(1.0, release)  # holds the GIL and waits: no CPU used, no steal
            await _REAL_SLEEP(1.8)
        finally:
            release.set()
            dog.stop()

    asyncio.run(scenario())

    evidence = _evidence(registry)
    assert evidence["cause"] == "no_cpu" and evidence["scope"] == "process"
    holder = [t for t in evidence["threads"] if t["name"] == "gil-holder"]
    assert holder and holder[0]["stack"][0].endswith(" holds_the_gil"), (
        "the stack names a GIL holder that waits without using the CPU"
    )


def test_causes_are_counted_per_stall() -> None:
    registry = HeartbeatRegistry()
    script = _Script()

    async def scenario() -> None:
        dog = _scripted(registry, script)
        dog.start()
        try:
            await _REAL_SLEEP(0.2)
            for _ in range(2):
                blocked_here(0.7)
                await _REAL_SLEEP(0.4)
        finally:
            dog.stop()

    asyncio.run(scenario())

    assert registry.stall_snapshot()[1] == 2
    causes = registry.stall_causes()
    assert sum(causes.values()) == 2, "every finished stall is counted once, under its cause"
    # the script gave no per-thread CPU, so "unknown" on a quiet machine; an overloaded one (CI)
    # may rightly have its own say about one of them
    assert set(causes) <= ALL_CAUSES


def test_a_failing_counter_source_does_not_hide_the_stall_or_stop_the_watchdog() -> None:
    registry = HeartbeatRegistry()

    def broken() -> Counters:
        raise OSError("/proc is gone")

    async def scenario() -> None:
        dog = _scripted(registry, broken)
        dog.start()
        try:
            await _REAL_SLEEP(0.2)
            blocked_here(0.7)
            await _REAL_SLEEP(0.3)
            blocked_here(0.7)
            await _REAL_SLEEP(0.3)
            assert dog._thread is not None and dog._thread.is_alive()
        finally:
            dog.stop()

    asyncio.run(scenario())

    stall, total = registry.stall_snapshot()
    assert total == 2 and stall is not None and stall["seconds"] >= 0.5
    assert "blocked_here" in stall["stack"][0]
    assert registry.stall_causes() == {"unknown": 2}


def test_an_explanation_that_fails_leaves_the_stall_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = HeartbeatRegistry()

    def broken(**kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("bug in the explanation")

    monkeypatch.setattr(loop_watchdog, "describe_stall", broken)

    async def scenario() -> None:
        await _REAL_SLEEP(0.2)
        blocked_here(0.7)
        await _REAL_SLEEP(0.3)
        blocked_here(0.7)  # the watchdog must still be alive for a second stall
        await _REAL_SLEEP(0.3)

    asyncio.run(_watched(registry, scenario))

    stall, total = registry.stall_snapshot()
    assert total == 2 and stall is not None and "evidence" not in stall
    assert stall["seconds"] >= 0.5 and registry.stall_causes() == {}


def _manual_watchdog(clock: dict[str, float]) -> LoopWatchdog:
    """A watchdog whose polls the test drives by hand, on a clock the test sets."""
    dog = LoopWatchdog(
        HeartbeatRegistry(),
        threshold_seconds=3.0,
        poll_seconds=0.5,
        clock=lambda: clock["t"],
        counters=lambda: Counters(taken=clock["t"]),
        stack_dump=False,
    )
    dog._loop_thread_id = threading.get_ident()
    dog._own_ident = -1
    dog._last_ack = dog._last_poll = clock["t"]
    return dog


def test_the_watchdog_is_held_up_when_it_was_away_for_the_whole_threshold() -> None:
    clock = {"t": 100.0}
    dog = _manual_watchdog(clock)
    dog._last_poll = 100.7

    # the loop has been silent for 3.4 s (a stall) while this thread was away for 2.7 s: it was
    # not held up
    clock["t"] = 103.4
    dog._poll_once()
    assert dog._episode is not None and dog._episode.scope == "loop"
    assert dog._episode.started == pytest.approx(100.0)

    # the next poll comes 3.6 s after the previous one: the watchdog itself was held up
    clock["t"] = 107.0
    dog._poll_once()
    assert dog._episode is not None and dog._episode.scope == "process"

    # a healthy poll ends the episode and publishes its duration
    dog._last_ack = clock["t"]
    clock["t"] = 107.5
    dog._poll_once()
    assert dog._episode is None
    stall, total = dog._registry.stall_snapshot()
    assert total == 1 and stall is not None
    assert stall["seconds"] == pytest.approx(7.0, abs=0.1)


def test_a_hold_up_just_over_the_threshold_is_a_stall_that_was_held_up() -> None:
    # the lateness that makes a stall (the watchdog away for the threshold) is also what makes it
    # process-wide, so a stall found only through the watchdog's own lateness is never "loop"
    clock = {"t": 100.0}
    dog = _manual_watchdog(clock)
    dog._last_ack = 103.1  # the loop caught up before the watchdog looked

    clock["t"] = 103.1
    dog._poll_once()

    assert dog._episode is not None and dog._episode.scope == "process"


class _SlowDump:
    """Stands in for the faulthandler dump: where the watchdog gets held up, mid-poll."""

    timeout = 99.0

    def __init__(self, clock: dict[str, float]) -> None:
        self._clock = clock

    def rearm(self, *, check: bool = True) -> None:
        self._clock["t"] += 3.6


def test_a_hold_up_in_the_middle_of_a_poll_counts_like_one_between_polls() -> None:
    # A thread inside a long GIL-holding call can catch the watchdog in the middle of a poll as
    # easily as asleep between two.
    clock = {"t": 100.0}
    dog = _manual_watchdog(clock)
    dog._dump = _SlowDump(clock)  # type: ignore[assignment]
    clock["t"] = dog._last_ack = 100.5
    dog._poll_once()  # on time and the loop answered: no stall yet, though the poll ends at 104.1
    assert dog._episode is None

    dog._dump = None
    clock["t"] = 104.6  # the next poll: 4.1 s after the previous one started, the loop silent too
    dog._poll_once()

    assert dog._episode is not None and dog._episode.scope == "process"


def test_a_stall_is_explained_while_it_lasts_and_the_final_record_replaces_it() -> None:
    clock = {"t": 100.0}
    dog = _manual_watchdog(clock)
    dog._remember()  # a reading from before the stall
    clock["t"] = 103.6

    dog._poll_once()  # the loop has been silent for 3.6 s

    stall, total = dog._registry.stall_snapshot()
    assert total == 1 and stall is not None
    assert stall["evidence"]["ongoing"] is True, "a hang is explained before it ends"
    assert dog._registry.stall_causes() == {}, "and counted only when it is over"

    dog._last_ack = clock["t"]
    clock["t"] = 104.1
    dog._poll_once()  # the loop answers

    stall, total = dog._registry.stall_snapshot()
    assert total == 1 and stall is not None and "ongoing" not in stall["evidence"]
    assert dog._registry.stall_causes() == {"unknown": 1}


def test_the_baseline_is_the_newest_reading_from_before_the_stall() -> None:
    clock = {"t": 100.0}
    dog = _manual_watchdog(clock)
    assert dog._baseline(100.0) is None, "no reading yet"
    for taken in (90.0, 91.0, 92.0, 93.0):
        dog._history = (*dog._history, Counters(taken=taken))

    assert dog._baseline(92.5) == Counters(taken=92.0)
    assert dog._baseline(93.0) == Counters(taken=93.0)
    assert dog._baseline(200.0) == Counters(taken=93.0)
    assert dog._baseline(50.0) == Counters(taken=90.0), "the oldest there is"


def test_only_the_last_few_readings_are_kept() -> None:
    clock = {"t": 100.0}
    dog = _manual_watchdog(clock)

    for i in range(40):
        clock["t"] = 100.0 + i
        dog._remember()

    assert len(dog._history) == dog._history_len == 3 * 2 + loop_watchdog.HISTORY_MARGIN
    assert dog._history[-1].taken == 139.0


def test_the_watchdogs_own_threads_are_the_observers_and_never_suspects() -> None:
    registry = HeartbeatRegistry()
    dog = _watchdog(registry)
    dog._loop_thread_id, dog._own_ident = 1, 7
    dog._sampler = SimpleNamespace(ident=9)  # type: ignore[assignment]
    base = Counters(taken=0.0, process_cpu=0.0, thread_cpu={1: 0.0, 7: 0.0, 8: 0.0, 9: 0.0})
    now = Counters(taken=10.0, process_cpu=9.0, thread_cpu={1: 0.0, 7: 5.0, 8: 0.2, 9: 4.0})
    names = {1: "MainThread", 7: "loop-watchdog", 8: "pool", 9: "loop-watchdog-sampler"}
    episode = _Episode(started=0.0, base=base, scope="process")
    episode.held = Dump(
        stacks={
            1: ["selectors.py:1 select"],
            7: ["stall_evidence.py:9 read"],
            8: ["x.py:1 f"],
            9: ["stall_evidence.py:3 read"],
        },
        names=names,
    )

    evidence = dog._explain(episode, 10.0, now)

    assert evidence is not None
    assert [t["name"] for t in evidence["threads"]] == ["MainThread", "pool"]
    assert evidence["cause"] != "other_thread", "the observers' own CPU is not the cause"

    # the same when the stacks are the watchdog's own sample and not faulthandler's dump
    sampled = _Episode(started=0.0, base=base, scope="process")
    sampled.stacks = {1: ["a.py:1 f"], 7: ["a.py:2 g"], 8: ["x.py:1 g"], 9: ["a.py:3 h"]}
    sampled.names = names
    evidence = dog._explain(sampled, 10.0, now)
    assert evidence is not None
    assert [t["name"] for t in evidence["threads"]] == ["MainThread", "pool"]


def test_a_failure_while_recording_does_not_end_the_watchdog() -> None:
    registry = HeartbeatRegistry()
    real = registry.note_stall
    failures: list[int] = []

    def flaky(seconds: float, stack: list[str] | None = None, **kwargs: Any) -> None:
        if not failures:
            failures.append(1)
            raise RuntimeError("the registry broke once")
        real(seconds, stack, **kwargs)

    registry.note_stall = flaky  # type: ignore[method-assign]

    async def scenario() -> None:
        await _REAL_SLEEP(0.2)
        blocked_here(0.7)
        await _REAL_SLEEP(0.4)
        blocked_here(0.7)
        await _REAL_SLEEP(0.4)

    asyncio.run(_watched(registry, scenario))

    # the sample that failed is taken again at the next poll, so no stall is lost or uncounted
    assert failures and registry.stall_snapshot()[1] == 2


def test_the_watchdog_installs_the_gc_recorder_and_removes_it_when_it_stops() -> None:
    registry = HeartbeatRegistry()

    async def scenario() -> None:
        dog = _watchdog(registry)
        dog.start()
        assert GC_PAUSES in gc.callbacks
        dog.stop()
        assert GC_PAUSES not in gc.callbacks
        dog.start()  # a watchdog can be started again
        assert gc.callbacks.count(GC_PAUSES) == 1
        dog.stop()
        assert GC_PAUSES not in gc.callbacks

    asyncio.run(scenario())


def test_the_stack_dump_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = HeartbeatRegistry()
    monkeypatch.setenv(loop_watchdog.STACK_DUMP_ENV, "0")
    release = threading.Event()

    async def scenario() -> None:
        dog = _watchdog(registry)
        dog.start()
        try:
            assert dog._dump is None
            await _REAL_SLEEP(0.2)
            start_gil_holder(1.0, release)
            await _REAL_SLEEP(1.8)
        finally:
            release.set()
            dog.stop()

    asyncio.run(scenario())

    evidence = _evidence(registry)
    assert evidence["scope"] == "process" and evidence["stack_source"] == "sample"
    assert not loop_watchdog.stack_dump_enabled()
    monkeypatch.setenv(loop_watchdog.STACK_DUMP_ENV, "1")
    assert loop_watchdog.stack_dump_enabled()
    monkeypatch.delenv(loop_watchdog.STACK_DUMP_ENV)
    assert loop_watchdog.stack_dump_enabled(), "on by default"


# --- what /api/healthz shows of the evidence -----------------------------------------------

EVIDENCE = {
    "cause": "other_thread",
    "scope": "process",
    "window_seconds": 11.1,
    "stack_source": "dump",
    "threads": [
        {"name": "MainThread", "loop": True, "cpu_seconds": 0.01, "stack": ["worker.py:124 once"]},
        {"name": "asyncio_2", "cpu_seconds": 10.4, "stack": ["avo.py:812 run", "thread.py:90 _w"]},
    ],
    "cpu": {"process_seconds": 10.5, "loop_thread_wait_seconds": 0.02},
    "gc": {"collections": 3, "pause_seconds": 0.04},
    "host": {"steal_seconds": 0.0, "major_faults": 0},
}


def test_the_evidence_of_a_stall_reaches_the_healthz_view(db: Database) -> None:
    registry = HeartbeatRegistry()
    registry.note_stall(10.6, ["worker.py:124 once"], new_episode=True, now=T0)
    registry.note_stall(10.8, evidence=EVIDENCE)
    registry.note_stall_cause("other_thread")
    stats = {"cpus": 2, "rss_mb": 812.3, "gc": {"collections": [10, 2, 1]}}
    flush_heartbeat(
        db, worker_id="worker", started_at=T0, registry=registry, now=T0, stats=lambda: stats
    )

    (view,) = read_worker_status(db, now=T0 + timedelta(seconds=60))["instances"]

    assert view["last_stall"] == {
        "seconds": 10.8,
        "age_seconds": 60.0,
        "running": ["worker.py:124 once"],
        **EVIDENCE,
    }
    assert view["stall_causes"] == {"other_thread": 1}
    assert view["process"] == stats
    assert json.loads(json.dumps(view, allow_nan=False)) == view


def test_evidence_attaches_to_the_stall_it_explains_and_not_to_the_next_one() -> None:
    registry = HeartbeatRegistry()
    registry.note_stall(5.0, ["a.py:1 f"], new_episode=True)
    registry.note_stall(5.2, evidence=EVIDENCE)
    registry.note_stall(3.0, ["b.py:2 g"], new_episode=True)  # a new stall: no evidence yet

    stall, total = registry.stall_snapshot()

    assert total == 2 and stall is not None and "evidence" not in stall
    registry.note_stall(3.4, evidence={"cause": "gc"})
    stall, _ = registry.stall_snapshot()
    assert stall is not None and stall["evidence"] == {"cause": "gc"}


def test_evidence_without_a_stall_is_ignored() -> None:
    registry = HeartbeatRegistry()

    registry.note_stall(5.0, evidence=EVIDENCE)

    assert registry.stall_snapshot() == (None, 0)


def test_evidence_is_bounded_when_it_is_stored_and_again_when_it_is_read(db: Database) -> None:
    huge: dict[str, Any] = {
        "cause": "x" * 500,
        "threads": [{"name": "t", "stack": ["f" * 500] * 100} for _ in range(50)],
        "nan": float("nan"),
        "inf": float("inf"),
        "deep": {"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}},
        **{f"key{i}": i for i in range(100)},
    }
    registry = HeartbeatRegistry()
    registry.note_stall(5.0, ["a.py:1 f"], new_episode=True, now=T0)
    registry.note_stall(5.0, evidence=huge)

    stall, _ = registry.stall_snapshot()

    assert stall is not None
    stored = stall["evidence"]
    assert len(stored) <= 16 and len(stored["cause"]) == 160
    assert len(stored["threads"]) == 12 and len(stored["threads"][0]["stack"]) == 12
    assert all(len(frame) == 160 for frame in stored["threads"][0]["stack"])
    assert stored["nan"] is None and stored["inf"] is None
    assert stored["deep"] == {"a": {"b": {"c": None}}}, "nested no deeper than four levels"
    assert len(json.dumps(stored)) < 30_000

    # and whatever a hand-edited row holds is bounded on the way out as well
    with db.session() as session:
        session.add(
            WorkerHeartbeat(
                worker_id="worker",
                started_at=T0,
                heartbeat_at=T0,
                components_json={},
                process_json={
                    "last_stall": {
                        "seconds": 5,
                        "at": T0.isoformat(),
                        "stack": [],
                        "evidence": huge,
                    },
                    "stall_causes": {"gc": 3, "x" * 100: 1, "bad": "many", "worse": True},
                    "process": {"rss_mb": 1.5, "deep": huge},
                },
            )
        )
    (view,) = read_worker_status(db, now=T0 + timedelta(seconds=5))["instances"]
    assert len(view["last_stall"]["cause"]) == 160 and len(view["last_stall"]["threads"]) == 12
    assert view["stall_causes"] == {"gc": 3, "x" * 32: 1, "bad": 0, "worse": 0}
    assert view["process"]["rss_mb"] == 1.5 and len(json.dumps(view["process"])) < 30_000


def test_a_huge_integer_in_a_stored_row_cannot_break_the_endpoint(db: Database) -> None:
    # math.isfinite(10**400) raises OverflowError: one such row used to be a 500 for /api/healthz
    with db.session() as session:
        session.add(
            WorkerHeartbeat(
                worker_id="worker",
                started_at=T0,
                heartbeat_at=T0,
                components_json={},
                process_json={
                    "last_stall": {
                        "seconds": 5,
                        "at": T0.isoformat(),
                        "stack": [],
                        "evidence": {"huge": 10**400, "fine": 3, "edge": 2**63 - 1, "over": 2**63},
                    },
                    "stall_causes": {"gc": 10**400},
                    "process": {"huge": 10**400, "cpus": 2},
                },
            )
        )

    (view,) = read_worker_status(db, now=T0 + timedelta(seconds=5))["instances"]

    last = view["last_stall"]
    assert last["huge"] is None and last["fine"] == 3 and last["edge"] == 2**63 - 1
    assert last["over"] is None, "an integer that is no counter is dropped"
    assert view["process"] == {"huge": None, "cpus": 2}
    assert view["stall_causes"] == {"gc": 0}


def test_a_part_of_a_row_that_cannot_be_read_costs_that_part_not_the_endpoint(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    flush_heartbeat(db, worker_id="worker", started_at=T0, registry=HeartbeatRegistry(), now=T0)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("a bug in a view")

    monkeypatch.setattr(heartbeat, "_stall_view", broken)
    monkeypatch.setattr(heartbeat, "_process_view", broken)
    monkeypatch.setattr(heartbeat, "_counts", broken)

    status = read_worker_status(db, now=T0 + timedelta(seconds=5))

    (view,) = status["instances"]
    assert status["status"] == "alive" and view["stale"] is False
    assert view["last_stall"] is None and view["process"] is None and view["stall_causes"] == {}


def test_the_process_context_is_bounded_when_it_is_written_too(db: Database) -> None:
    flush_heartbeat(
        db,
        worker_id="worker",
        started_at=T0,
        registry=HeartbeatRegistry(),
        now=T0,
        stats=lambda: {"rss_mb": float("nan"), "big": 10**400, "text": "x" * 500},
    )

    (view,) = read_worker_status(db, now=T0 + timedelta(seconds=1))["instances"]
    assert view["process"] == {"rss_mb": None, "big": None, "text": "x" * 160}
    with db.session() as session:  # and the row itself holds nothing a JSON reader would choke on
        stored = session.get(WorkerHeartbeat, "worker")
        assert stored is not None
        assert stored.process_json["process"] == {"rss_mb": None, "big": None, "text": "x" * 160}


def test_evidence_cannot_overwrite_the_fields_a_stall_always_has(db: Database) -> None:
    with db.session() as session:
        session.add(
            WorkerHeartbeat(
                worker_id="worker",
                started_at=T0,
                heartbeat_at=T0,
                components_json={},
                process_json={
                    "last_stall": {
                        "seconds": 5,
                        "at": T0.isoformat(),
                        "stack": ["a.py:1 f"],
                        "evidence": {"seconds": 999, "running": ["fake"], "age_seconds": -1},
                    }
                },
            )
        )

    (view,) = read_worker_status(db, now=T0 + timedelta(seconds=7))["instances"]

    assert view["last_stall"] == {"seconds": 5, "age_seconds": 7.0, "running": ["a.py:1 f"]}


def test_the_stall_causes_are_few_and_short() -> None:
    registry = HeartbeatRegistry()
    registry.note_stall_cause("y" * 100)
    for i in range(40):
        registry.note_stall_cause(f"cause-{i}")
    registry.note_stall_cause("cause-0")

    causes = registry.stall_causes()

    assert "y" * 32 in causes and "y" * 100 not in causes, "a name is cut to 32 characters"
    assert len(causes) == 16 and causes["cause-0"] == 2
    assert "cause-39" not in causes, "a new cause beyond the 16th is dropped"
    registry.note_stall_cause("cause-1")
    assert registry.stall_causes()["cause-1"] == 2, "a known cause keeps counting"


def test_booleans_and_null_pass_through_the_evidence_sanitizer(db: Database) -> None:
    registry = HeartbeatRegistry()
    registry.note_stall(5.0, ["a.py:1 f"], new_episode=True, now=T0)
    registry.note_stall(5.0, evidence={"flag": True, "off": False, "none": None, "n": 0})

    stall, _ = registry.stall_snapshot()

    assert stall is not None
    stored = stall["evidence"]
    assert stored == {"flag": True, "off": False, "none": None, "n": 0}
    assert stored["flag"] is True and stored["off"] is False


def test_a_failing_process_statistic_does_not_stop_the_heartbeat(db: Database) -> None:
    registry = HeartbeatRegistry()

    def broken() -> dict[str, Any]:
        raise OSError("no /proc")

    assert flush_heartbeat(
        db, worker_id="worker", started_at=T0, registry=registry, now=T0, stats=broken
    )

    (view,) = read_worker_status(db, now=T0 + timedelta(seconds=1))["instances"]
    assert view["process"] is None and view["stall_causes"] == {}


def test_a_heartbeat_row_from_an_older_worker_has_empty_evidence_fields(db: Database) -> None:
    with db.session() as session:
        session.add(
            WorkerHeartbeat(
                worker_id="worker",
                started_at=T0,
                heartbeat_at=T0,
                components_json={},
                process_json={"event_loop_lag_max_seconds": 1.0, "stalls_total": 3},
            )
        )

    (view,) = read_worker_status(db, now=T0 + timedelta(seconds=1))["instances"]

    assert view["stall_causes"] == {} and view["process"] is None and view["last_stall"] is None
    assert view["stalls_total"] == 3


def test_the_real_process_statistics_are_what_the_heartbeat_publishes(db: Database) -> None:
    flush_heartbeat(db, worker_id="worker", started_at=T0, registry=HeartbeatRegistry(), now=T0)

    (view,) = read_worker_status(db, now=T0 + timedelta(seconds=1))["instances"]

    assert set(view["process"]["gc"]) == {
        "collections",
        "pause_seconds",
        "max_pause_seconds",
        "threshold",
    }
    assert view["process"]["cpus"] >= 1 and view["process"]["threads"] >= 1
    assert view["process"]["python"]
