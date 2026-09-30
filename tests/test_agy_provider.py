"""Tests for Google Antigravity (AGY) chat provider."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from hypertrade.config import Settings
from hypertrade.providers.agy import (
    AgyChatProvider,
    resolve_agy_access,
    resolve_agy_binary,
)
from hypertrade.providers.runtime import ProviderRuntime


def test_resolve_agy_binary_with_custom_path(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake_agy"
    fake_bin.write_text("#!/bin/sh\necho ok\n")
    fake_bin.chmod(0o755)

    resolved = resolve_agy_binary(bin_path=str(fake_bin))
    assert resolved == str(fake_bin)


def test_resolve_agy_access_with_token(tmp_path: Path) -> None:
    fake_bin = tmp_path / "agy"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(0o755)

    token_file = tmp_path / "token.json"
    token_file.write_text('{"token": "fake"}')

    assert resolve_agy_access(bin_path=str(fake_bin), auth_token_path=token_file) is True


def test_agy_chat_plain_text_response() -> None:
    provider = AgyChatProvider(model="gemini-3.8-flash-high", bin_path="agy")

    fake_output = json.dumps({
        "status": "SUCCESS",
        "response": "Gemini 3.8 Flash High analysis result.",
        "usage": {
            "input_tokens": 120,
            "output_tokens": 45,
            "thinking_tokens": 10,
            "total_tokens": 165,
        },
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=fake_output,
            stderr="",
        )

        messages = [
            {"role": "system", "content": "You are a quantitative research agent."},
            {"role": "user", "content": "Analyze ETH volatility."},
        ]
        resp = provider.chat(messages)

        assert resp.content == "Gemini 3.8 Flash High analysis result."
        assert len(resp.tool_calls) == 0
        assert resp.usage.input_tokens == 120
        assert resp.usage.output_tokens == 45
        assert resp.usage.reasoning_tokens == 10
        assert resp.usage.total_tokens == 165


def test_agy_chat_tool_call_response() -> None:
    provider = AgyChatProvider(model="gemini-3.8-flash-high", bin_path="agy")

    tool_call_json = {
        "tool_calls": [
            {
                "id": "call_klines_001",
                "name": "market_candles",
                "arguments": {"inst_id": "ETH-USDT-SWAP", "bar": "1H", "limit": 100},
            }
        ]
    }
    fake_output = json.dumps({
        "status": "SUCCESS",
        "response": f"```json\n{json.dumps(tool_call_json)}\n```",
        "usage": {
            "input_tokens": 200,
            "output_tokens": 60,
            "thinking_tokens": 15,
            "total_tokens": 260,
        },
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=fake_output,
            stderr="",
        )

        messages = [
            {"role": "user", "content": "Fetch ETH 1H candles."},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "market_candles",
                    "parameters": {"type": "object", "properties": {"inst_id": {"type": "string"}}},
                },
            }
        ]
        resp = provider.chat(messages, tools=tools)

        assert resp.content == ""
        assert len(resp.tool_calls) == 1
        call = resp.tool_calls[0]
        assert call.name == "market_candles"
        assert call.arguments["inst_id"] == "ETH-USDT-SWAP"
        assert call.arguments["bar"] == "1H"


def test_agy_chat_error_fallback() -> None:
    provider = AgyChatProvider(model="gemini-3.8-flash-high", bin_path="agy")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Rate limit exceeded",
        )

        resp = provider.chat([{"role": "user", "content": "test"}])
        assert "[AGY Error: Rate limit exceeded]" in resp.content


def test_provider_runtime_lists_and_activates_agy(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake_agy"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(0o755)

    settings = Settings(
        ACTIVE_CHAT_PROVIDER="agy",
        AGY_BIN_PATH=str(fake_bin),
        AGY_MODEL="gemini-3.8-flash-high",
    )
    runtime = ProviderRuntime(settings)

    providers = runtime.list_providers()
    agy_info = next(p for p in providers if p["name"] == "agy")
    assert agy_info["display_name"] == "Antigravity (AGY / Gemini)"
    assert agy_info["model"] == "gemini-3.8-flash-high"
    assert agy_info["default"] is True
    assert agy_info["enabled"] is True

    # Validate model choice
    validated = runtime.validate_model_choice("agy", "gemini-3.8-flash-high")
    assert validated == "gemini-3.8-flash-high"

    # Gemini alias resolution
    assert runtime.normalize_provider_name("gemini") == "agy"
    assert runtime.normalize_provider_name("antigravity") == "agy"

    # Get chat provider
    provider = runtime.get_chat_provider()
    assert isinstance(provider, AgyChatProvider)
    assert provider.model == "gemini-3.8-flash-high"
