"""Loop supervisor: a crashed worker loop restarts alone, with backoff; the process survives."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from hypertrade import worker
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.runtime.loop_supervisor import supervise


class _Done(BaseException):
    """Ends the endless supervisor from inside a factory (it escapes `except Exception`)."""


class FakeTime:
    """Virtual clock: sleeping advances time instantly, so no test ever waits."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)  # let sibling loops run, as a real sleep would


def _run(
    factory: Callable[[], Awaitable[None]], fake: FakeTime, **kwargs: Any
) -> None:
    asyncio.run(
        supervise(
            "demo",
            factory,
            sleep=fake.sleep,
            clock=fake.clock,
            rng=random.Random(7),
            **kwargs,
        )
    )


def test_crashing_loop_restarts_with_growing_jittered_delays() -> None:
    fake, calls = FakeTime(), 0

    async def factory() -> None:
        nonlocal calls
        calls += 1
        if calls <= 4:
            raise RuntimeError("boom")
        raise _Done

    with pytest.raises(_Done):
        _run(factory, fake)

    assert calls == 5 and len(fake.sleeps) == 4
    for crash, delay in enumerate(fake.sleeps, start=1):
        target = 2 ** (crash - 1)  # 1, 2, 4, 8 seconds, +-20% jitter
        assert target * 0.8 <= delay <= target * 1.2
    assert fake.sleeps == sorted(fake.sleeps)


def test_restart_delay_is_capped() -> None:
    fake, calls = FakeTime(), 0

    async def factory() -> None:
        nonlocal calls
        calls += 1
        if calls <= 12:
            raise RuntimeError("fails on every start")
        raise _Done

    with pytest.raises(_Done):
        _run(factory, fake, max_delay=30.0)

    assert max(fake.sleeps) <= 30.0
    assert fake.sleeps[-1] >= 30.0 * 0.8, "the delay should settle at the cap, not keep growing"


def test_a_long_healthy_run_resets_the_backoff() -> None:
    fake, calls = FakeTime(), 0

    async def factory() -> None:
        nonlocal calls
        calls += 1
        if calls in (1, 2):
            fake.now += 10  # dies quickly twice: the second delay doubles
            raise RuntimeError("early crash")
        if calls == 3:
            fake.now += 400  # was healthy for longer than healthy_after, then hit one error
            raise RuntimeError("late transient error")
        raise _Done

    with pytest.raises(_Done):
        _run(factory, fake, healthy_after=300.0)

    first, second, third = fake.sleeps
    assert 0.8 <= first <= 1.2
    assert 1.6 <= second <= 2.4
    assert 0.8 <= third <= 1.2, "a loop that ran for 400s must restart like a first failure"


def test_cancellation_is_never_swallowed_or_restarted() -> None:
    fake, calls = FakeTime(), 0

    async def factory() -> None:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        _run(factory, fake)

    assert calls == 1 and fake.sleeps == []


def test_a_loop_that_returns_is_left_stopped() -> None:
    fake, calls = FakeTime(), 0

    async def factory() -> None:
        nonlocal calls
        calls += 1

    _run(factory, fake)

    assert calls == 1 and fake.sleeps == []


def test_crash_is_journalled_and_reported_to_the_observer() -> None:
    fake, calls = FakeTime(), 0
    journalled: list[tuple[str, str]] = []
    observed: list[tuple[str, str]] = []

    async def journal(component: str, exc: Exception) -> None:
        journalled.append((component, str(exc)))

    async def factory() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        raise _Done

    with pytest.raises(_Done):
        _run(
            factory,
            fake,
            journal=journal,
            on_crash=lambda name, exc: observed.append((name, str(exc))),
        )

    assert journalled == [("worker.crash.demo", "boom")]
    assert observed == [("demo", "boom")]


def test_a_failing_journal_or_observer_never_stops_the_restart() -> None:
    fake, calls = FakeTime(), 0

    async def broken_journal(component: str, exc: Exception) -> None:
        raise RuntimeError("journal database is down")

    def broken_observer(name: str, exc: Exception) -> None:
        raise RuntimeError("observer is broken")

    async def factory() -> None:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise RuntimeError("boom")
        raise _Done

    with pytest.raises(_Done):
        _run(factory, fake, journal=broken_journal, on_crash=broken_observer)

    assert calls == 3 and len(fake.sleeps) == 2


def test_siblings_keep_running_while_one_loop_crashes() -> None:
    fake = FakeTime()
    ticks = 0
    crasher_calls = 0

    async def healthy() -> None:
        nonlocal ticks
        while ticks < 6:
            ticks += 1
            await asyncio.sleep(0)

    async def crasher() -> None:
        nonlocal crasher_calls
        crasher_calls += 1
        if crasher_calls <= 3:
            raise RuntimeError("boom")

    async def scenario() -> None:
        await asyncio.gather(
            supervise("healthy", healthy, sleep=fake.sleep, clock=fake.clock),
            supervise("crasher", crasher, sleep=fake.sleep, clock=fake.clock),
        )

    asyncio.run(scenario())  # would raise RuntimeError("boom") under a bare gather

    assert ticks == 6 and crasher_calls == 4


