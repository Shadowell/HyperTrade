"""Why the worker's event loop stalled: code locations and numbers, never source or values.

``loop_watchdog`` says *that* the loop was blocked and for how long. The stalls sampled in
production show what that is not enough for: for 3-14 s the loop thread sat in an idle ``select``
or at unrelated places (``socket.gethostname()``, a database send, SQLAlchemy's pure-Python
helpers, the OKX stream). A thread is parked wherever it last gave up the GIL or the CPU, so the
loop was the victim, not the cause. Finding the cause means looking at everything else that was
going on:

* every thread's stack and how much CPU each thread used while the loop was stalled;
* garbage-collection pauses (a full collection holds the GIL for as long as it takes);
* whether the process ran at all (CPU used, how long the loop thread waited for a CPU, system
  CPU / memory / IO pressure, CPU steal, page faults), which tells a thread that holds the GIL from
  a host that did not schedule the process;
* a stack dump taken *during* the stall by faulthandler's C thread, which needs no GIL. A
  GIL-holding C call stops the watchdog thread too, so it can sample only after the call returned.

Everything is best effort and Linux first (the production host); where an operating system does not
provide a number it is simply absent. Nothing in here may raise into the watchdog.
"""

from __future__ import annotations

import faulthandler
import gc
import logging
import os
import platform
import re
import resource
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import FrameType
from typing import Any

logger = logging.getLogger("hypertrade.stall_evidence")

STACK_FRAMES = 10
# Per thread in a stall record: shorter than the loop thread's own stack, there are several.
THREAD_STACK_FRAMES = 8
# The busiest threads other than the loop thread that a stall record names.
EVIDENCE_THREADS = 3
# A thread that used less CPU than this during a stall is not worth naming.
MIN_THREAD_CPU_SECONDS = 0.1
# A collection shorter than this is only counted; slower ones are remembered one by one.
SLOW_GC_SECONDS = 0.05
SLOW_GC_RING = 256
# Share of a stall's length that one cause has to explain before it is named.
CAUSE_SHARE = 0.5
# Below this share of the stall the process counts as not having run at all.
IDLE_SHARE = 0.2
# A dump lists every thread with up to 100 frames each; the loop thread, the oldest, comes last.
MAX_DUMP_BYTES = 8 * 1024 * 1024
# Consecutive failed re-arms (a thread could not be created, say) before the dump gives up.
MAX_DUMP_FAILURES = 5
_LINUX = sys.platform.startswith("linux")


# --- code locations ------------------------------------------------------------------------


def _location(filename: str, lineno: int | str, name: str) -> str | None:
    """``file:line function``; None for an asyncio frame, ``<dynamic>`` for generated code.

    Code compiled from a string (strategies the agents write run through ``exec``) has names that
    are data, not ours, and this record is published: a ``<string>``-style filename, or a bare label
    that is not a path, shows as ``<dynamic>:line <code>``. A script with a directory (a console
    entry point such as ``/app/.venv/bin/uvicorn``) is code of ours and stays.
    """
    path = filename.replace("\\", "/")
    if "/asyncio/" in path:
        return None
    base = path.rpartition("/")[2]
    # <frozen runpy> and the like are the interpreter's own modules
    generated = not base.startswith("<frozen ") and (
        base.startswith("<") or (not base.endswith(".py") and "/" not in path)
    )
    if generated:
        return f"<dynamic>:{lineno} <code>"
    return f"{base}:{lineno} {name}"


def stack_of(frame: FrameType | None, *, limit: int = STACK_FRAMES) -> list[str]:
    """``file:line function`` for the deepest ``limit`` non-asyncio frames, deepest first.

    Walks the frames directly instead of going through ``traceback``, which also reads the source
    line of every frame: nothing but locations leaves this function, and sampling dozens of
    threads while the process is struggling must not open dozens of source files.
    """
    locations: list[str] = []
    while frame is not None and len(locations) < limit:
        code = frame.f_code
        location = _location(code.co_filename, frame.f_lineno or 0, code.co_name)
        if location is not None:
            locations.append(location)
        frame = frame.f_back
    return locations


