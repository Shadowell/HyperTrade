from __future__ import annotations

import json
from io import StringIO
from typing import Any

import httpx
from hypertrade.cli import (
    AgentApiClient,
    CliConfig,
    main,
    render_thread_turn_stream,
    run_chat,
)


def test_remote_ask_uses_canonical_thread_protocol_only() -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []
    client = _canonical_client(seen)
    output = StringIO()

    assert main(["ask", "看下 LAB 的价格"], client=client, output=output) == 0

    paths = [path for _, path, _ in seen]
    assert "/api/agent/v1/threads" in paths
    assert "/api/agent/v1/threads/thr_cli/turns" in paths
    assert not any(path.startswith("/api/agent/runs") for path in paths)
    turn_payload = next(
        payload for method, path, payload in seen if method == "POST" and path.endswith("/turns")
    )
    assert set(turn_payload) == {"input", "client_message_id"}
    assert turn_payload["input"] == "看下 LAB 的价格"
    assert "LAB evidence" in output.getvalue()


def test_remote_chat_reuses_one_server_thread_and_only_sends_new_input() -> None:
    seen: list[tuple[str, str, dict[str, Any]]] = []
    client = _canonical_client(seen)
    inputs = iter(
        [
            "比较 momentum_breakout_v1 和 mean_reversion_v1 哪个收益更高？",
            "后者最大回撤多少？",
            "exit",
        ]
    )

    run_chat(client=client, input_fn=lambda _: next(inputs), output=StringIO())

    thread_creates = [row for row in seen if row[0] == "POST" and row[1] == "/api/agent/v1/threads"]
    turn_creates = [row for row in seen if row[0] == "POST" and row[1].endswith("/turns")]
    assert len(thread_creates) == 1
    assert len(turn_creates) == 2
    assert all(row[1] == "/api/agent/v1/threads/thr_cli/turns" for row in turn_creates)
    assert all(set(row[2]) == {"input", "client_message_id"} for row in turn_creates)
    assert "prior_turns" not in json.dumps(turn_creates, ensure_ascii=False)
    stream_queries = [payload["after"] for method, path, payload in seen if method == "STREAM"]
    assert stream_queries == [0, 5]


def test_canonical_cli_rejects_stream_eof_without_terminal_event() -> None:
    class EofClient:
        stream_calls = 0

        def start_thread_turn(
            self,
            thread_id: str,
            prompt: str,
            *,
            client_message_id: str,
        ) -> dict[str, Any]:
            del thread_id, prompt, client_message_id
            return {"turn": {"turn_id": "trn_eof"}}

        def stream_thread_events(self, thread_id: str, *, after: int = 0):
            del thread_id, after
            self.stream_calls += 1
            return iter(())

        def get_thread_turn(self, thread_id: str, turn_id: str) -> dict[str, Any]:
            del thread_id, turn_id
            return {"turn": {"status": "running"}, "items": []}

    client = EofClient()
    output = StringIO()

    render_thread_turn_stream(client, "thr_eof", "hello", output=output)  # type: ignore[arg-type]

    assert client.stream_calls == 3
    assert "Protocol error" in output.getvalue()


def _canonical_client(seen: list[tuple[str, str, dict[str, Any]]]) -> AgentApiClient:
    state = {"turn": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        payload: dict[str, Any] = {}
        if request.content:
            payload = dict(json.loads(request.content.decode()))
        path = request.url.path
        if request.method == "GET" and path.endswith("/events/stream"):
            after = int(request.url.params.get("after", "0"))
            seen.append(("STREAM", path, {"after": after}))
            turn_number = state["turn"]
            turn_id = f"trn_{turn_number}"
            base = 0 if turn_number == 1 else 5
            body = "".join(
                [
                    _sse(base + 2, "turn.accepted", turn_id, {}),
                    _sse(base + 3, "turn.started", turn_id, {"mission_id": f"mis_{turn_number}"}),
                    _sse(
                        base + 4,
                        "agent_message.completed",
                        turn_id,
                        {"content": {"text": f"LAB evidence {turn_number}"}},
                    ),
                    _sse(base + 5, "turn.completed", turn_id, {}),
                ]
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        seen.append((request.method, path, payload))
        if path == "/api/auth/login":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/harness/overview":
            return httpx.Response(
                200,
                json={"providers": [{"name": "test", "model": "deterministic", "default": True}]},
            )
        if path == "/api/agent/v1/threads":
            return httpx.Response(200, json={"thread": {"thread_id": "thr_cli"}})
        if request.method == "POST" and path.endswith("/turns"):
            state["turn"] += 1
            turn_id = f"trn_{state['turn']}"
            return httpx.Response(
                202,
                json={"created": True, "turn": {"turn_id": turn_id}, "event_cursor": 1},
            )
        if request.method == "GET" and "/turns/" in path:
            turn_id = path.rsplit("/", 1)[-1]
            return httpx.Response(
                200,
                json={
                    "turn": {"turn_id": turn_id, "status": "completed"},
                    "items": [
                        {
                            "item_type": "agent_message",
                            "content": {"text": f"LAB evidence {state['turn']}"},
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return AgentApiClient(
        CliConfig(api_url="http://example.test", username="admin", password="secret"),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _sse(cursor: int, event: str, turn_id: str, payload: dict[str, Any]) -> str:
    event_payload = {
        "event_type": event,
        "payload": {"turn_id": turn_id, **payload},
    }
    return (
        f"id: {cursor}\nevent: {event}\ndata: {json.dumps(event_payload, ensure_ascii=False)}\n\n"
    )
