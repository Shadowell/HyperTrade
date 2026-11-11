"""Stall evidence: the numbers and code locations that explain a stalled event loop."""

import gc
import json
import linecache
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from hypertrade.runtime import stall_evidence as ev
from hypertrade.runtime.stall_evidence import (
    CounterProbe,
    Counters,
    GcPauseRecorder,
    HeldStackDump,
    Usage,
    classify,
    describe_stall,
    parse_cpu_steal,
    parse_faulthandler_dump,
    parse_pressure,
    parse_schedstat,
    process_stats,
    stack_of,
    thread_cpu_clock,
    usage_between,
)

LINUX = sys.platform.startswith("linux")  # per-thread CPU clocks and /proc exist only there


# --- code locations ------------------------------------------------------------------------


def test_stack_of_never_reads_source_code(monkeypatch: pytest.MonkeyPatch) -> None:
    # `traceback.extract_stack` loads the source line of every frame it walks. Sampling dozens of
    # threads during a stall must neither open source files nor hold source text.
    def forbidden(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("a stack sample must not read source code")

    monkeypatch.setattr(linecache, "getline", forbidden)
    monkeypatch.setattr(linecache, "getlines", forbidden)
    monkeypatch.setattr(linecache, "updatecache", forbidden)

    stack = stack_of(sys._getframe(), limit=4)

    assert len(stack) == 4 and stack[0].endswith(" test_stack_of_never_reads_source_code")


def test_stack_of_is_deepest_first_bounded_and_skips_a_missing_frame() -> None:
    def outer() -> list[str]:
        return inner()

    def inner() -> list[str]:
        return stack_of(sys._getframe(), limit=2)

    stack = outer()

    assert [item.split(" ")[1] for item in stack] == ["inner", "outer"]
    assert stack_of(None) == []


def test_idle_stacks_are_the_waits_of_parked_threads() -> None:
    assert ev.is_idle([])
    assert ev.is_idle(["threading.py:359 wait", "threading.py:1012 run"])
    assert ev.is_idle(["thread.py:90 _worker", "threading.py:1012 run"])
    assert not ev.is_idle(["avo.py:812 run_backtest", "thread.py:90 _worker"])
    assert not ev.is_idle(["worker.py:41 wait"])  # a function called wait elsewhere is not a wait


def test_code_compiled_from_a_string_is_anonymised_in_a_stack() -> None:
    # Strategies the agents write run through exec(); their function names are data and the stack
    # is published, so such frames show where they are, not what they are called.
    scope: dict[str, Any] = {"stack_of": stack_of, "sys": sys}
    source = "def secret_strategy_name():\n    return stack_of(sys._getframe(), limit=3)\n"
    for label in ("<string>", "customer-alpha-strategy-42"):
        exec(compile(source, label, "exec"), scope)  # noqa: S102 - the point of the test
        stack = scope["secret_strategy_name"]()
        assert stack[0] == "<dynamic>:2 <code>", stack
        assert "secret" not in " ".join(stack) and "customer" not in " ".join(stack)
    assert ev._location("<frozen runpy>", 88, "_run_code") == "<frozen runpy>:88 _run_code"
    assert ev._location("<candidate>", 5, "on_bar") == "<dynamic>:5 <code>"
    assert ev._location("/some/dir/<generated>", 3, "f") == "<dynamic>:3 <code>"
    # a console entry point has a directory: it is our code and stays
    assert ev._location("/app/.venv/bin/uvicorn", 8, "<module>") == "uvicorn:8 <module>"
    assert ev._location("/x/asyncio/base_events.py", 1, "f") is None


# --- a faulthandler dump -------------------------------------------------------------------

DUMP_314 = """Timeout (0:00:03.500000)!
Thread 0x000000016f94f000 [asyncio_2] (most recent call first):
  File "/app/backend/src/hypertrade/arc/avo.py", line 812 in run_backtest
  File "/app/backend/src/hypertrade/worker.py", line 51 in step
  File "/usr/lib/python3.14/concurrent/futures/thread.py", line 90 in _worker

Thread 0x00000001ec66ff80 (most recent call first):
  File "/usr/lib/python3.14/selectors.py", line 468 in select
  File "/usr/lib/python3.14/asyncio/base_events.py", line 2012 in _run_once
  File "/app/backend/src/hypertrade/worker.py", line 951 in <module>
"""

DUMP_312 = """Thread 0x00007f4d0f7fe6c0 (most recent call first):
  File "/usr/lib/python3.12/threading.py", line 359 in wait
  <no Python frame>
Current thread 0x00007f4d1a3f1740 (most recent call first):
  File "x.py", line 5 in <lambda>
garbage that is neither
"""


def test_a_faulthandler_dump_is_read_into_stacks_by_thread_ident() -> None:
    dump = parse_faulthandler_dump(DUMP_314)
    stacks = dump.stacks

    assert dump.names == {0x16F94F000: "asyncio_2"}, "only the threads the dump names"
    assert stacks[0x16F94F000] == [
        "avo.py:812 run_backtest",
        "worker.py:51 step",
        "thread.py:90 _worker",
    ]
    # asyncio internals are left out, as in every other stack this module produces
    assert stacks[0x1EC66FF80] == ["selectors.py:468 select", "worker.py:951 <module>"]


def test_generated_code_in_a_dump_is_anonymised_too() -> None:
    dump = parse_faulthandler_dump(
        'Thread 0x1 (most recent call first):\n'
        '  File "<string>", line 3 in on_bar_of_secret_strategy\n'
        '  File "/app/backend/src/hypertrade/backtest/candidate.py", line 328 in run\n'
        '  File "<frozen runpy>", line 88 in _run_code\n'
    )

    assert dump.stacks[1] == [
        "<dynamic>:3 <code>",
        "candidate.py:328 run",
        "<frozen runpy>:88 _run_code",
    ]


def test_older_dump_formats_and_noise_are_tolerated() -> None:
    dump = parse_faulthandler_dump(DUMP_312)

    assert dump.stacks == {
        0x7F4D0F7FE6C0: ["threading.py:359 wait"],
        0x7F4D1A3F1740: ["x.py:5 <lambda>"],
    }
    assert dump.names == {}
    assert parse_faulthandler_dump("").stacks == {}
    assert parse_faulthandler_dump('  File "orphan.py", line 1 in f').stacks == {}  # no thread yet


def test_a_dumped_stack_is_bounded() -> None:
    frames = "".join(f'  File "f{i}.py", line {i} in fn{i}\n' for i in range(40))

    header = "Thread 0x1 (most recent call first):\n"
    (stack,) = parse_faulthandler_dump(header + frames).stacks.values()

    assert len(stack) == ev.THREAD_STACK_FRAMES and stack[0] == "f0.py:0 fn0"


def test_the_dump_fires_only_when_the_timer_is_not_re_armed() -> None:
    dump = HeldStackDump(timeout=0.6)  # generous: a loaded CI machine may delay a re-arm a little
    assert dump.start() and dump.active
    try:
        assert dump.rearm() is None
        # re-armed well inside the timeout, like a healthy watchdog: nothing is ever dumped
        for _ in range(12):
            time.sleep(0.05)
            assert dump.rearm() is None
        time.sleep(1.6)  # the "watchdog" is held up: the C thread dumps every stack
        held = dump.rearm()
        assert dump.rearm() is None, "a dump is reported once, not again at the next poll"
    finally:
        dump.close()

    assert held is not None
    mine = held.stacks[threading.get_ident()]
    assert mine[0].endswith(" test_the_dump_fires_only_when_the_timer_is_not_re_armed")


def test_a_closed_dump_is_inert_and_close_is_idempotent() -> None:
    dump = HeldStackDump(timeout=0.2)
    dump.start()
    dump.rearm()
    dump.close()
    dump.close()

    assert not dump.active
    time.sleep(0.4)  # the timer was cancelled: no dump can arrive any more
    assert dump.rearm() is None


def test_a_dump_is_looked_for_only_when_the_caller_says_one_may_have_fired() -> None:
    dump = HeldStackDump(timeout=0.2)
    assert dump.start()
    try:
        dump.rearm()
        time.sleep(0.6)  # the timer fires
        assert dump.rearm(check=False) is None, "a healthy poll costs no system call"
        held = dump.rearm(check=True)  # the next look still finds it
    finally:
        dump.close()

    assert held is not None and threading.get_ident() in held.stacks


@pytest.mark.skipif(not LINUX, reason="memfd_create is Linux only")
def test_the_dump_goes_to_memory_not_to_a_disk() -> None:
    # faulthandler's cancel holds the GIL while a dump is being written: a write that blocks on a
    # throttled disk would freeze the interpreter during the very IO stalls being studied
    dump = HeldStackDump(timeout=1.0)
    assert dump.start()
    try:
        assert dump._file is not None
        assert os.readlink(f"/proc/self/fd/{dump._file.fileno()}").startswith("/memfd:")
    finally:
        dump.close()


def test_without_memfd_a_temporary_file_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_memfd(name: str) -> int:
        raise OSError("memfd_create is not permitted here")

    monkeypatch.setattr(ev.os, "memfd_create", no_memfd, raising=False)
    dump = HeldStackDump(timeout=0.2)

    assert dump.start() and dump.active
    dump.close()


def test_a_missing_file_turns_the_dump_off(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise OSError("read-only file system")

    monkeypatch.setattr(ev.os, "memfd_create", broken, raising=False)
    monkeypatch.setattr(ev.tempfile, "TemporaryFile", broken)
    dump = HeldStackDump(timeout=0.2)

    assert not dump.start() and not dump.active
    assert dump.rearm() is None


def test_a_failed_re_arm_is_skipped_and_only_a_run_of_them_ends_the_dump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = iter([False] * 4 + [True] + [False] * 4 + [True] + [False] * ev.MAX_DUMP_FAILURES)
    real = ev.faulthandler.dump_traceback_later

    def flaky(*args: Any, **kwargs: Any) -> None:
        if next(results):
            real(*args, **kwargs)
        else:
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(ev.faulthandler, "dump_traceback_later", flaky)
    dump = HeldStackDump(timeout=30.0)
    assert dump.start()
    try:
        for _ in range(4):  # four failures: skipped, the dump is still on
            dump.rearm()
            assert dump.active
        dump.rearm()  # a success starts the count again
        for _ in range(4):
            dump.rearm()
            assert dump.active
        dump.rearm()
        for _ in range(ev.MAX_DUMP_FAILURES):
            dump.rearm()
        assert not dump.active, "a run of failures ends it"
    finally:
        dump.close()


# --- garbage collection --------------------------------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _collect(rec: GcPauseRecorder, clock: _Clock, seconds: float, generation: int) -> None:
    rec("start", {"generation": generation, "collected": 0, "uncollectable": 0})
    clock.now += seconds
    rec("stop", {"generation": generation, "collected": 5, "uncollectable": 0})


def test_every_collection_is_counted_and_timed_per_generation() -> None:
    clock = _Clock()
    rec = GcPauseRecorder(clock=clock)

    _collect(rec, clock, 0.004, 0)
    _collect(rec, clock, 0.010, 0)
    _collect(rec, clock, 9.5, 2)

    assert rec.collections == [2, 0, 1]
    assert rec.pause_total == pytest.approx([0.014, 0.0, 9.5])
    assert rec.pause_max == pytest.approx([0.010, 0.0, 9.5])
    count, seconds = rec.totals()
    assert count == 3 and seconds == pytest.approx(9.514)
    assert rec.summary() == {
        "collections": [2, 0, 1],
        "pause_seconds": [0.01, 0.0, 9.5],
        "max_pause_seconds": [0.01, 0.0, 9.5],
    }


def test_only_slow_collections_are_remembered_and_found_by_time() -> None:
    clock = _Clock()
    rec = GcPauseRecorder(clock=clock)
    _collect(rec, clock, 0.001, 0)  # too quick to remember
    clock.now += 10
    _collect(rec, clock, 2.0, 1)  # ends at 112.001
    clock.now += 10
    _collect(rec, clock, 6.0, 2)  # ends at 128.001

    assert rec.slowest_since(0.0) == pytest.approx((6.0, 2))
    assert rec.slowest_since(120.0) == pytest.approx((6.0, 2))  # only the last one is newer
    assert rec.slowest_since(105.0) == pytest.approx((6.0, 2))
    assert rec.slowest_since(129.0) is None
    only_first = GcPauseRecorder(clock=clock)
    _collect(only_first, clock, 0.001, 0)
    assert only_first.slowest_since(0.0) is None


def test_the_memory_of_slow_collections_is_a_ring() -> None:
    clock = _Clock()
    rec = GcPauseRecorder(clock=clock)
    for _ in range(ev.SLOW_GC_RING + 40):
        _collect(rec, clock, 0.06, 1)
    _collect(rec, clock, 0.5, 2)

    assert len([entry for entry in rec._slow if entry is not None]) == ev.SLOW_GC_RING
    assert rec.slowest_since(0.0) == pytest.approx((0.5, 2))


def test_the_collector_callback_clamps_the_generation_and_never_raises() -> None:
    clock = _Clock()
    rec = GcPauseRecorder(clock=clock)

    _collect(rec, clock, 0.1, 7)
    _collect(rec, clock, 0.1, -3)
    rec("start", None)  # type: ignore[arg-type]
    rec("stop", None)  # type: ignore[arg-type]  # fails inside, and is swallowed

    assert rec.collections == [1, 0, 1]


def test_a_stop_without_a_start_is_not_a_pause() -> None:
    # installed in the middle of a collection: the "start" was never seen, and the time since
    # an unset start would be published forever as a pause of the age of the machine
    clock = _Clock()
    rec = GcPauseRecorder(clock=clock)

    rec("stop", {"generation": 2, "collected": 7, "uncollectable": 0})

    assert rec.collections == [0, 0, 0] and rec.pause_total == [0.0, 0.0, 0.0]
    assert rec.slowest_since(0.0) is None
    _collect(rec, clock, 0.2, 1)  # and the recorder works normally afterwards
    assert rec.collections == [0, 1, 0]


def test_the_recorder_installs_once_and_sees_real_collections() -> None:
    rec = GcPauseRecorder()
    rec.install()
    rec.install()
    try:
        assert gc.callbacks.count(rec) == 1
        gc.collect()
        assert rec.collections[2] >= 1 and rec.totals()[1] > 0.0
    finally:
        rec.uninstall()
    rec.uninstall()
    assert rec not in gc.callbacks


# --- readings of the operating system ------------------------------------------------------


def test_the_proc_files_are_read_into_seconds() -> None:
    assert parse_schedstat("5000000000 2500000000 7\n") == 2.5
    assert parse_schedstat("") is None and parse_schedstat("1") is None
    assert parse_schedstat("a b c") is None

    pressure = "some avg10=0.00 avg60=1.10 avg300=0.50 total=3000000\nfull avg10=0 total=9\n"
    assert parse_pressure(pressure) == 3.0
    assert parse_pressure("full avg10=0.00 total=9\n") is None
    assert parse_pressure("some avg10=0.00 total=oops\n") is None

    stat = "cpu  100 0 50 1000 5 0 2 250 0 0\ncpu0 1 1 1 1 1 1 1 1 1 1\n"
    assert parse_cpu_steal(stat, 100.0) == 2.5
    assert parse_cpu_steal("cpu0 1 2 3\n", 100.0) is None
    assert parse_cpu_steal("cpu  1 2 3\n", 100.0) is None


def _fake_proc(root: Path, *, loop_tid: int, steal: int, cpu_total: int, wait_ns: int) -> None:
    (root / "pressure").mkdir(parents=True, exist_ok=True)
    (root / "self" / "task" / str(loop_tid)).mkdir(parents=True, exist_ok=True)
    (root / "stat").write_text(f"cpu  100 0 50 1000 5 0 2 {steal} 0 0\n")
    (root / "pressure" / "cpu").write_text(f"some avg10=1.00 total={cpu_total}\n")
    (root / "pressure" / "memory").write_text("some avg10=0.00 total=0\nfull avg10=0.00 total=0\n")
    (root / "pressure" / "io").write_text("some avg10=0.00 total=2000000\n")
    (root / "self" / "task" / str(loop_tid) / "schedstat").write_text(f"123 {wait_ns} 4\n")


def test_the_probe_reads_host_counters_and_the_loop_threads_run_queue_wait(
    tmp_path: Path,
) -> None:
    _fake_proc(tmp_path, loop_tid=4242, steal=250, cpu_total=3_000_000, wait_ns=2_500_000_000)
    clock = _Clock()
    probe = CounterProbe(loop_native_id=4242, clock=clock, proc_root=str(tmp_path))
    probe._tick = 100.0

    reading = probe.read()

    assert reading.taken == 100.0
    assert reading.host == {
        "steal_seconds": 2.5,
        "cpu_pressure_seconds": 3.0,
        "memory_pressure_seconds": 0.0,
        "io_pressure_seconds": 2.0,
    }
    assert reading.loop_wait == 2.5
    assert reading.process_cpu is not None and reading.process_cpu > 0.0
    assert reading.major_faults is not None and reading.involuntary_switches is not None


def test_a_system_without_proc_still_yields_the_portable_numbers(tmp_path: Path) -> None:
    probe = CounterProbe(loop_native_id=1, proc_root=str(tmp_path / "missing"))

    first = probe.read()
    second = probe.read()  # sources that failed are not asked again

    assert first.host == {} and first.loop_wait is None
    assert first.process_cpu is not None and second.process_cpu is not None
    assert probe._dead >= {"stat", "pressure/cpu", "self/task/1/schedstat"}


def test_a_threads_cpu_clock_is_computed_from_its_kernel_id() -> None:
    assert thread_cpu_clock(1234) == ((~1234) << 3) | 6
    assert thread_cpu_clock(1) != thread_cpu_clock(2)


@pytest.mark.skipif(not LINUX, reason="per-thread CPU clocks need Linux")
def test_the_computed_clock_is_the_one_glibc_hands_out_and_a_gone_thread_just_fails() -> None:
    me = threading.current_thread()
    assert me.native_id is not None and me.ident is not None
    assert thread_cpu_clock(me.native_id) == time.pthread_getcpuclockid(me.ident)
    assert time.clock_gettime(thread_cpu_clock(me.native_id)) > 0.0
    with pytest.raises(OSError):  # no thread has this id: an error, not undefined behaviour
        time.clock_gettime(thread_cpu_clock(4_194_000))


@pytest.mark.skipif(not LINUX, reason="per-thread CPU clocks need Linux")
def test_the_probe_reads_cpu_time_per_thread() -> None:
    stop = threading.Event()

    def burn() -> None:
        while not stop.is_set():
            sum(range(1000))

    thread = threading.Thread(target=burn, name="burner")
    thread.start()
    try:
        before = CounterProbe(loop_native_id=None).read()
        time.sleep(0.4)
        after = CounterProbe(loop_native_id=None).read()
    finally:
        stop.set()
        thread.join()

    assert thread.ident is not None
    used = after.thread_cpu[thread.ident] - before.thread_cpu[thread.ident]
    assert used > 0.05, "the burning thread used CPU"
    idle = after.thread_cpu[threading.get_ident()] - before.thread_cpu[threading.get_ident()]
    assert idle < used


def _counters(
    taken: float, *, process: float = 0.0, cpu: dict[int, float] | None = None, **kw: Any
) -> Counters:
    return Counters(taken=taken, process_cpu=process, thread_cpu=cpu or {}, **kw)


def test_usage_is_what_changed_between_two_readings() -> None:
    base = _counters(
        10.0,
        process=5.0,
        cpu={1: 1.0, 2: 4.0, 9: 7.0},
        major_faults=3,
        involuntary_switches=10,
        loop_wait=0.5,
        host={"steal_seconds": 1.0, "cpu_pressure_seconds": 2.0},
        gc_collections=100,
        gc_pause_seconds=1.5,
    )
    now = _counters(
        22.0,
        process=15.0,
        cpu={1: 1.5, 2: 12.0, 3: 2.0},  # 9 ended; 3 started inside the window
        major_faults=8,
        involuntary_switches=60,
        loop_wait=3.5,
        host={"steal_seconds": 1.4, "memory_pressure_seconds": 9.0},
        gc_collections=140,
        gc_pause_seconds=7.5,
    )

    usage = usage_between(base, now)

    assert usage.window == 12.0 and usage.process_cpu == 10.0
    assert usage.thread_cpu == {1: 0.5, 2: 8.0, 3: 2.0}
    assert usage.loop_wait == 3.0
    assert usage.host == pytest.approx({"steal_seconds": 0.4})  # only what both readings have
    assert usage.major_faults == 5 and usage.involuntary_switches == 50
    assert usage.gc_collections == 40 and usage.gc_pause_seconds == 6.0


def test_usage_never_goes_negative_and_keeps_unknowns_unknown() -> None:
    base = _counters(10.0, process=9.0, cpu={1: 5.0}, gc_collections=9, gc_pause_seconds=3.0)
    now = Counters(taken=9.0, process_cpu=None, thread_cpu={1: 4.0})  # counters went backwards

    usage = usage_between(base, now)

    assert usage.window == 0.0 and usage.process_cpu is None
    assert usage.thread_cpu == {1: 0.0}
    assert usage.major_faults is None and usage.loop_wait is None
    assert usage.gc_collections == 0 and usage.gc_pause_seconds == 0.0


def test_without_a_per_thread_baseline_totals_are_not_passed_off_as_the_windows_cpu() -> None:
    base = Counters(taken=1.0, process_cpu=5.0)  # the read behind it failed: nothing per thread
    now = _counters(11.0, process=15.0, cpu={1: 8000.0, 2: 4000.0})

    usage = usage_between(base, now)

    assert usage.thread_cpu == {} and usage.process_cpu == 10.0 and usage.threads_ended == 0


def test_threads_that_ended_in_the_window_are_counted() -> None:
    base = _counters(1.0, cpu={1: 1.0, 2: 2.0, 3: 3.0})
    now = _counters(2.0, cpu={1: 2.0})

    assert usage_between(base, now).threads_ended == 2


def test_a_counter_that_went_backwards_counts_as_no_change() -> None:
    # a reading is a snapshot of a counter that can be reset (a restarted cgroup, a wrapped value)
    base = _counters(
        1.0,
        process=9.0,
        major_faults=10,
        involuntary_switches=50,
        loop_wait=5.0,
        host={"steal_seconds": 3.0},
    )
    now = _counters(
        2.0,
        process=1.0,
        major_faults=4,
        involuntary_switches=20,
        loop_wait=2.0,
        host={"steal_seconds": 1.0},
    )

    usage = usage_between(base, now)

    assert usage.process_cpu == 0.0 and usage.loop_wait == 0.0
    assert usage.major_faults == 0 and usage.involuntary_switches == 0
    assert usage.host == {"steal_seconds": 0.0}


# --- the verdict ---------------------------------------------------------------------------

LOOP = 1


def _usage(
    *,
    loop: float = 0.0,
    others: tuple[float, ...] = (),
    process: float | None = 0.0,
    gc_pause: float = 0.0,
    per_thread: bool = True,
    loop_wait: float | None = None,
    host: dict[str, float] | None = None,
    threads_ended: int = 0,
) -> Usage:
    cpu: dict[int, float] = {}
    if per_thread:
        cpu = {LOOP: loop, **{100 + i: v for i, v in enumerate(others)}}
    return Usage(
        window=10.0,
        process_cpu=process,
        major_faults=None,
        involuntary_switches=None,
        thread_cpu=cpu,
        loop_wait=loop_wait,
        host=host or {},
        gc_collections=0,
        gc_pause_seconds=gc_pause,
        threads_ended=threads_ended,
    )


STEAL = {"steal_seconds": 3.0}


@pytest.mark.parametrize(
    ("scope", "usage", "cause"),
    [
        # garbage collection explains the stall, even though the thread that ran it burned CPU too
        ("process", _usage(others=(9.8,), process=9.8, gc_pause=9.6), "gc"),
        ("loop", _usage(loop=9.7, process=9.7, gc_pause=5.0), "gc"),
        # synchronous code on the loop thread itself (a long GIL-holding call made on it as well)
        ("loop", _usage(loop=9.0, process=9.0), "loop_busy"),
        ("process", _usage(loop=9.0, process=9.0), "loop_busy"),
        # one other thread held the GIL for most of the stall: the watchdog was held up too
        ("process", _usage(others=(9.5, 0.2), process=9.7), "other_thread"),
        # a loop that stalls while the watchdog runs is not blamed on a busy thread: it may be
        # blocked in a call of its own, and the busy thread a coincidence
        ("loop", _usage(others=(9.5, 0.2), process=9.7), "busy_pool"),
        ("loop", _usage(others=(5.0,), process=5.0), "busy_pool"),
        # no single thread has half, but together the others do: a GIL convoy shares one core
        ("process", _usage(others=(4.8, 4.8), process=9.6), "cpu_contention"),
        ("process", _usage(others=(3.2, 3.2, 3.2), process=9.6), "cpu_contention"),
        ("loop", _usage(others=(4.8, 4.8), process=9.6), "busy_pool"),
        # threads Python does not know about (BLAS, Arrow) used the CPU
        ("process", _usage(others=(0.3,), process=9.0), "native_threads"),
        ("loop", _usage(others=(0.3,), process=9.0), "native_threads"),
        # ...unless a thread ended in the window: its CPU is in the process total only
        ("process", _usage(others=(0.3,), process=9.0, threads_ended=1), "unknown"),
        # nothing ran at all
        ("process", _usage(others=(0.2,), process=0.4), "no_cpu"),
        # only the loop did not answer and no thread was busy: the loop waits in a call
        ("loop", _usage(others=(0.2,), process=0.4), "loop_blocked"),
        # the loop thread was runnable and waited for a CPU for most of the stall
        ("loop", _usage(others=(0.2,), process=0.4, loop_wait=6.0), "cpu_starved"),
        ("process", _usage(others=(9.5,), process=9.7, loop_wait=6.0), "cpu_starved"),
        # the host's counters say it took the CPU, memory or IO away; the process barely ran
        ("process", _usage(process=0.4, host={"steal_seconds": 3.0}), "host_pressure"),
        ("loop", _usage(process=0.4, host={"cpu_pressure_seconds": 6.0}), "host_pressure"),
        ("process", _usage(process=0.4, host={"io_pressure_seconds": 5.0}), "host_pressure"),
        ("process", _usage(process=0.4, host={"memory_pressure_seconds": 5.0}), "host_pressure"),
        # a little pressure, or a process that ran: not the host's doing
        ("process", _usage(process=0.4, host={"steal_seconds": 1.0}), "no_cpu"),
        ("process", _usage(process=0.4, host={"cpu_pressure_seconds": 4.0}), "no_cpu"),
        ("process", _usage(others=(0.3,), process=6.0, host=STEAL), "native_threads"),
        # no per-thread CPU on this system (macOS)
        ("loop", _usage(per_thread=False, process=0.4), "unknown"),
        ("process", _usage(per_thread=False, process=9.0), "unknown"),
        ("process", _usage(per_thread=False, process=0.4), "no_cpu"),
        ("process", _usage(per_thread=False, process=None), "unknown"),
        ("process", _usage(per_thread=False, process=0.4, host=STEAL), "host_pressure"),
    ],
)
def test_the_verdict(scope: str, usage: Usage, cause: str) -> None:
    assert classify(10.0, scope=scope, loop_ident=LOOP, usage=usage) == cause


def test_a_cause_needs_half_of_the_stall() -> None:
    def verdict(scope: str, usage: Usage) -> str:
        return classify(10.0, scope=scope, loop_ident=LOOP, usage=usage)

    assert verdict("loop", _usage(loop=5.0)) == "loop_busy"
    assert verdict("loop", _usage(loop=4.9)) == "loop_blocked"
    assert verdict("loop", _usage(gc_pause=5.0)) == "gc"
    assert verdict("loop", _usage(gc_pause=4.9)) != "gc"
    assert verdict("process", _usage(others=(5.0,), process=5.0)) == "other_thread"
    assert verdict("process", _usage(others=(2.5, 2.5), process=5.0)) == "cpu_contention"
    assert verdict("process", _usage(others=(2.4, 2.4), process=4.8)) == "unknown"
    assert verdict("loop", _usage(loop_wait=5.0)) == "cpu_starved"
    assert verdict("loop", _usage(loop_wait=4.9)) == "loop_blocked"
    def lazy(**host: float) -> Usage:  # a process that barely ran, with these host counters
        return _usage(per_thread=False, process=0.4, host=dict(host))

    assert verdict("process", lazy(cpu_pressure_seconds=5.0)) == "host_pressure"
    assert verdict("process", lazy(cpu_pressure_seconds=4.9)) == "no_cpu"
    assert verdict("process", lazy(steal_seconds=2.0)) == "host_pressure"
    assert verdict("process", lazy(steal_seconds=1.9)) == "no_cpu"
    # a process that used half of the stall's CPU is not blamed on the host, whatever it reports
    busy = {"steal_seconds": 9.0}
    assert verdict("process", _usage(per_thread=False, process=4.9, host=busy)) == "host_pressure"
    assert verdict("process", _usage(per_thread=False, process=5.0, host=busy)) == "unknown"
    assert verdict("process", _usage(per_thread=False, process=1.9)) == "no_cpu"
    assert verdict("process", _usage(per_thread=False, process=2.0)) == "unknown"
    # the probe could not read the loop thread's clock: it is taken to be idle, the others count
    gone = Usage(10.0, 9.0, None, None, {100: 9.0}, None, {}, 0, 0.0)
    assert classify(10.0, scope="process", loop_ident=LOOP, usage=gone) == "other_thread"
    assert classify(10.0, scope="process", loop_ident=None, usage=gone) == "other_thread"
    assert classify(10.0, scope="loop", loop_ident=LOOP, usage=gone) == "busy_pool"
    assert classify(0.0, scope="loop", loop_ident=LOOP, usage=_usage()) == "loop_blocked"


# --- the record ------------------------------------------------------------------------------

NAMES = {LOOP: "MainThread", 100: "asyncio_2", 101: "asyncio_3", 102: "asyncio_4", 103: "hb"}


def _describe(usage: Usage, stacks: dict[int, list[str]], **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "seconds": 10.0,
        "scope": "process",
        "usage": usage,
        "loop_ident": LOOP,
        "stacks": stacks,
        "names": NAMES,
        "stacks_during_stall": True,
        "slowest_gc": None,
    }
    args.update(kw)
    return describe_stall(**args)


def test_the_record_names_the_loop_thread_first_then_the_busiest_threads() -> None:
    usage = _usage(loop=0.01, others=(9.4, 0.05, 3.0, 0.5, 7.0))
    stacks = {
        LOOP: ["selectors.py:468 select"],
        100: ["avo.py:812 run_backtest", "thread.py:90 _worker"],
        101: ["threading.py:359 wait"],
        102: ["db.py:5 query"],
    }

    record = _describe(usage, stacks)  # thread 104 (0x68) has no name

    threads = record["threads"]
    assert [t["name"] for t in threads] == ["MainThread", "asyncio_2", "thread-68", "asyncio_4"]
    assert threads[0] == {
        "name": "MainThread",
        "loop": True,
        "cpu_seconds": 0.01,
        "stack": ["selectors.py:468 select"],
    }
    assert threads[1]["cpu_seconds"] == 9.4 and threads[1]["stack"][0] == "avo.py:812 run_backtest"
    assert all("loop" not in t for t in threads[1:])
    assert len(threads) == 1 + ev.EVIDENCE_THREADS
    assert record["cause"] == "other_thread" and record["scope"] == "process"


def test_a_thread_without_cpu_is_not_named_from_a_sample_taken_after_the_stall() -> None:
    stacks = {LOOP: [], 100: ["a.py:1 f"]}

    record = _describe(_usage(others=(0.05, 0.02), process=0.1), stacks, stacks_during_stall=False)

    assert [t["name"] for t in record["threads"]] == ["MainThread"]


def test_a_thread_stuck_in_a_call_that_keeps_the_gil_is_named_from_the_dump_without_cpu() -> None:
    # A C call that holds the GIL while it waits (a driver blocked on the network, say) uses no
    # CPU, so only its stack gives it away: busy threads first, then threads not parked in a wait.
    usage = _usage(others=(0.0, 3.0, 0.0), process=3.0)
    stacks = {
        LOOP: ["selectors.py:468 select"],
        100: ["driver.py:77 fetch_all", "thread.py:90 _worker"],
        101: ["avo.py:812 run_backtest", "thread.py:90 _worker"],
        102: ["threading.py:359 wait", "thread.py:90 _worker"],
    }

    record = _describe(usage, stacks, stacks_during_stall=True)

    assert [t["name"] for t in record["threads"]] == ["MainThread", "asyncio_3", "asyncio_2"]
    assert record["threads"][1]["cpu_seconds"] == 3.0


def test_without_per_thread_cpu_every_thread_not_parked_in_a_wait_is_named() -> None:
    stacks = {
        LOOP: ["selectors.py:468 select"],
        100: ["threading.py:359 wait", "thread.py:90 _worker"],  # a parked pool thread
        101: ["avo.py:812 run_backtest", "thread.py:90 _worker"],  # a thread inside a long call
        102: [],
    }

    record = _describe(_usage(per_thread=False, process=9.0), stacks)

    assert [t["name"] for t in record["threads"]] == ["MainThread", "asyncio_3"]
    assert all("cpu_seconds" not in t for t in record["threads"])


def test_the_record_says_where_its_stacks_come_from() -> None:
    usage = _usage(process=9.0)
    assert _describe(usage, {}, stacks_during_stall=True)["stack_source"] == "dump"
    assert _describe(usage, {}, stacks_during_stall=False)["stack_source"] == "sample"


def test_the_record_carries_the_numbers_and_is_plain_json() -> None:
    usage = Usage(
        window=12.34,
        process_cpu=0.456,
        major_faults=120,
        involuntary_switches=7,
        thread_cpu={LOOP: 0.0},
        loop_wait=8.4321,
        host={"steal_seconds": 3.14159, "cpu_pressure_seconds": 9.9},
        gc_collections=3,
        gc_pause_seconds=0.123,
    )

    record = _describe(usage, {}, slowest_gc=(0.1, 2))

    assert record["window_seconds"] == 12.3
    assert record["cpu"] == {"process_seconds": 0.46, "loop_thread_wait_seconds": 8.43}
    assert record["gc"] == {
        "collections": 3,
        "pause_seconds": 0.12,
        "max_pause_seconds": 0.1,
        "generation": 2,
    }
    assert record["host"] == {
        "steal_seconds": 3.14,
        "cpu_pressure_seconds": 9.9,
        "major_faults": 120,
        "involuntary_switches": 7,
    }
    assert json.loads(json.dumps(record, allow_nan=False)) == record
    no_gc = _describe(usage, {})["gc"]
    assert "max_pause_seconds" not in no_gc and "generation" not in no_gc


def test_a_record_without_any_reading_still_has_a_cause() -> None:
    record = _describe(Usage.unknown(), {LOOP: ["a.py:1 f"]})

    assert record["cause"] == "unknown"
    assert record["cpu"] == {} and record["host"] == {}
    assert record["threads"] == [{"name": "MainThread", "loop": True, "stack": ["a.py:1 f"]}]


# --- the process context the heartbeat publishes -----------------------------------------


def test_process_stats_has_the_context_a_stall_is_read_in(tmp_path: Path) -> None:
    (tmp_path / "self").mkdir()
    (tmp_path / "self" / "statm").write_text("250000 100000 5000 100 0 90000 0\n")
    rec = GcPauseRecorder(clock=_Clock())

    stats = process_stats(rec, proc_root=str(tmp_path))

    page = os.sysconf("SC_PAGE_SIZE")
    assert stats["rss_mb"] == round(100000 * page / (1024 * 1024), 1)
    assert stats["gc"] == {
        "collections": [0, 0, 0],
        "pause_seconds": [0.0, 0.0, 0.0],
        "max_pause_seconds": [0.0, 0.0, 0.0],
        "threshold": list(gc.get_threshold()),
    }
    assert stats["python"].startswith(f"{sys.version_info.major}.{sys.version_info.minor}")
    assert stats["threads"] == threading.active_count()
    assert isinstance(stats["cpus"], int) and stats["cpus"] >= 1
    assert all(math.isfinite(v) for v in stats["gc"]["pause_seconds"])
    json.dumps(stats, allow_nan=False)


def test_process_stats_omits_what_the_system_does_not_say(tmp_path: Path) -> None:
    stats = process_stats(GcPauseRecorder(clock=_Clock()), proc_root=str(tmp_path / "none"))

    assert "rss_mb" not in stats and "gc" in stats and "python" in stats
