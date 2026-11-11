"""Name what holds the worker's event loop, and what else was going on while it was held.

The heartbeat reports *that* the loop was blocked and for how long (``event_loop_lag_max_seconds``),
not *what* blocked it, and the production host is not reachable from a debugging session. This
watchdog runs on its own thread, asks the loop to acknowledge a callback twice a second and, when
the acknowledgement is more than ``threshold_seconds`` late, samples every thread's stack and hands
the loop thread's to the heartbeat registry, so ``/api/healthz`` can say which function was running.

A stack of the loop thread names the culprit only when the loop itself runs synchronous code. The
stalls in production were a different animal: for 3-14 s the loop thread sat in an idle ``select``
or at unrelated places, waiting for the GIL or the CPU while something else had it. So the
watchdog also

* notices when *it* was held up (a thread inside a long GIL-holding C call stops this one too, and
  the loop can catch up before the watchdog looks, which used to hide the stall altogether);
* keeps a short history of CPU, garbage-collection and host counters, read on a thread of their own
  so that reading them never makes this thread late, and publishes what changed during a stall:
  which threads used the CPU, how long collections paused the process, whether the process ran at
  all (``stall_evidence`` has the details);
* lets faulthandler's C thread dump every thread's stack during a stall that held the watchdog up.

Only ``file:line function`` and numbers are recorded, never source lines or variable values, so a
stack cannot carry a credential or customer data.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from types import FrameType
from typing import Any

from hypertrade.runtime.heartbeat import HeartbeatRegistry
from hypertrade.runtime.stall_evidence import (
    GC_PAUSES,
    STACK_FRAMES,
    THREAD_STACK_FRAMES,
    CounterProbe,
    Counters,
    Dump,
    GcPauseRecorder,
    HeldStackDump,
    Usage,
    describe_stall,
    stack_of,
    usage_between,
)

logger = logging.getLogger("hypertrade.loop_watchdog")

DEFAULT_THRESHOLD_SECONDS = 3.0
POLL_SECONDS = 0.5
# A long stall is re-sampled this often: the blocking call can change while it lasts.
RESAMPLE_SECONDS = 15.0
# HYPERTRADE_STALL_DUMP=0 turns off the faulthandler stack dump (everything else stays on).
STACK_DUMP_ENV = "HYPERTRADE_STALL_DUMP"
# Readings kept beyond the threshold, so a stall found late still has one from before it began.
HISTORY_MARGIN = 6
# How long stop() waits for each of the watchdog's threads.
STOP_JOIN_SECONDS = 2.0


def format_stack(frame: FrameType, *, limit: int = STACK_FRAMES) -> list[str]:
    """``file:line function`` for the deepest ``limit`` non-asyncio frames, deepest first."""
    return stack_of(frame, limit=limit)


def stack_dump_enabled() -> bool:
    value = os.environ.get(STACK_DUMP_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


@dataclass
class _Episode:
    """One stall, from the loop's last sign of life until it answers again."""

    started: float
    base: Counters | None  # the reading taken just before the stall began
    scope: str = "loop"  # "process" once the watchdog thread was held up too
    last_report: float | None = None
    stacks: dict[int, list[str]] = field(default_factory=dict)  # latest sample by thread ident
    names: dict[int, str] = field(default_factory=dict)
    held: Dump | None = None  # faulthandler's dump, taken during the stall


