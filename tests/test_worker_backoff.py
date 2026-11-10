"""Unit tests for jittered exponential backoff controller."""

from __future__ import annotations

import random

from hypertrade.runtime.backoff import calculate_jittered_backoff


def test_zero_or_negative_idle_returns_zero() -> None:
    assert calculate_jittered_backoff(0) == 0.0
    assert calculate_jittered_backoff(-1) == 0.0


def test_exponential_growth_deterministic() -> None:
    rng = random.Random(42)
    # Consecutive idle = 1 -> target = 1.0 * 2^0 = 1.0
    val1 = calculate_jittered_backoff(1, base=1.0, rng=rng)
    assert 0.8 <= val1 <= 1.2

    # Consecutive idle = 2 -> target = 1.0 * 2^1 = 2.0
    val2 = calculate_jittered_backoff(2, base=1.0, rng=rng)
    assert 1.6 <= val2 <= 2.4

    # Consecutive idle = 3 -> target = 1.0 * 2^2 = 4.0
    val3 = calculate_jittered_backoff(3, base=1.0, rng=rng)
    assert 3.2 <= val3 <= 4.8


def test_backoff_respects_max_ceiling() -> None:
    rng = random.Random(123)
    val = calculate_jittered_backoff(20, base=1.0, max_interval=15.0, rng=rng)
    # Target capped at 15.0 with jitter
    assert val <= 15.0
