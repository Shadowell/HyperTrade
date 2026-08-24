"""Sprint-144: provider token streaming — deltas, tool-call accumulation, usage.

Chunk shapes mimic the OpenAI streaming protocol (delta.content /
delta.tool_calls with partial argument strings / usage-only final chunk).
The provider client is injected, so nothing touches the network.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from hypertrade.agent.planner import AgentPlanner
from hypertrade.providers.chat import ChatResponse, OpenAICompatibleChatProvider


def _content_chunk(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text, tool_calls=None))],
        usage=None,
    )


def _tool_call_chunk(
    index: int, *, id: str = "", name: str = "", args: str = ""
) -> SimpleNamespace:
    function = SimpleNamespace(
        name=name or None,
        arguments=args or None,
    )
    delta = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(index=index, id=id or None, function=function),
        ],
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=None)


def _usage_chunk(total: int) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=total,
            total_tokens=10 + total,
            prompt_tokens_details=None,
            completion_tokens_details=None,
        ),
    )


class _FakeCompletions:
    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks
        self.last_kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> list[SimpleNamespace]:
        self.last_kwargs = kwargs
        return list(self._chunks)


class _FakeClient:
    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(chunks))


def test_stream_chat_emits_deltas_and_accumulates_tool_calls() -> None:
    chunks = [
        _content_chunk("研究"),
        _content_chunk("结论："),
        _tool_call_chunk(0, id="call_1", name="market_summary", args='{"lim'),
        _tool_call_chunk(0, args='it": 10}'),
        _tool_call_chunk(1, id="call_2", name="memory_search", args="{}"),
        _usage_chunk(42),
    ]
    provider = OpenAICompatibleChatProvider(
        name="test",
        api_key="k",
        base_url="http://localhost",
        model="m",
        client=_FakeClient(chunks),
    )
    deltas: list[str] = []

    response = provider.stream_chat(
        [{"role": "user", "content": "hi"}],
        on_delta=deltas.append,
    )

    assert deltas == ["研究", "结论："]
    assert response.content == "研究结论："
    assert [call.name for call in response.tool_calls] == ["market_summary", "memory_search"]
    assert response.tool_calls[0].arguments == {"limit": 10}
    assert response.tool_calls[0].id == "call_1"
    assert response.usage.total_tokens == 52
    assert response.usage.reported is True
    # Streaming protocol flags actually sent.
    assert response is not None


def test_stream_chat_sends_stream_options_and_tools() -> None:
    chunks = [_content_chunk("ok"), _usage_chunk(1)]
    client = _FakeClient(chunks)
    provider = OpenAICompatibleChatProvider(
        name="test", api_key="k", base_url="http://localhost", model="m", client=client
    )

    provider.stream_chat(
        [{"role": "user", "content": "hi"}],
        [{"type": "function", "function": {"name": "t", "parameters": {}}}],
        on_delta=lambda text: None,
    )

    assert client.chat.completions.last_kwargs["stream"] is True
    assert client.chat.completions.last_kwargs["stream_options"] == {"include_usage": True}
    assert client.chat.completions.last_kwargs["tool_choice"] == "auto"


def test_reasoning_content_never_reaches_on_delta() -> None:
    reasoning_chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, reasoning_content="private thoughts")
            )
        ],
        usage=None,
    )
    provider = OpenAICompatibleChatProvider(
        name="test",
        api_key="k",
        base_url="http://localhost",
        model="m",
        client=_FakeClient([reasoning_chunk, _content_chunk("answer"), _usage_chunk(1)]),
    )
    deltas: list[str] = []

    response = provider.stream_chat(
        [{"role": "user", "content": "hi"}], on_delta=deltas.append
    )

    assert deltas == ["answer"]
    assert response.reasoning_content == "private thoughts"


class _StreamingScriptedProvider:
    """Planner-level fake: streams the final answer, tool rounds stay silent."""

    name = "streaming-scripted"
    model = "test"

    def __init__(self, rounds: int) -> None:
        self._rounds = rounds
        self.deltas_per_call: list[list[str]] = []

    def chat(self, messages: list[dict[str, Any]], tools: Any = None) -> ChatResponse:
        raise AssertionError("planner must use stream_chat when a delta sink is set")

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: Any = None,
        *,
        on_delta: Any = None,
    ) -> ChatResponse:
        deltas: list[str] = []
        if self._rounds > 0:
            self._rounds -= 1
            # Tool rounds carry no visible content.
            from hypertrade.providers.chat import ToolCallRequest

            return ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(id=f"call_{self._rounds}", name="market_summary", arguments={})
                ],
            )
        for piece in ("## 结论", "\n研究完成。"):
            deltas.append(piece)
            if on_delta is not None:
                on_delta(piece)
        self.deltas_per_call.append(deltas)
        return ChatResponse(content="## 结论\n研究完成。")


def test_planner_streams_final_answer_through_delta_sink() -> None:
    provider = _StreamingScriptedProvider(rounds=1)
    planner = AgentPlanner(provider)
    received: list[str] = []

    def executor(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    result = planner.run("研究 BTC", executor, delta_sink=received.append)

    assert result.final_message == "## 结论\n研究完成。"
    assert received == ["## 结论", "\n研究完成。"]
    assert len(result.tool_calls) == 1


def test_planner_without_delta_sink_uses_plain_chat() -> None:
    provider = _StreamingScriptedProvider(rounds=0)
    # Without a sink the planner must not require stream_chat: plain chat works.
    provider.chat = lambda messages, tools=None: ChatResponse(content="plain answer")  # type: ignore[method-assign]
    planner = AgentPlanner(provider)

    result = planner.run("你好", lambda name, args: {"ok": True})

    assert result.final_message == "plain answer"
    assert result.context_compactions == 0


def test_kernel_emits_answer_delta_events(monkeypatch, tmp_path) -> None:

    from hypertrade.agent.kernel import AgentKernel
    from hypertrade.config import Settings
    from hypertrade.db import Database

    db = Database("sqlite:///:memory:")
    db.create_all()

    provider = _StreamingScriptedProvider(rounds=0)
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda self, selected=None, selected_model=None: provider,
    )
    kernel = AgentKernel(
        db,
        knowledge_dir=tmp_path,
        settings=Settings(DEEPSEEK_API_KEY="k", KNOWLEDGE_DIR=tmp_path),
    )
    events: list[dict[str, Any]] = []

    kernel.run_chat_with_events("研究 BTC", event_sink=events.append)

    deltas = [event for event in events if event.get("event") == "answer_delta"]
    assert [event["text"] for event in deltas] == ["## 结论", "\n研究完成。"]
    assert all(event["run_id"] for event in deltas)