class LoopWatchdog:
    def __init__(
        self,
        registry: HeartbeatRegistry,
        *,
        threshold_seconds: float = DEFAULT_THRESHOLD_SECONDS,
        poll_seconds: float = POLL_SECONDS,
        resample_seconds: float = RESAMPLE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        gc_pauses: GcPauseRecorder | None = None,
        counters: Callable[[], Counters] | None = None,
        stack_dump: bool | None = None,
    ) -> None:
        self._registry = registry
        self._threshold = threshold_seconds
        self._poll = poll_seconds
        self._resample = resample_seconds
        self._clock = clock
        self._gc = gc_pauses or GC_PAUSES
        self._counters = counters
        self._dump_wanted = stack_dump_enabled() if stack_dump is None else stack_dump
        self._dump: HeldStackDump | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sampler: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id = 0
        self._own_ident = 0
        self._last_ack = clock()
        self._last_poll = self._last_ack
        # Readings of the last few seconds, newest last; the one just before a stall is its
        # baseline. An immutable tuple the sampler thread replaces, so no reader can see it change.
        self._history: tuple[Counters, ...] = ()
        self._history_len = int(threshold_seconds / poll_seconds) + HISTORY_MARGIN
        self._episode: _Episode | None = None
        self._stop_join = STOP_JOIN_SECONDS

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Watch ``loop`` (default: the running one); call it from the loop's own thread."""
        self._loop = loop or asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        self._last_ack = self._clock()
        self._last_poll = self._last_ack
        self._history = ()
        self._episode = None
        self._gc.install()
        if self._counters is None:
            probe = CounterProbe(
                loop_native_id=threading.get_native_id(), gc_pauses=self._gc, clock=self._clock
            )
            self._counters = probe.read
        if self._dump_wanted:
            # Dumps fire when this thread is away for the timeout. That has to be shorter than the
            # time that counts as a stall (and its poll), or a hold-up just over the threshold
            # would be a stall with no dump.
            timeout = max(self._threshold - 2 * self._poll, 2 * self._poll)
            dump = HeldStackDump(timeout=timeout)
            self._dump = dump if dump.start() else None
        self._stop.clear()
        self._sampler = threading.Thread(
            target=self._run_sampler, name="loop-watchdog-sampler", daemon=True
        )
        self._thread = threading.Thread(target=self._run, name="loop-watchdog", daemon=True)
        self._sampler.start()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in (self._thread, self._sampler):
            if thread is not None:
                thread.join(timeout=self._stop_join)
        dump, self._dump = self._dump, None
        if dump is not None:
            if self._thread is not None and self._thread.is_alive():
                # Still inside a poll: closing the file under it could leave the timer armed on a
                # descriptor that is then reused. The file is left to the process.
                logger.warning("loop watchdog did not stop in time; its stack dump stays armed")
            else:
                dump.close()
        self._gc.uninstall()

    def _ack(self) -> None:  # runs on the loop thread
        self._last_ack = self._clock()

    def _run(self) -> None:
        loop = self._loop
        assert loop is not None
        self._own_ident = threading.get_ident()
        while not self._stop.wait(self._poll):
            try:
                loop.call_soon_threadsafe(self._ack)
            except RuntimeError:  # the loop is closed: the worker is shutting down
                return
            try:
                self._poll_once()
            except Exception:
                # Diagnostics must never take the watchdog down with them.
                logger.exception("loop watchdog could not record a stall")

    def _run_sampler(self) -> None:
        """Read the counters on a thread of their own.

        Each reading gives the GIL away a dozen times (files under ``/proc``), and when other
        threads are busy every one of those costs a few milliseconds: on the watchdog thread that
        would make the watchdog late, which is what it measures.
        """
        while not self._stop.wait(self._poll):
            try:
                self._remember()
            except Exception:
                logger.debug("loop watchdog could not read its counters", exc_info=True)

    def _remember(self) -> None:
        self._history = (*self._history[-(self._history_len - 1) :], self._read())

    def _read(self) -> Counters:
        try:
            assert self._counters is not None
            return self._counters()
        except Exception:
            logger.debug("loop watchdog could not read its counters", exc_info=True)
            return Counters(taken=self._clock())

    def _baseline(self, started: float) -> Counters | None:
        """The newest reading from before ``started``, else the oldest there is."""
        history = self._history
        for reading in reversed(history):
            if reading.taken <= started:
                return reading
        return history[0] if history else None

    def _poll_once(self) -> None:
        now = self._clock()
        # How long since this thread last started a poll: about one poll when all is well, far more
        # when a thread inside a long GIL-holding call (or a host that did not run the process)
        # held it up. Measured from the *start* of the previous poll on purpose: a hold-up that
        # catches this thread in the middle of a poll is as real as one that catches it asleep.
        away = now - self._last_poll
        self._last_poll = now
        held_up = away >= self._threshold
        # Time since the last sign of life. The loop can answer a late acknowledgement before this
        # thread looks, so the watchdog's own lateness counts as well.
        gap = max(now - self._last_ack, away)
        dump = self._dump
        dumped = dump.rearm(check=away >= dump.timeout) if dump is not None else None
        episode = self._episode
        if gap < self._threshold:
            if episode is not None:
                self._episode = None
                self._finish(episode, now)
            return
        if episode is None:
            episode = self._episode = _Episode(started=now - gap, base=self._baseline(now - gap))
        if held_up:
            episode.scope = "process"
        if dumped is not None:
            episode.held = dumped
        if episode.last_report is None or now - episode.last_report >= self._resample:
            self._sample(episode, gap)
            episode.last_report = now

    def _sample(self, episode: _Episode, gap: float) -> None:
        loop_stack, episode.stacks = self._stacks()
        episode.names = {t.ident: t.name for t in threading.enumerate() if t.ident is not None}
        # What is known so far, so a stall that never ends (a hang) is explained too; the final
        # record replaces it. The first sample of an episode counts it; if recording it fails,
        # the next poll retries.
        self._registry.note_stall(
            gap,
            loop_stack,
            new_episode=episode.last_report is None,
            evidence=self._explain(episode, gap, self._read(), ongoing=True),
        )
        logger.warning(
            "event loop blocked for %.1fs; running (deepest first): %s",
            gap,
            " | ".join(loop_stack),
        )

    def _stacks(self) -> tuple[list[str], dict[int, list[str]]]:
        """The loop thread's stack and every thread's, as locations (``_explain`` drops ours)."""
        frames = sys._current_frames()
        loop_frame = frames.get(self._loop_thread_id)
        loop_stack = stack_of(loop_frame, limit=STACK_FRAMES) if loop_frame is not None else []
        return loop_stack, {
            ident: stack_of(frame, limit=THREAD_STACK_FRAMES) for ident, frame in frames.items()
        }

    def _finish(self, episode: _Episode, now: float) -> None:
        """The loop answered again: record how long the stall really lasted and what explains it."""
        seconds = max(now - episode.started - self._poll, 0.0)
        evidence = self._explain(episode, seconds, self._read())
        self._registry.note_stall(seconds, evidence=evidence)
        if evidence is None:
            return
        self._registry.note_stall_cause(str(evidence["cause"]))
        logger.warning(
            "event loop stall over after %.1fs: cause=%s scope=%s cpu=%s gc=%s host=%s",
            seconds,
            evidence["cause"],
            evidence["scope"],
            evidence["cpu"],
            evidence["gc"],
            evidence["host"],
        )

    def _explain(
        self, episode: _Episode, seconds: float, reading: Counters, *, ongoing: bool = False
    ) -> dict[str, Any] | None:
        try:
            base = episode.base
            usage = usage_between(base, reading) if base is not None else Usage.unknown()
            # The watchdog's own threads are the observers, never suspects.
            own = {self._own_ident}
            if self._sampler is not None and self._sampler.ident is not None:
                own.add(self._sampler.ident)
            cpu = {i: seconds for i, seconds in usage.thread_cpu.items() if i not in own}
            usage = replace(usage, thread_cpu=cpu)
            held = episode.held
            stacks = held.stacks if held is not None else episode.stacks
            return describe_stall(
                seconds=seconds,
                scope=episode.scope,
                usage=usage,
                loop_ident=self._loop_thread_id,
                stacks={ident: stack for ident, stack in stacks.items() if ident not in own},
                # live threads by their `threading` name, a thread that ended by the dump's
                names={**(held.names if held is not None else {}), **episode.names},
                stacks_during_stall=held is not None,
                slowest_gc=self._gc.slowest_since(base.taken) if base is not None else None,
                ongoing=ongoing,
            )
        except Exception:
            logger.exception("loop watchdog could not explain a stall")
            return None
