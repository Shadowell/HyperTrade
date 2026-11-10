"""Jittered exponential backoff calculation for worker loop idle intervals."""

from __future__ import annotations

import random


def calculate_jittered_backoff(
    consecutive_idle: int,
    base: float = 1.0,
    max_interval: float = 30.0,
    jitter_factor: float = 0.2,
    *,
    rng: random.Random | None = None,
) -> float:
    """Calculate an exponential backoff sleep duration with bounded symmetric jitter.

    Args:
        consecutive_idle: Number of consecutive idle polling cycles without tasks.
        base: Initial baseline sleep duration in seconds (>= 0).
        max_interval: Upper ceiling for exponential backoff (>= base).
        jitter_factor: Proportion of randomized jitter (+/- percentage around target).
        rng: Optional Random instance for deterministic testing.

    Returns:
        Duration in seconds to sleep before the next polling tick.
    """
    if consecutive_idle <= 0:
        return 0.0

    target = min(max_interval, base * (2 ** (consecutive_idle - 1)))
    generator = rng if rng is not None else random

    jitter_delta = target * jitter_factor
    jittered = generator.uniform(target - jitter_delta, target + jitter_delta)
    return max(0.1, min(max_interval, round(jittered, 3)))
