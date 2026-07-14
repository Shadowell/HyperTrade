"""Codex Responses API chat provider.

Hermes exposes OpenAI Codex as an OAuth-backed ``openai-codex`` provider on
``https://chatgpt.com/backend-api/codex``. HyperTrade keeps a narrower boundary:
Codex may plan and write final text, while HyperTrade still owns tool execution,
policy checks, trace, RAG, and Memory auditability.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from hypertrade.providers.chat import ChatResponse, TokenUsage, ToolCallRequest


def resolve_codex_access_token(*, api_key: str = "", auth_json: Path | None = None) -> str:
    """Resolve a Codex bearer token without printing or persisting it.

    Resolution order mirrors the operator-facing setup: an explicit server-side
    secret wins, then a Codex/Hermes auth JSON file may provide OAuth
    ``access_token`` data. Refresh is intentionally not attempted here; expired
    credentials fail at the provider boundary instead of mutating another
    tool's auth store.
    """

    explicit = api_key.strip()
    if explicit:
        return explicit
    if auth_json is None:
        return ""
    path = auth_json.expanduser()
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return _token_from_auth_payload(payload)


class CodexResponsesChatProvider:
    """Adapter for Codex's Responses API function-calling shape."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 90.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.name = "codex"
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = http_client or httpx.Client(timeout=timeout_seconds)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": _messages_to_responses_input(messages),
            "store": False,
            # The ChatGPT Codex backend is stream-only. Buffering its SSE
            # response here keeps the provider contract synchronous while
            # HyperTrade retains control of every returned tool call.
            "stream": True,
        }
        instructions = _instructions_from_messages(messages)
        if instructions:
            payload["instructions"] = instructions
        if tools:
            payload["tools"] = _chat_tools_to_responses_tools(tools)
            payload["tool_choice"] = "auto"
        response = self._client.post(
            f"{self._base_url}/responses",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = _responses_payload_from_http_response(response)
        if not isinstance(data, dict):
            return ChatResponse(content="")
        return _parse_responses_payload(data)


def _token_from_auth_payload(payload: dict[str, Any]) -> str:
    for key in ("access_token", "api_key", "OPENAI_API_KEY"):
        token = payload.get(key)
        if isinstance(token, str) and token.strip():
            return token.strip()

    tokens = payload.get("tokens")
    if isinstance(tokens, dict):
        token = tokens.get("access_token")
        if isinstance(token, str) and token.strip():
            return token.strip()

    providers = payload.get("providers")
    if isinstance(providers, dict):
        state = providers.get("openai-codex") or providers.get("codex")
        if isinstance(state, dict):
            nested_tokens = state.get("tokens")
            if isinstance(nested_tokens, dict):
                token = nested_tokens.get("access_token")
                if isinstance(token, str) and token.strip():
                    return token.strip()

    pool = payload.get("credential_pool")
    if isinstance(pool, dict):
        entries = pool.get("openai-codex")
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                token = entry.get("access_token")
                if isinstance(token, str) and token.strip():
                    return token.strip()
    return ""


def _messages_to_responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        if role == "system":
            continue
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(message.get("tool_call_id") or ""),
                    "output": _coerce_content_text(message.get("content")),
                }
            )
            continue

        if role == "assistant":
            content = _coerce_content_text(message.get("content"))
            if content:
                items.append({"role": "assistant", "content": content})
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    call_item = _assistant_tool_call_to_responses_input(tool_call)
                    if call_item is not None:
                        items.append(call_item)
            continue

        items.append({"role": role, "content": _coerce_content_text(message.get("content"))})
    return items


def _instructions_from_messages(messages: list[dict[str, Any]]) -> str:
    """Move trusted system guidance to the Codex Responses instructions field."""

    return "\n\n".join(
        _coerce_content_text(message.get("content")).strip()
        for message in messages
        if str(message.get("role") or "") == "system"
        and _coerce_content_text(message.get("content")).strip()
    )


