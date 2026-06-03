"""Provider adapter layer for chat models.

HyperTrade keeps model-specific details here so Agent planning can depend on a
small `ChatProvider` protocol instead of DeepSeek/OpenAI/OpenRouter/Qwen SDK
details. This is the same boundary many enterprise Agent systems use: provider
configuration is outside the Agent graph, while tool schemas and messages stay
inside the graph.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import OpenAI


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatResponse:
    content: str
    reasoning_content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


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

    def __init__(self, *, name: str, api_key: str, base_url: str, model: str) -> None:
        self.name = name
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

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
        )
