from __future__ import annotations

import json
from typing import Any

import httpx
from hypertrade.config import Settings
from hypertrade.providers.codex import CodexResponsesChatProvider
from hypertrade.providers.runtime import ProviderRuntime


def test_codex_provider_status_reads_codex_cli_auth_without_exposing_token(tmp_path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"tokens": {"access_token": "codex-secret-token"}}),
        encoding="utf-8",
    )

    runtime = ProviderRuntime(
        Settings(
            DEEPSEEK_API_KEY="",
            CODEX_API_KEY="",
            CODEX_AUTH_JSON=auth_path,
            CODEX_MODEL="gpt-5.4",
        )
    )

    providers = runtime.list_providers(selected="codex")
    codex = next(provider for provider in providers if provider["name"] == "codex")

    assert codex["display_name"] == "Codex"
    assert codex["enabled"] is True
    assert codex["default"] is True
    assert codex["model"] == "gpt-5.4"
    assert codex["key_status"] == "configured"
    assert "codex-secret-token" not in str(codex)

    chat_provider = runtime.get_chat_provider(selected="codex")

    assert chat_provider is not None
    assert chat_provider.name == "codex"
    assert chat_provider.model == "gpt-5.4"


def test_codex_default_model_options_include_gpt_5_5() -> None:
    runtime = ProviderRuntime(Settings(DEEPSEEK_API_KEY="", CODEX_API_KEY="codex-token"))

    providers = runtime.list_providers(selected="codex")
    codex = next(provider for provider in providers if provider["name"] == "codex")

    assert codex["model_options"] == ["gpt-5.4", "gpt-5.5", "gpt-5.4-mini"]


def test_codex_provider_accepts_hermes_openai_codex_alias(tmp_path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"providers": {"openai-codex": {"tokens": {"access_token": "alias-token"}}}}),
        encoding="utf-8",
    )

    runtime = ProviderRuntime(
        Settings(DEEPSEEK_API_KEY="", CODEX_API_KEY="", CODEX_AUTH_JSON=auth_path)
    )

    providers = runtime.list_providers(selected="openai-codex")
    codex = next(provider for provider in providers if provider["name"] == "codex")
    chat_provider = runtime.get_chat_provider(selected="openai-codex")

    assert codex["default"] is True
    assert codex["enabled"] is True
    assert chat_provider is not None
    assert chat_provider.name == "codex"


def test_codex_provider_status_supports_selected_model_options() -> None:
    runtime = ProviderRuntime(
        Settings(
            DEEPSEEK_API_KEY="",
            CODEX_API_KEY="codex-secret-token",
            CODEX_MODEL="gpt-5.4",
            CODEX_MODEL_OPTIONS="gpt-5.4,gpt-5.4-mini",
        )
    )

    providers = runtime.list_providers(
        selected="codex",
        selected_models={"codex": "gpt-5.4-mini"},
    )
    codex = next(provider for provider in providers if provider["name"] == "codex")

    assert codex["model"] == "gpt-5.4-mini"
    assert codex["model_options"] == ["gpt-5.4", "gpt-5.4-mini"]
    assert "codex-secret-token" not in str(codex)

    chat_provider = runtime.get_chat_provider(
        selected="codex",
        selected_model="gpt-5.4-mini",
    )

    assert chat_provider is not None
    assert chat_provider.model == "gpt-5.4-mini"


def test_codex_provider_posts_responses_payload_and_parses_tool_call() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call_market",
                        "name": "market_summary",
                        "arguments": "{}",
                    }
                ]
            },
        )

    provider = CodexResponsesChatProvider(
        api_key="codex-secret-token",
        base_url="https://chatgpt.test/backend-api/codex",
        model="gpt-5.4",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = provider.chat(
        [
            {"role": "system", "content": "You are HyperTrade."},
            {"role": "user", "content": "请做行情归纳"},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "market_summary",
                    "description": "Fetch all-market state.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        ],
    )

    assert captured["url"] == "https://chatgpt.test/backend-api/codex/responses"
    assert captured["authorization"] == "Bearer codex-secret-token"
    assert captured["payload"]["model"] == "gpt-5.4"
    assert captured["payload"]["input"][0] == {
        "role": "developer",
        "content": "You are HyperTrade.",
    }
    assert captured["payload"]["tools"] == [
        {
            "type": "function",
            "name": "market_summary",
            "description": "Fetch all-market state.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    ]
    assert captured["payload"]["tool_choice"] == "auto"
    assert response.content == ""
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "call_market"
    assert response.tool_calls[0].name == "market_summary"
    assert response.tool_calls[0].arguments == {}


def test_codex_provider_maps_tool_outputs_back_to_responses_input() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "# 市场归纳\n\n已基于工具结果完成。",
                            }
                        ],
                    }
                ]
            },
        )

    provider = CodexResponsesChatProvider(
        api_key="codex-secret-token",
        base_url="https://chatgpt.test/backend-api/codex/",
        model="gpt-5.4",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = provider.chat(
        [
            {"role": "user", "content": "请做行情归纳"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_market",
                        "type": "function",
                        "function": {"name": "market_summary", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_market", "content": "{\"top_movers\": []}"},
        ],
    )

    assert {
        "type": "function_call",
        "call_id": "call_market",
        "name": "market_summary",
        "arguments": "{}",
    } in captured["payload"]["input"]
    assert {
        "type": "function_call_output",
        "call_id": "call_market",
        "output": "{\"top_movers\": []}",
    } in captured["payload"]["input"]
    assert response.content == "# 市场归纳\n\n已基于工具结果完成。"
    assert response.tool_calls == []