def _assistant_tool_call_to_responses_input(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    function = value.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    raw_arguments = function.get("arguments")
    arguments = raw_arguments if isinstance(raw_arguments, str) else json.dumps(raw_arguments or {})
    return {
        "type": "function_call",
        "call_id": str(value.get("id") or value.get("call_id") or name),
        "name": name.strip(),
        "arguments": arguments,
    }


def _chat_tools_to_responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        converted.append(
            {
                "type": "function",
                "name": name.strip(),
                "description": str(function.get("description") or ""),
                "strict": False,
                "parameters": function.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return converted


def _responses_payload_from_http_response(response: httpx.Response) -> dict[str, Any]:
    """Decode JSON Responses replies and the ChatGPT Codex SSE variant."""

    content_type = response.headers.get("content-type", "").lower()
    body = response.text
    if "text/event-stream" in content_type or body.lstrip().startswith("event:"):
        return _responses_payload_from_sse(body)
    try:
        data = response.json()
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _responses_payload_from_sse(body: str) -> dict[str, Any]:
    """Reassemble terminal response items because Codex completes with output=[]"""

    output_items: list[dict[str, Any]] = []
    output_text: list[str] = []
    completed_response: dict[str, Any] = {}
    event_data: list[str] = []

    def consume_event() -> None:
        nonlocal completed_response
        if not event_data:
            return
        raw = "\n".join(event_data).strip()
        event_data.clear()
        if not raw or raw == "[DONE]":
            return
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        if event_type == "response.output_item.done":
            item = event.get("item")
            if isinstance(item, dict):
                output_items.append(item)
        elif event_type == "response.output_text.done":
            text = event.get("text")
            if isinstance(text, str) and text:
                output_text.append(text)
        elif event_type == "response.completed":
            response = event.get("response")
            if isinstance(response, dict):
                completed_response = response

    for line in body.splitlines():
        if line.startswith("data:"):
            event_data.append(line[5:].lstrip())
        elif not line.strip():
            consume_event()
    consume_event()

    payload = dict(completed_response)
    if output_items:
        payload["output"] = output_items
    elif output_text:
        payload["output"] = [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "\n".join(output_text)}],
            }
        ]
    return payload


def _parse_responses_payload(payload: dict[str, Any]) -> ChatResponse:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[ToolCallRequest] = []

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text:
        content_parts.append(output_text)

    output = payload.get("output")
    if isinstance(output, list):
        for index, item in enumerate(output):
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "function_call":
                tool_call = _parse_function_call_item(item, index=index)
                if tool_call is not None:
                    tool_calls.append(tool_call)
            elif item_type == "message":
                text = _extract_message_text(item)
                if text and text not in content_parts:
                    content_parts.append(text)
            elif item_type == "reasoning":
                reasoning = _extract_reasoning_text(item)
                if reasoning:
                    reasoning_parts.append(reasoning)
            elif item_type in {"output_text", "text"}:
                output_item_text = item.get("text")
                if isinstance(output_item_text, str) and output_item_text:
                    content_parts.append(output_item_text)

    return ChatResponse(
        content="\n".join(part for part in content_parts if part),
        reasoning_content="\n".join(reasoning_parts),
        tool_calls=tool_calls,
        usage=_responses_token_usage(payload.get("usage")),
    )


def _responses_token_usage(value: Any) -> TokenUsage:
    """Normalize the Responses API usage shape while preserving unknown usage."""

    if not isinstance(value, dict):
        return TokenUsage()
    input_tokens = _non_negative_int(value.get("input_tokens"))
    output_tokens = _non_negative_int(value.get("output_tokens"))
    input_details = value.get("input_tokens_details")
    output_details = value.get("output_tokens_details")
    input_details = input_details if isinstance(input_details, dict) else {}
    output_details = output_details if isinstance(output_details, dict) else {}
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=_non_negative_int(input_details.get("cached_tokens")),
        reasoning_tokens=_non_negative_int(output_details.get("reasoning_tokens")),
        total_tokens=_non_negative_int(value.get("total_tokens"))
        or input_tokens + output_tokens,
        reported=True,
    )


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _parse_function_call_item(item: dict[str, Any], *, index: int) -> ToolCallRequest | None:
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    raw_arguments = item.get("arguments") or "{}"
    if isinstance(raw_arguments, dict):
        arguments = raw_arguments
    elif isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            parsed = {}
        arguments = parsed if isinstance(parsed, dict) else {}
    else:
        arguments = {}
    call_id = item.get("call_id") or item.get("id") or f"call_{index}"
    return ToolCallRequest(id=str(call_id), name=name.strip(), arguments=arguments)


def _extract_message_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            text = part.get("text") or part.get("content")
            if isinstance(text, str) and text:
                parts.append(text)
    return "\n".join(parts)


def _extract_reasoning_text(item: dict[str, Any]) -> str:
    summary = item.get("summary")
    if isinstance(summary, str):
        return summary
    if not isinstance(summary, list):
        return ""
    parts: list[str] = []
    for part in summary:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict):
            text = part.get("text") or part.get("content")
            if isinstance(text, str) and text:
                parts.append(text)
    return "\n".join(parts)


def _coerce_content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False)


__all__ = ["CodexResponsesChatProvider", "resolve_codex_access_token"]
