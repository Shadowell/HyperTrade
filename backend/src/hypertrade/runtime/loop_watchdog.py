"""Name the call that holds the worker's event loop.

The heartbeat reports *that* the loop was blocked and for how long (``event_loop_lag_max_seconds``),
not *what* blocked it, and the production host is not reachable from a debugging session. This
watchdog runs on its own thread, asks the loop to acknowledge a callback twice a second and, when
the acknowledgement is more than ``threshold_seconds`` late, samples the loop thread's stack and
hands it to the heartbeat registry, so ``/api/healthz`` can say which function was running.

Only ``file:line function`` is recorded (deepest frame first), never source lines or variable
values, so a stack cannot carry a credential or customer data.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
import traceback
from collections.abc import Callable
from types import FrameType

from hypertrade.runtime.heartbeat import HeartbeatRegistry

logger = logging.getLogger("hypertrade.loop_watchdog")

DEFAULT_THRESHOLD_SECONDS = 3.0
POLL_SECONDS = 0.5
# A long stall is re-sampled this often: the blocking call can change while it lasts.
RESAMPLE_SECONDS = 15.0
STACK_FRAMES = 10


def format_stack(frame: FrameType, *, limit: int = STACK_FRAMES) -> list[str]:
    """``file:line function`` for the deepest ``limit`` non-asyncio frames, deepest first."""
    frames = [
        item
        for item in traceback.extract_stack(frame)
        if "/asyncio/" not in item.filename.replace("\\", "/")
    ]
    deepest_first = reversed(frames[-limit:])
    return [f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in deepest_first]


class LoopWatchdog:
    def __init__(
        self,
        registry: HeartbeatRegistry,
        *,
        threshold_seconds: float = DEFAULT_THRESHOLD_SECONDS,
        poll_seconds: float = POLL_SECONDS,
        resample_seconds: float = RESAMPLE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._threshold = threshold_seconds
        self._poll = poll_seconds
        self._resample = resample_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id = 0
        self._last_ack = clock()

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Watch ``loop`` (default: the running one); call it from the loop's own thread."""
        self._loop = loop or asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        self._last_ack = self._clock()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="loop-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _ack(self) -> None:  # runs on the loop thread
        self._last_ack = self._clock()

    def _run(self) -> None:
        assert self._loop is not None
        episode_start: float | None = None
        last_report: float | None = None
        while not self._stop.wait(self._poll):
            try:
                self._loop.call_soon_threadsafe(self._ack)
            except RuntimeError:  # the loop is closed: the worker is shutting down
                return
            now = self._clock()
            gap = now - self._last_ack
            if gap < self._threshold:
                if episode_start is not None:
                    # The loop answered again: record how long the stall really lasted.
                    self._registry.note_stall(now - episode_start - self._poll)
                    episode_start = last_report = None
                continue
            if episode_start is None:
                episode_start = now - gap
            if last_report is None or now - last_report >= self._resample:
                frame = sys._current_frames().get(self._loop_thread_id)
                if frame is not None:
                    stack = format_stack(frame)
                    self._registry.note_stall(gap, stack, new_episode=last_report is None)
                    logger.warning(
                        "event loop blocked for %.1fs; running (deepest first): %s",
                        gap,
                        " | ".join(stack),
                    )
                last_report = now