_IDLE_TOPS = frozenset(
    {
        ("threading.py", "wait"),
        ("threading.py", "_wait_for_tstate_lock"),
        ("threading.py", "join"),
        ("queue.py", "get"),
        ("thread.py", "_worker"),
        ("selectors.py", "select"),
        ("loop_watchdog.py", "_run"),
    }
)


def is_idle(stack: Sequence[str]) -> bool:
    """Whether a stack ends in one of the waits a parked pool or service thread sits in."""
    if not stack:
        return True
    where, _, name = stack[0].partition(" ")
    return (where.partition(":")[0], name) in _IDLE_TOPS


# --- a stack dumped by faulthandler during the stall ---------------------------------------

# "Thread 0x7f.. (most recent call first):", and since Python 3.14 "Thread 0x7f.. [name] (...):"
_THREAD_HEADER = re.compile(r"^(?:Current thread|Thread) 0x([0-9a-fA-F]+)(?: \[(.*?)\])?(?: |$)")
_FRAME_LINE = re.compile(r'^\s+File "(.*)", line (\d+) in (.+?)\s*$')


@dataclass(frozen=True, slots=True)
class Dump:
    """Every thread's stack as faulthandler saw it during a stall."""

    stacks: dict[int, list[str]]  # by thread ident (``threading.get_ident()``)
    # Python 3.14 names the threads in the dump, which also names one that has ended since.
    names: dict[int, str]


def parse_faulthandler_dump(text: str, *, limit: int = THREAD_STACK_FRAMES) -> Dump:
    """The stacks (and, where printed, the thread names) in a faulthandler traceback dump.

    The dump lists each thread's frames most recent first, which is already deepest first. Lines
    that are not a thread header or a frame (the timeout banner, ``<no Python frame>``) are ignored.
    """
    stacks: dict[int, list[str]] = {}
    names: dict[int, str] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        header = _THREAD_HEADER.match(line)
        if header:
            ident = int(header.group(1), 16)
            current = stacks.setdefault(ident, [])
            if header.group(2):
                names[ident] = header.group(2)[:48]
            continue
        frame = _FRAME_LINE.match(line)
        if frame is None or current is None or len(current) >= limit:
            continue
        location = _location(*frame.groups())
        if location is not None:
            current.append(location)
    return Dump(stacks, names)


def _dump_file() -> Any:
    """An unlinked in-memory file where there is one (Linux), else a temporary file.

    ``faulthandler.cancel_dump_traceback_later`` waits for a dump that is being written while it
    holds the GIL, so a dump that blocks on a throttled disk would freeze the whole interpreter
    during exactly the I/O stalls this is meant to explain. Memory does not block.
    """
    memfd = getattr(os, "memfd_create", None)
    if memfd is not None:
        try:
            return os.fdopen(memfd("hypertrade-stall-dump"), "w+b", buffering=0)
        except OSError:
            logger.debug("no memfd for the stall dump", exc_info=True)
    return tempfile.TemporaryFile(mode="w+b", buffering=0)  # noqa: SIM115 - lives as long as we do


