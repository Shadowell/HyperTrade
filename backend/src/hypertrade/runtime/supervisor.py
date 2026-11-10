"""Run each worker loop under a supervisor so one loop's crash never ends the process.

`worker.main` used to hand every loop straight to one `asyncio.gather`: an exception that escaped
any loop ended the process and, with it, every sibling loop until Docker restarted the container
(two such escapes were real: the OKX REST fallback and the RAG scanner). Each loop already catches
and journals its own per-iteration failures; this is the backstop for everything it does not
catch, including a loop that fails while it starts up.

A crashed loop is restarted in place after a jittered exponential delay. The delay resets once a
loop has stayed up for ``healthy_after`` seconds, so a loop that ran for an hour and then hit one
transient error comes back quickly, while one that fails on every start is retried at most every
``max_delay`` seconds instead of spinning. Shutdown (``CancelledError``) always passes through.
A loop that *returns* is left stopped: "forever" loops only return when they were told to.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable

from hypertrade.runtime.backoff import calculate_jittered_backoff

logger = logging.getLogger("hypertrade.supervisor")

LoopFactory = Callable[[], Awaitable[None]]
Journal = Callable[[str, Exception], Awaitable[None]]
CrashObserver = Callable[[str, Exception], None]

DEFAULT_BASE_DELAY_SECONDS = 1.0
DEFAULT_MAX_DELAY_SECONDS = 60.0
DEFAULT_HEALTHY_AFTER_SECONDS = 300.0


async def supervise(
    name: str,
    factory: LoopFactory,
    *,
    journal: Journal | None = None,
    on_crash: CrashObserver | None = None,
    base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    max_delay: float = DEFAULT_MAX_DELAY_SECONDS,
    healthy_after: float = DEFAULT_HEALTHY_AFTER_SECONDS,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    clock: Callable[[], float] = time.monotonic,
    rng: random.Random | None = None,
) -> None:
    """Keep ``factory()`` running until the process is cancelled.

    ``factory`` must build a *new* coroutine on every call (a coroutine object cannot be awaited
    twice), which is why loops are passed as factories rather than as coroutines.
    ``journal(component, exc)`` persists the crash; ``on_crash(name, exc)`` feeds in-memory
    liveness. Neither may break supervision, so failures in them are logged and dropped.
    """
    pause = sleep if sleep is not None else asyncio.sleep
    consecutive = 0
    while True:
        started = clock()
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            stayed_up = clock() - started
            consecutive = 1 if stayed_up >= healthy_after else consecutive + 1
            delay = calculate_jittered_backoff(
                consecutive, base=base_delay, max_interval=max_delay, rng=rng
            )
            logger.exception(
                "worker loop %s crashed after %.1fs (consecutive crash %d); restarting in %.1fs",
                name,
                stayed_up,
                consecutive,
                delay,
            )
            _notify(on_crash, name, exc)
            await _journal(journal, name, exc)
            await pause(delay)
            continue
        logger.warning("worker loop %s returned; it is not restarted", name)
        return


def _notify(observer: CrashObserver | None, name: str, exc: Exception) -> None:
    if observer is None:
        return
    try:
        observer(name, exc)
    except Exception:
        logger.warning("crash observer failed for %s", name, exc_info=True)


async def _journal(journal: Journal | None, name: str, exc: Exception) -> None:
    if journal is None:
        return
    try:
        await journal(f"worker.crash.{name}", exc)
    except Exception:
        logger.warning("could not journal the crash of %s", name, exc_info=True)