def test_without_supervision_one_crash_ends_the_gather() -> None:
    # The behaviour the supervisor replaces: kept as a test so the reason it exists is visible.
    async def crasher() -> None:
        raise RuntimeError("boom")

    async def scenario() -> None:
        await asyncio.gather(crasher(), asyncio.sleep(0))

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(scenario())


# --- the loops the worker hands to the supervisor -------------------------------------------

_ALL_OFF = {
    "PAPER_ENABLED": False,
    "MONITOR_SCHEDULER_ENABLED": False,
    "AGENT_TASK_WORKER_ENABLED": False,
    "MISSION_RUNTIME_ENABLED": False,
    "MISSION_RUNTIME_WORKER_ENABLED": False,
    "RESEARCH_TRIGGERS_ENABLED": False,
    "AUTONOMOUS_PULSE_ENABLED": False,
    "ARC_PAPER_EFFECT_RECONCILE_ENABLED": False,
    "SELF_HEALING_EVOLUTION_ENABLED": False,
    "RACE_JUDGE_ENABLED": False,
    "ARC_MEMORY_DISTILLATION_ENABLED": False,
}


def _loops(**overrides: Any) -> list[tuple[str, Any]]:
    settings = Settings(DEEPSEEK_API_KEY="", **{**_ALL_OFF, **overrides})
    return worker.build_loops(Database("sqlite:///:memory:"), settings)


def test_core_loops_always_run() -> None:
    assert [name for name, _ in _loops()] == [
        "rag_scanner",
        "market_ingestion",
        "market_rest_supplement",
        "arc_observation",
        "arc_evolution",
        "arc_auto_review",
        "arc_meta_tuning",
        "cognitive_memory_replay",
        "heartbeat",
    ]


def test_optional_loops_follow_their_settings() -> None:
    names = [
        name
        for name, _ in _loops(
            PAPER_ENABLED=True,
            MONITOR_SCHEDULER_ENABLED=True,
            AGENT_TASK_WORKER_ENABLED=True,
            RACE_JUDGE_ENABLED=True,
            ARC_MEMORY_DISTILLATION_ENABLED=True,
        )
    ]
    for expected in (
        "paper_trading",
        "monitor_scheduler",
        "agent_task_worker",
        "race_judge",
        "memory_distillation",
    ):
        assert expected in names


def test_mission_workers_follow_concurrency_and_the_full_cutover_rule() -> None:
    names = [
        name
        for name, _ in _loops(
            MISSION_RUNTIME_ENABLED=True,
            MISSION_RUNTIME_WORKER_ENABLED=True,
            MISSION_RUNTIME_WORKER_CONCURRENCY=3,
            AGENT_TASK_WORKER_ENABLED=True,
            RESEARCH_TRIGGERS_ENABLED=True,
        )
    ]
    assert [n for n in names if n.startswith("mission_worker")] == [
        "mission_worker_1",
        "mission_worker_2",
        "mission_worker_3",
    ]
    assert "avo_research" in names
    assert "agent_task_worker" in names and "research_trigger" in names

    cutover = [
        name
        for name, _ in _loops(
            MISSION_RUNTIME_ENABLED=True,
            MISSION_RUNTIME_WORKER_ENABLED=True,
            MISSION_RUNTIME_CANARY_PERCENT=100,
            AGENT_TASK_WORKER_ENABLED=True,
            RESEARCH_TRIGGERS_ENABLED=True,
        )
    ]
    assert "agent_task_worker" not in cutover and "research_trigger" not in cutover


def test_loop_names_are_unique_with_everything_enabled() -> None:
    everything = dict.fromkeys(_ALL_OFF, True)
    names = [name for name, _ in _loops(**everything, MISSION_RUNTIME_WORKER_CONCURRENCY=2)]
    assert len(names) == len(set(names))


def test_main_runs_every_loop_under_the_supervisor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    calls = {"bad": 0, "good": 0}
    journalled: list[str] = []

    async def bad() -> None:
        calls["bad"] += 1
        if calls["bad"] <= 2:
            raise RuntimeError("boom")

    async def good() -> None:
        calls["good"] += 1

    async def fake_journal(db: Database, component: str, exc: Exception, **kwargs: Any) -> None:
        journalled.append(component)

    real_sleep = asyncio.sleep

    async def instant(_seconds: float) -> None:
        await real_sleep(0)

    settings = Settings(DEEPSEEK_API_KEY="", DATABASE_URL=f"sqlite:///{tmp_path}/main.db")
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "build_loops", lambda db, s: [("bad", bad), ("good", good)])
    monkeypatch.setattr(worker, "_journal", fake_journal)
    monkeypatch.setattr(asyncio, "sleep", instant)

    asyncio.run(worker.main())  # a bare gather would raise RuntimeError("boom") here

    assert calls == {"bad": 3, "good": 1}
    assert journalled == ["worker.crash.bad", "worker.crash.bad"]


def test_each_factory_builds_a_fresh_coroutine_and_resolves_the_loop_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[Database] = []

    async def fake_rag_loop(db: Database) -> None:
        built.append(db)

    monkeypatch.setattr(worker, "rag_scanner_loop", fake_rag_loop)
    factory = dict(_loops())["rag_scanner"]

    first, second = factory(), factory()
    assert first is not second, "a coroutine can only be awaited once; restarts need new ones"

    async def run_both() -> None:
        await first
        await second

    asyncio.run(run_both())
    assert len(built) == 2
