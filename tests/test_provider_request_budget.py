"""Explicit request budget for the OpenAI-compatible providers.

The settings default to the OpenAI SDK's own timeout and retry count, so shipping them changes no
behaviour. These tests pin that equality (the guarantee that nothing moves unless an operator opts
in) and that every OpenAI-compatible provider actually receives the configured budget.
"""

from typing import Any

import httpx
import pytest
from hypertrade.config import Settings
from hypertrade.providers.chat import OpenAICompatibleChatProvider
from hypertrade.providers.deepseek import DeepSeekClient
from hypertrade.providers.runtime import ProviderRuntime
from openai import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT
from pydantic import ValidationError


def _settings(**overrides: Any) -> Settings:
    return Settings(DEEPSEEK_API_KEY="", **overrides)


def test_defaults_equal_the_openai_sdk_defaults_so_nothing_changes_unless_set() -> None:
    settings = _settings()

    assert settings.provider_request_timeout_seconds == DEFAULT_TIMEOUT.read
    assert settings.provider_max_retries == DEFAULT_MAX_RETRIES


def test_a_provider_built_without_a_budget_keeps_the_sdk_defaults() -> None:
    provider = OpenAICompatibleChatProvider(
        name="x", api_key="k", base_url="http://localhost:1/v1", model="m"
    )

    client = provider._client
    assert client.timeout == DEFAULT_TIMEOUT
    assert client.max_retries == DEFAULT_MAX_RETRIES


def test_the_budget_sets_read_write_pool_but_keeps_the_short_connect_timeout() -> None:
    provider = OpenAICompatibleChatProvider(
        name="x",
        api_key="k",
        base_url="http://localhost:1/v1",
        model="m",
        timeout_seconds=45.0,
        max_retries=0,
    )

    assert provider._client.timeout == httpx.Timeout(45.0, connect=DEFAULT_TIMEOUT.connect)
    assert provider._client.max_retries == 0


def test_an_injected_client_is_used_as_is() -> None:
    sentinel = object()
    provider = OpenAICompatibleChatProvider(
        name="x",
        api_key="k",
        base_url="u",
        model="m",
        client=sentinel,
        timeout_seconds=1.0,
        max_retries=9,
    )
    assert provider._client is sentinel


def test_deepseek_client_forwards_the_budget() -> None:
    provider = DeepSeekClient(
        api_key="k",
        base_url="http://localhost:1/v1",
        model="m",
        timeout_seconds=30.0,
        max_retries=1,
    )

    assert provider._client.timeout == httpx.Timeout(30.0, connect=DEFAULT_TIMEOUT.connect)
    assert provider._client.max_retries == 1


@pytest.mark.parametrize(
    ("provider", "env"),
    [
        ("deepseek", {"DEEPSEEK_API_KEY": "k"}),
        ("openai", {"OPENAI_API_KEY": "k"}),
        ("openrouter", {"OPENROUTER_API_KEY": "k", "OPENROUTER_MODEL": "m"}),
        ("qwen", {"QWEN_API_KEY": "k"}),
        ("vide_coding", {"VIDE_CODING_API_KEY": "k"}),
    ],
)
def test_every_openai_compatible_provider_receives_the_configured_budget(
    provider: str, env: dict[str, str]
) -> None:
    settings = Settings(
        ACTIVE_CHAT_PROVIDER=provider,
        PROVIDER_REQUEST_TIMEOUT_SECONDS=75,
        PROVIDER_MAX_RETRIES=4,
        **{"DEEPSEEK_API_KEY": "", **env},
    )

    built = ProviderRuntime(settings).get_chat_provider()

    assert isinstance(built, OpenAICompatibleChatProvider)
    assert built.name == provider
    assert built._client.timeout == httpx.Timeout(75.0, connect=DEFAULT_TIMEOUT.connect)
    assert built._client.max_retries == 4


@pytest.mark.parametrize(
    "overrides",
    [
        {"PROVIDER_REQUEST_TIMEOUT_SECONDS": 0},
        {"PROVIDER_REQUEST_TIMEOUT_SECONDS": 3601},
        {"PROVIDER_MAX_RETRIES": -1},
        {"PROVIDER_MAX_RETRIES": 11},
    ],
)
def test_out_of_range_budgets_are_rejected_at_startup(overrides: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        _settings(**overrides)
