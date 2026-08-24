"""Provider adapter layer for chat models.

HyperTrade keeps model-specific details here so Agent planning can depend on a
small `ChatProvider` protocol instead of DeepSeek/OpenAI/OpenRouter/Qwen SDK
details. This is the same boundary many enterprise Agent systems use: provider
configuration is outside the Agent graph, while tool schemas and messages stay
inside the graph.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class TokenUsage:
    """Provider-reported usage normalized without inventing missing counts."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    reported: bool = False

    def to_dict(self) -> dict[str, int | bool]:
        total = self.total_tokens or self.input_tokens + self.output_tokens
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": total,
            "reported": self.reported,
        }


@dataclass
class ChatResponse:
    content: str
    reasoning_content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)


class ChatProvider(Protocol):
    """Minimal interface needed by the Agent planner."""

    name: str
    model: str

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse: ...


class OpenAICompatibleChatProvider:
    """Adapter for providers that implement the OpenAI chat-completions shape."""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        client: Any | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._client = client if client is not None else OpenAI(api_key=api_key, base_url=base_url)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            # Function/tool calling is enabled only when the planner supplies
            # tool schemas. Plain chat calls can reuse the same provider adapter.
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        response = self._client.chat.completions.create(**kwargs)
        return _response_to_chat_response(response)

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        on_delta: Callable[[str], None],
    ) -> ChatResponse:
        """Streaming chat: content deltas are emitted via on_delta as they
        arrive; tool-call deltas accumulate into complete calls; the returned
        ChatResponse is equivalent to the non-streaming chat().

        reasoning_content accumulates but is never emitted through on_delta —
        private reasoning must not leak into operator-visible streams.
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        stream = self._client.chat.completions.create(**kwargs)
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        # tool_call deltas arrive split across chunks, keyed by their index.
        tool_acc: dict[int, dict[str, str]] = {}
        usage = TokenUsage()
        for chunk in stream:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = _openai_token_usage(chunk_usage)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            reasoning = str(getattr(delta, "reasoning_content", "") or "")
            if reasoning:
                reasoning_parts.append(reasoning)
            content_delta = str(getattr(delta, "content", "") or "")
            if content_delta:
                content_parts.append(content_delta)
                on_delta(content_delta)
            for tc_delta in getattr(delta, "tool_calls", None) or []:
                index = int(getattr(tc_delta, "index", 0) or 0)
                acc = tool_acc.setdefault(index, {"id": "", "name": "", "arguments": ""})
                tc_id = str(getattr(tc_delta, "id", "") or "")
                if tc_id:
                    acc["id"] = tc_id
                function = getattr(tc_delta, "function", None)
                if function is not None:
                    fn_name = str(getattr(function, "name", "") or "")
                    if fn_name:
                        acc["name"] = fn_name
                    fn_args = getattr(function, "arguments", None)
                    if fn_args:
                        acc["arguments"] = acc["arguments"] + str(fn_args)
        tool_calls: list[ToolCallRequest] = []
        for index in sorted(tool_acc):
            acc = tool_acc[index]
            raw = acc["arguments"] or "{}"
            try:
                args: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                # Tool arguments come from the model, so they are treated as
                # untrusted input and normalized before reaching AgentKernel.
                args = {}
            if not isinstance(args, dict):
                args = {}
            tool_calls.append(
                ToolCallRequest(id=acc["id"] or f"call_{index}", name=acc["name"], arguments=args)
            )
        return ChatResponse(
            content="".join(content_parts),
            reasoning_content="".join(reasoning_parts),
            tool_calls=tool_calls,
            usage=usage,
        )


def _response_to_chat_response(response: Any) -> ChatResponse:
    """Normalize one non-streaming completion into ChatResponse."""
    message = response.choices[0].message
    tool_calls: list[ToolCallRequest] = []
    if message.tool_calls:
        for tc in message.tool_calls:
            raw = tc.function.arguments or "{}"
            try:
                args: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                # Tool arguments come from the model, so they are treated as
                # untrusted input and normalized before reaching AgentKernel.
                args = {}
            if not isinstance(args, dict):
                args = {}
            tool_calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, arguments=args))
    reasoning_content = str(getattr(message, "reasoning_content", "") or "")
    return ChatResponse(
        content=message.content or "",
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
        usage=_openai_token_usage(getattr(response, "usage", None)),
    )


def _openai_token_usage(value: Any) -> TokenUsage:
    """Normalize Chat Completions usage objects from OpenAI-compatible SDKs."""

    if value is None:
        return TokenUsage()
    prompt_details = _usage_value(value, "prompt_tokens_details")
    completion_details = _usage_value(value, "completion_tokens_details")
    input_tokens = _usage_int(value, "prompt_tokens", "input_tokens")
    output_tokens = _usage_int(value, "completion_tokens", "output_tokens")
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=_usage_int(prompt_details, "cached_tokens")
        or _usage_int(value, "prompt_cache_hit_tokens", "cache_read_input_tokens"),
        reasoning_tokens=_usage_int(completion_details, "reasoning_tokens"),
        total_tokens=_usage_int(value, "total_tokens") or input_tokens + output_tokens,
        reported=True,
    )


def _usage_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _usage_int(value: Any, *keys: str) -> int:
    for key in keys:
        raw = _usage_value(value, key)
        if raw is None:
            continue
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            continue
    return 0
