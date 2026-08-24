"""Hermetic test defaults for the whole pytest suite.

Provider API keys from the developer's ``.env`` must never leak into tests:
before sprint-138 the mission planner silently called the real DeepSeek API
whenever a developer had a key configured, making mission tests
non-deterministic and cost-bearing. Explicit per-test Settings kwargs still
override these empty values (pydantic-settings: init > env > dotenv), so
tests that intentionally exercise provider code keep working by passing
their own keys.
"""

from __future__ import annotations

import pytest

_PROVIDER_KEY_ENV_VARS = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "QWEN_API_KEY",
    "VIDE_CODING_API_KEY",
    "CODEX_API_KEY",
)


@pytest.fixture(autouse=True)
def _hermetic_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _PROVIDER_KEY_ENV_VARS:
        monkeypatch.setenv(var, "")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
