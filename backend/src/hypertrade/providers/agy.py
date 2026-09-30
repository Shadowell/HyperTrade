"""Google Antigravity (AGY) CLI chat provider.

Adapts the `agy` CLI non-interactive execution to the HyperTrade `ChatProvider` protocol.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from hypertrade.providers.chat import ChatResponse, TokenUsage, ToolCallRequest


def resolve_agy_binary(*, bin_path: str = "agy") -> str:
    """Resolve the agy CLI binary executable path."""
    explicit = bin_path.strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        found = shutil.which(explicit)
        if found:
            return found

    for candidate in ("/usr/local/bin/agy", str(Path.home() / ".local" / "bin" / "agy")):
        p = Path(candidate)
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return ""


def resolve_agy_access(*, bin_path: str = "agy", auth_token_path: Path | None = None) -> bool:
    """Check if agy binary is available and credentials exist."""
    bin_resolved = resolve_agy_binary(bin_path=bin_path)
    if not bin_resolved:
        return False

    default_token = Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    token_candidates = [
        (auth_token_path or default_token).expanduser(),
        (Path.home() / ".gemini" / "gemini-credentials.json").expanduser(),
        (Path.home() / ".gemini" / "antigravity-cli" / "settings.json").expanduser(),
    ]
    return any(p.is_file() for p in token_candidates) or bool(bin_resolved)


class AgyChatProvider:
    """Adapter for Antigravity (AGY) non-interactive agent execution."""

    def __init__(
        self,
        *,
        model: str = "gemini-3.8-flash-high",
        bin_path: str = "agy",
        timeout_seconds: float = 120.0,
        auth_token_path: Path | None = None,
    ) -> None:
        self.name = "agy"
        self.model = model
        self._bin_path = resolve_agy_binary(bin_path=bin_path) or bin_path
        self._timeout_seconds = timeout_seconds
        self._auth_token_path = auth_token_path

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        prompt = self._build_prompt(messages, tools)
        cmd = [
            self._bin_path,
            "--model",
            self.model,
            "--output-format",
            "json",
            f"--print={prompt}",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(f"AGY CLI call timed out after {self._timeout_seconds}s") from exc
        except FileNotFoundError as exc:
            raise RuntimeError(f"AGY CLI binary not found at '{self._bin_path}'") from exc

        return self._parse_output(result.stdout, result.stderr, result.returncode, tools=tools)

    def _build_prompt(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> str:
        parts: list[str] = []

        system_parts: list[str] = []
        for msg in messages:
            if msg.get("role") in {"system", "developer"}:
                content = str(msg.get("content") or "").strip()
                if content:
                    system_parts.append(content)

        if tools:
            tool_descriptions = json.dumps(tools, ensure_ascii=False, indent=2)
            tool_prompt = (
                "You have access to the following tools:\n"
                f"```json\n{tool_descriptions}\n```\n"
                "If you need to call a tool, you MUST output a json markdown block with:\n"
                "```json\n"
                "{\n"
                '  "tool_calls": [\n'
                '    {"name": "<tool_name>", "arguments": { ... }}\n'
                "  ]\n"
                "}\n"
                "```\n"
                "If no tool call is needed, provide your final direct response as plain text."
            )
            system_parts.append(tool_prompt)

        if system_parts:
            parts.append("[System Instructions]\n" + "\n\n".join(system_parts))

        parts.append("[Conversation History]")
        for msg in messages:
            role = msg.get("role")
            if role in {"system", "developer"}:
                continue
            if role == "tool":
                call_id = msg.get("tool_call_id", "")
                content = msg.get("content", "")
                parts.append(f"Tool Result ({call_id}):\n{content}")
            elif role == "assistant":
                content = msg.get("content", "")
                calls = msg.get("tool_calls")
                if calls:
                    serialized_calls = json.dumps(calls, ensure_ascii=False)
                    parts.append(f"Assistant (Tool Calls):\n{serialized_calls}")
                elif content:
                    parts.append(f"Assistant: {content}")
            elif role == "user":
                parts.append(f"User: {msg.get('content', '')}")

        return "\n\n".join(parts)

    def _parse_output(
        self,
        stdout: str,
        stderr: str,
        returncode: int,
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        stdout_str = stdout.strip()
        data: dict[str, Any] = {}
        if stdout_str:
            with contextlib.suppress(json.JSONDecodeError):
                data = json.loads(stdout_str)

        if not data and returncode != 0:
            error_msg = stderr.strip() or stdout_str or f"AGY process failed with code {returncode}"
            return ChatResponse(content=f"[AGY Error: {error_msg}]")

        response_text = str(data.get("response") or "").strip()
        usage_data = data.get("usage") or {}
        usage = TokenUsage(
            input_tokens=int(usage_data.get("input_tokens") or 0),
            output_tokens=int(usage_data.get("output_tokens") or 0),
            reasoning_tokens=int(usage_data.get("thinking_tokens") or 0),
            total_tokens=int(usage_data.get("total_tokens") or 0),
            reported=bool(usage_data),
        )

        tool_calls: list[ToolCallRequest] = []
        if tools and response_text:
            parsed_calls = self._extract_tool_calls(response_text)
            if parsed_calls:
                tool_calls.extend(parsed_calls)
                # If tool calls were extracted from json block, clear content
                response_text = ""

        return ChatResponse(
            content=response_text,
            tool_calls=tool_calls,
            usage=usage,
        )

    def _extract_tool_calls(self, text: str) -> list[ToolCallRequest]:
        calls: list[ToolCallRequest] = []
        # Match ```json ... ``` blocks
        json_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        candidates = list(json_blocks)
        if not candidates and text.startswith("{") and text.endswith("}"):
            candidates.append(text)

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue

            if isinstance(parsed, dict):
                raw_calls = parsed.get("tool_calls")
                if isinstance(raw_calls, list):
                    for call in raw_calls:
                        if isinstance(call, dict) and "name" in call:
                            calls.append(
                                ToolCallRequest(
                                    id=str(call.get("id") or f"call_{uuid4().hex[:12]}"),
                                    name=str(call["name"]),
                                    arguments=dict(call.get("arguments") or {}),
                                )
                            )
                elif "name" in parsed and "arguments" in parsed:
                    calls.append(
                        ToolCallRequest(
                            id=str(parsed.get("id") or f"call_{uuid4().hex[:12]}"),
                            name=str(parsed["name"]),
                            arguments=dict(parsed.get("arguments") or {}),
                        )
                    )
        return calls