class HeldStackDump:
    """Has faulthandler dump every thread's stack when the watchdog thread cannot re-arm it.

    ``faulthandler.dump_traceback_later`` runs a C thread that needs no GIL. The watchdog re-arms
    it on every poll, so it fires only when the watchdog thread was held up for ``timeout`` seconds:
    by a thread inside a long GIL-holding C call, by a collection or by a host that did not run
    the process. That is exactly when ``sys._current_frames()`` cannot be called, and the dump
    shows the stacks as they were during the stall, the culprit's included.

    The timer is process-global: nothing else in the worker uses ``dump_traceback_later``, and this
    would replace the timer of anything that did. The C thread reads other threads' frames without
    the GIL; while one of them runs Python the dump can hold ``<invalid frame>`` lines (ignored
    when parsing), and a torn read is a risk of the C-level kind, so ``HYPERTRADE_STALL_DUMP=0``
    switches the whole mechanism off.
    """

    def __init__(self, timeout: float) -> None:
        self._timeout = timeout
        self._file: Any = None
        self._failures = 0

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def active(self) -> bool:
        return self._file is not None

    def start(self) -> bool:
        try:
            self._file = _dump_file()
        except OSError:
            logger.info("stall stack dumps are off: no file to dump into", exc_info=True)
            return False
        return True

    def rearm(self, *, check: bool = True) -> Dump | None:
        """Re-arm the timer; return the dump that fired since the previous call, if one did.

        ``check`` says a dump may have fired (the caller was away for at least ``timeout``): only
        then is the file looked at, so a healthy poll costs no system call.
        """
        file = self._file
        if file is None:
            return None
        held: Dump | None = None
        try:
            faulthandler.cancel_dump_traceback_later()  # waits for a dump in progress to finish
            if check and file.seek(0, os.SEEK_END):
                file.seek(0)
                text = file.read(MAX_DUMP_BYTES).decode("utf-8", "replace")
                file.seek(0)
                file.truncate()
                held = parse_faulthandler_dump(text)
            faulthandler.dump_traceback_later(self._timeout, repeat=False, file=file)
            self._failures = 0
        except (OSError, RuntimeError, ValueError):
            # One failure (no thread could be created, say) is skipped; a run of them ends it.
            self._failures += 1
            if self._failures >= MAX_DUMP_FAILURES:
                logger.warning("stall stack dumps stopped", exc_info=True)
                self.close()
        return held

    def close(self) -> None:
        file, self._file = self._file, None
        if file is None:
            return
        try:
            faulthandler.cancel_dump_traceback_later()
            file.close()
        except (OSError, RuntimeError, ValueError):
            logger.debug("stall stack dump file did not close cleanly", exc_info=True)


# --- garbage collection ---------------------------------------------------------------------


class GcPauseRecorder:
    """Times every garbage collection through ``gc.callbacks``.

    The callback runs inside the collector, in whichever thread triggered the collection, and
    that thread may be holding any lock: it takes none and allocates almost nothing. Every
    collection is counted and timed per generation; only slow ones are remembered one by one.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._started: float | None = None
        self.collections = [0, 0, 0]
        self.pause_total = [0.0, 0.0, 0.0]
        self.pause_max = [0.0, 0.0, 0.0]
        self._slow: list[tuple[float, float, int] | None] = [None] * SLOW_GC_RING
        self._slow_next = 0

    def __call__(self, phase: str, info: dict[str, int]) -> None:
        try:
            if phase == "start":
                self._started = self._clock()
                return
            started, self._started = self._started, None
            if started is None:  # a collection that began before this recorder was installed
                return
            ended = self._clock()
            seconds = max(0.0, ended - started)
            generation = min(max(int(info.get("generation", 0)), 0), 2)
            self.collections[generation] += 1
            self.pause_total[generation] += seconds
            if seconds > self.pause_max[generation]:
                self.pause_max[generation] = seconds
            if seconds >= SLOW_GC_SECONDS:
                self._slow[self._slow_next % SLOW_GC_RING] = (ended, seconds, generation)
                self._slow_next += 1
        except Exception:  # a collector callback must never raise
            return

    def install(self) -> None:
        if self not in gc.callbacks:
            gc.callbacks.append(self)

    def uninstall(self) -> None:
        if self in gc.callbacks:
            gc.callbacks.remove(self)

    def totals(self) -> tuple[int, float]:
        """Collections and seconds spent in them since the recorder was created."""
        return sum(self.collections), sum(self.pause_total)

    def slowest_since(self, since: float) -> tuple[float, int] | None:
        """The slowest remembered collection that ended after ``since``: (seconds, generation)."""
        best: tuple[float, float, int] | None = None
        for entry in list(self._slow):
            if entry is not None and entry[0] >= since and (best is None or entry[1] > best[1]):
                best = entry
        return (best[1], best[2]) if best else None

    def summary(self) -> dict[str, list[float] | list[int]]:
        return {
            "collections": list(self.collections),
            "pause_seconds": [round(v, 2) for v in self.pause_total],
            "max_pause_seconds": [round(v, 3) for v in self.pause_max],
        }


GC_PAUSES = GcPauseRecorder()


# --- what the operating system says ---------------------------------------------------------


def parse_schedstat(text: str) -> float | None:
    """Seconds a thread waited on a run queue, from ``/proc/<pid>/task/<tid>/schedstat``."""
    parts = text.split()
    if len(parts) < 2:
        return None
    try:
        return int(parts[1]) / 1e9
    except ValueError:
        return None


def parse_pressure(text: str) -> float | None:
    """Seconds some task was stalled, from a ``/proc/pressure/*`` file's ``some`` line."""
    for line in text.splitlines():
        if line.startswith("some "):
            for token in line.split():
                if token.startswith("total="):
                    try:
                        return int(token[6:]) / 1e6
                    except ValueError:
                        return None
    return None


def parse_cpu_steal(text: str, ticks_per_second: float) -> float | None:
    """Seconds the hypervisor ran something else, from the first line of ``/proc/stat``."""
    for line in text.splitlines():
        if line.startswith("cpu "):
            fields = line.split()
            try:
                return int(fields[8]) / ticks_per_second
            except (IndexError, ValueError):
                return None
    return None


def thread_cpu_clock(native_id: int) -> int:
    """The Linux CPU-time clock of one thread, from its kernel thread id.

    What glibc's ``pthread_getcpuclockid`` returns, computed from the id instead: that function
    dereferences a ``pthread_t`` and is undefined for a thread that has ended, whereas a clock id
    for a thread that is gone just fails with ESRCH.
    """
    return ((~native_id) << 3) | 6


@dataclass(frozen=True, slots=True)
class Counters:
    """One reading of everything that is cheap to read and comparable over a stall."""

    taken: float
    process_cpu: float | None = None
    major_faults: int | None = None
    involuntary_switches: int | None = None
    thread_cpu: Mapping[int, float] = field(default_factory=dict)  # by threading ident
    loop_wait: float | None = None  # the loop thread's time on a run queue, waiting for a CPU
    host: Mapping[str, float] = field(default_factory=dict)
    gc_collections: int = 0
    gc_pause_seconds: float = 0.0


class CounterProbe:
    """Reads :class:`Counters`; a source that fails once is not asked again."""

    def __init__(
        self,
        *,
        loop_native_id: int | None,
        gc_pauses: GcPauseRecorder | None = None,
        clock: Callable[[], float] = time.monotonic,
        proc_root: str = "/proc",
    ) -> None:
        self._loop_native_id = loop_native_id
        self._gc = gc_pauses
        self._clock = clock
        self._root = proc_root
        self._dead: set[str] = set()
        try:
            self._tick = float(os.sysconf("SC_CLK_TCK"))
        except (ValueError, OSError, AttributeError):
            self._tick = 100.0

    def _read(self, relative: str) -> str | None:
        if relative in self._dead:
            return None
        try:
            with open(os.path.join(self._root, relative), encoding="ascii", errors="replace") as f:
                return f.read()
        except OSError:
            self._dead.add(relative)
            return None

    def _thread_cpu(self) -> dict[int, float]:
        """CPU seconds per Python thread, by ``threading`` ident (Linux only)."""
        if not _LINUX:
            return {}
        cpu: dict[int, float] = {}
        for thread in threading.enumerate():
            ident, tid = thread.ident, thread.native_id
            if ident is None or tid is None:
                continue
            try:
                cpu[ident] = time.clock_gettime(thread_cpu_clock(tid))
            except (OSError, ValueError, OverflowError):
                continue  # the thread ended since it was listed
        return cpu

    def _host(self) -> dict[str, float]:
        host: dict[str, float] = {}
        text = self._read("stat")
        steal = parse_cpu_steal(text, self._tick) if text else None
        if steal is not None:
            host["steal_seconds"] = steal
        for name in ("cpu", "memory", "io"):
            text = self._read(f"pressure/{name}")
            value = parse_pressure(text) if text else None
            if value is not None:
                host[f"{name}_pressure_seconds"] = value
        return host

    def read(self) -> Counters:
        taken = self._clock()
        process_cpu: float | None = None
        major_faults: int | None = None
        switches: int | None = None
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
            process_cpu = usage.ru_utime + usage.ru_stime
            major_faults = usage.ru_majflt
            switches = usage.ru_nivcsw
        except (OSError, ValueError):
            pass
        loop_wait: float | None = None
        if self._loop_native_id is not None:
            text = self._read(f"self/task/{self._loop_native_id}/schedstat")
            loop_wait = parse_schedstat(text) if text else None
        collections, pause = self._gc.totals() if self._gc is not None else (0, 0.0)
        return Counters(
            taken=taken,
            process_cpu=process_cpu,
            major_faults=major_faults,
            involuntary_switches=switches,
            thread_cpu=self._thread_cpu(),
            loop_wait=loop_wait,
            host=self._host(),
            gc_collections=collections,
            gc_pause_seconds=pause,
        )


@dataclass(frozen=True, slots=True)
class Usage:
    """What changed between two readings: the stall's window."""

    window: float
    process_cpu: float | None
    major_faults: int | None
    involuntary_switches: int | None
    thread_cpu: dict[int, float]
    loop_wait: float | None
    host: dict[str, float]
    gc_collections: int
    gc_pause_seconds: float
    threads_ended: int = 0  # threads in the first reading and not in the second: their CPU is lost

    @classmethod
    def unknown(cls) -> Usage:
        """No baseline reading to compare with: nothing is known about the window."""
        return cls(0.0, None, None, None, {}, None, {}, 0, 0.0)


def _minus(now: float | None, base: float | None) -> float | None:
    return None if now is None or base is None else max(0.0, now - base)


def usage_between(base: Counters, now: Counters) -> Usage:
    faults = _minus(now.major_faults, base.major_faults)
    switches = _minus(now.involuntary_switches, base.involuntary_switches)
    host = {
        key: max(0.0, value - base.host[key]) for key, value in now.host.items() if key in base.host
    }
    thread_cpu: dict[int, float] = {}
    ended = 0
    if base.thread_cpu:
        # A thread that started inside the window is counted from zero. Without any per-thread
        # reading to start from (a failed read) the totals would pass for the window's CPU.
        thread_cpu = {
            ident: max(0.0, cpu - base.thread_cpu.get(ident, 0.0))
            for ident, cpu in now.thread_cpu.items()
        }
        ended = len(set(base.thread_cpu) - set(now.thread_cpu))
    return Usage(
        window=max(0.0, now.taken - base.taken),
        process_cpu=_minus(now.process_cpu, base.process_cpu),
        major_faults=None if faults is None else int(faults),
        involuntary_switches=None if switches is None else int(switches),
        thread_cpu=thread_cpu,
        loop_wait=_minus(now.loop_wait, base.loop_wait),
        host=host,
        gc_collections=max(0, now.gc_collections - base.gc_collections),
        gc_pause_seconds=max(0.0, now.gc_pause_seconds - base.gc_pause_seconds),
        threads_ended=ended,
    )


# --- the verdict -----------------------------------------------------------------------------


def _host_pressure(usage: Usage, seconds: float) -> bool:
    """Whether the host's own counters show it took the CPU, memory or IO away."""
    if usage.host.get("steal_seconds", 0.0) >= IDLE_SHARE * seconds:
        return True
    return any(
        usage.host.get(f"{kind}_pressure_seconds", 0.0) >= CAUSE_SHARE * seconds
        for kind in ("cpu", "memory", "io")
    )


def classify(seconds: float, *, scope: str, loop_ident: int | None, usage: Usage) -> str:
    """One word for what the numbers say. The raw numbers are published next to it.

    ``scope`` is ``process`` when the watchdog thread was held up as well (the GIL or the
    whole process was unavailable) and ``loop`` when only the loop did not answer. A cause has to
    explain half of the stall:

    * ``gc``: collections account for it;
    * ``loop_busy``: the loop thread itself ran (synchronous code on the loop; in a process-scope
      stall, a long GIL-holding call made on the loop thread);
    * ``cpu_starved``: the loop thread was runnable but waited for a CPU (the host, another process
      or other threads took them; ``host`` and ``threads`` say who);
    * ``other_thread`` (process scope): one other thread ran for most of the stall while the
      watchdog was held up too, so it held the GIL: its stack names the call;
    * ``cpu_contention`` (process scope): no single thread did, together the others did;
    * ``busy_pool`` (loop scope): the watchdog ran and the loop did not answer while other threads
      used the CPU: the loop was starved by them or blocked in a call, and the stacks tell which;
    * ``native_threads``: threads Python does not know about (BLAS, Arrow, ...) used the CPU;
    * ``host_pressure``: the process used little CPU and the host's counters (steal, pressure) say
      it was the host;
    * ``no_cpu`` (process scope): the process used almost no CPU: every thread was blocked (a call
      that keeps the GIL while it waits, IO, paging) or the host did not run it; ``threads`` and
      ``host`` tell which;
    * ``loop_blocked`` (loop scope): the loop thread waits in a call; its stack names the call.
    """
    seconds = max(seconds, 0.001)
    half = CAUSE_SHARE * seconds
    if usage.gc_pause_seconds >= half:
        return "gc"
    cpu = usage.thread_cpu
    # Per-thread CPU is known on Linux; a loop thread whose clock could not be read counts as idle.
    loop_cpu = cpu.get(loop_ident, 0.0) if cpu and loop_ident is not None else 0.0
    if loop_cpu >= half:
        return "loop_busy"
    if usage.loop_wait is not None and usage.loop_wait >= half:
        return "cpu_starved"
    if cpu:
        others = [value for ident, value in cpu.items() if ident != loop_ident]
        if scope == "process":
            if others and max(others) >= half:
                return "other_thread"
            if sum(others) >= half:
                return "cpu_contention"
        elif sum(others) >= half:
            return "busy_pool"
        if (
            usage.process_cpu is not None
            and usage.threads_ended == 0  # an ended thread's CPU is in the process total only
            and usage.process_cpu - sum(cpu.values()) >= half
        ):
            return "native_threads"
    little_cpu = usage.process_cpu is not None and usage.process_cpu < half
    if little_cpu and _host_pressure(usage, seconds):
        return "host_pressure"
    if scope == "process":
        if usage.process_cpu is not None and usage.process_cpu < IDLE_SHARE * seconds:
            return "no_cpu"
        return "unknown"
    return "loop_blocked" if cpu else "unknown"


def _pick_threads(
    *,
    loop_ident: int | None,
    cpu: Mapping[int, float],
    stacks: Mapping[int, list[str]],
    names: Mapping[int, str],
    during_stall: bool,
) -> list[dict[str, Any]]:
    """The loop thread (marked), then the threads most likely to be the cause, with their stacks.

    Busiest first. A thread that used no CPU is named only when it is not parked in a wait and
    either the stacks were taken during the stall (a thread stuck in a call that keeps the GIL
    uses no CPU either) or this system has no per-thread CPU to go by.
    """
    entries: list[dict[str, Any]] = []

    def entry(ident: int) -> dict[str, Any]:
        item: dict[str, Any] = {"name": names.get(ident) or f"thread-{ident:x}"}
        if ident == loop_ident:
            item["loop"] = True
        if ident in cpu:
            item["cpu_seconds"] = round(cpu[ident], 2)
        item["stack"] = list(stacks.get(ident, []))[:THREAD_STACK_FRAMES]
        return item

    if loop_ident is not None:
        entries.append(entry(loop_ident))
    others = sorted(ident for ident in set(stacks) | set(cpu) if ident != loop_ident)
    chosen = sorted(
        (i for i in others if cpu.get(i, 0.0) >= MIN_THREAD_CPU_SECONDS),
        key=lambda i: cpu[i],
        reverse=True,
    )
    if during_stall or not cpu:
        chosen.extend(i for i in others if i not in chosen and not is_idle(stacks.get(i, [])))
    entries.extend(entry(ident) for ident in chosen[:EVIDENCE_THREADS])
    return entries


def describe_stall(
    *,
    seconds: float,
    scope: str,
    usage: Usage,
    loop_ident: int | None,
    stacks: Mapping[int, list[str]],
    names: Mapping[int, str],
    stacks_during_stall: bool,
    slowest_gc: tuple[float, int] | None,
    ongoing: bool = False,
) -> dict[str, Any]:
    """The part of a stall record that explains it (JSON-safe, bounded, numbers and locations).

    ``ongoing`` marks what is known while the stall still lasts; the final record replaces it.
    """
    cpu_view: dict[str, float] = {}
    if usage.process_cpu is not None:
        cpu_view["process_seconds"] = round(usage.process_cpu, 2)
    if usage.loop_wait is not None:
        cpu_view["loop_thread_wait_seconds"] = round(usage.loop_wait, 2)
    gc_view: dict[str, float | int] = {
        "collections": usage.gc_collections,
        "pause_seconds": round(usage.gc_pause_seconds, 2),
    }
    if slowest_gc is not None:
        gc_view["max_pause_seconds"] = round(slowest_gc[0], 2)
        gc_view["generation"] = slowest_gc[1]
    host: dict[str, float | int] = {key: round(v, 2) for key, v in usage.host.items()}
    if usage.major_faults is not None:
        host["major_faults"] = usage.major_faults
    if usage.involuntary_switches is not None:
        host["involuntary_switches"] = usage.involuntary_switches
    record: dict[str, Any] = {
        "cause": classify(seconds, scope=scope, loop_ident=loop_ident, usage=usage),
        "scope": scope,
        "window_seconds": round(usage.window, 1),
        # "dump": the stacks were taken during the stall; "sample": after it, by the watchdog
        "stack_source": "dump" if stacks_during_stall else "sample",
        "threads": _pick_threads(
            loop_ident=loop_ident,
            cpu=usage.thread_cpu,
            stacks=stacks,
            names=names,
            during_stall=stacks_during_stall,
        ),
        "cpu": cpu_view,
        "gc": gc_view,
        "host": host,
    }
    if ongoing:
        record["ongoing"] = True
    return record


# --- what the heartbeat publishes about the process itself ----------------------------------


def _cpu_count() -> int | None:
    affinity = getattr(os, "sched_getaffinity", None)
    try:
        return len(affinity(0)) if affinity is not None else os.cpu_count()
    except OSError:
        return os.cpu_count()


def _rss_mb(proc_root: str) -> float | None:
    try:
        with open(os.path.join(proc_root, "self/statm"), encoding="ascii") as f:
            pages = int(f.read().split()[1])
        return round(pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024), 1)
    except (OSError, ValueError, IndexError):
        return None


def process_stats(
    recorder: GcPauseRecorder | None = None, *, proc_root: str = "/proc"
) -> dict[str, Any]:
    """The context a stall is read in: interpreter, CPUs, threads, memory, garbage collection.

    ``gc.threshold`` tells which collector this interpreter has (Python 3.14 has two generations
    and an incremental old one; earlier versions collect the old generation in one go).
    """
    gc_view: dict[str, Any] = dict((recorder or GC_PAUSES).summary())
    gc_view["threshold"] = list(gc.get_threshold())
    stats: dict[str, Any] = {
        "python": platform.python_version(),
        "threads": threading.active_count(),
        "gc": gc_view,
    }
    cpus = _cpu_count()
    if cpus:
        stats["cpus"] = cpus
    rss = _rss_mb(proc_root)
    if rss is not None:
        stats["rss_mb"] = rss
    return stats
