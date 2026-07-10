from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from hypertrade.agent.kernel import AgentKernel
from hypertrade.agent.observability import AgentObservabilityService
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.memory.service import MemoryService
from hypertrade.providers.chat import (
    ChatResponse,
    TokenUsage,
    ToolCallRequest,
    _openai_token_usage,
)


class ReplayProvider:
    name = "replay"
    model = "flight-recorder-test"

    def __init__(self) -> None:
        self._responses = [
            ChatResponse(
                content="",
                reasoning_content="private reasoning must not be persisted",
                tool_calls=[
                    ToolCallRequest(
                        id="call_memory_search",
                        name="memory_search",
                        arguments={"query": "risk"},
                    ),
                    ToolCallRequest(
                        id="call_memory_write",
                        name="memory_write",
                        arguments={"kind": "agent_note", "content": "Watch funding risk."},
                    ),
                ],
                usage=TokenUsage(
                    input_tokens=180,
                    output_tokens=20,
                    cached_input_tokens=60,
                    reasoning_tokens=8,
                    total_tokens=200,
                    reported=True,
                ),
            ),
            ChatResponse(
                content="Memory reviewed.",
                usage=TokenUsage(
                    input_tokens=120,
                    output_tokens=30,
                    cached_input_tokens=40,
                    reasoning_tokens=12,
                    total_tokens=150,
                    reported=True,
                ),
            ),
        ]

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        return self._responses.pop(0)


def test_openai_usage_is_normalized_without_double_counting_cached_tokens() -> None:
    usage = _openai_token_usage(
        SimpleNamespace(
            prompt_tokens=125,
            completion_tokens=25,
            total_tokens=150,
            prompt_tokens_details=SimpleNamespace(cached_tokens=80),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=10),
        )
    )

    assert usage.to_dict() == {
        "input_tokens": 125,
        "output_tokens": 25,
        "cached_input_tokens": 80,
        "reasoning_tokens": 10,
        "total_tokens": 150,
        "reported": True,
    }
    deepseek_usage = _openai_token_usage(
        {
            "prompt_tokens": 90,
            "completion_tokens": 10,
            "total_tokens": 100,
            "prompt_cache_hit_tokens": 64,
        }
    )
    assert deepseek_usage.cached_input_tokens == 64
    assert deepseek_usage.total_tokens == 100


def test_agent_flight_recorder_correlates_model_tool_memory_and_tokens(
    monkeypatch,
    tmp_path,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    seeded = MemoryService(db).write(
        content="Risk budget should remain conservative.",
        kind="risk_note",
        source_run_id="run_prior",
        source_tool="fixture",
        tags=["risk"],
    )
    provider = ReplayProvider()
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda self, selected=None, selected_model=None: provider,
    )

    run = AgentKernel(
        db,
        knowledge_dir=str(tmp_path),
        settings=Settings(DEEPSEEK_API_KEY="test-key", KNOWLEDGE_DIR=tmp_path),
    ).run_chat("Review risk memory")
    payload = AgentObservabilityService(db).get(run.id)

    assert payload["usage"] == {
        "input_tokens": 300,
        "output_tokens": 50,
        "cached_input_tokens": 100,
        "reasoning_tokens": 20,
        "total_tokens": 350,
        "request_count": 2,
        "reported_requests": 2,
        "unreported_requests": 0,
        "reported": True,
    }
    assert payload["models"]["request_count"] == 2
    assert payload["memory"]["read_ids"] == [seeded.id]
    assert payload["memory"]["write_count"] == 1
    assert {item["id"] for item in payload["memory"]["items"]} == {
        seeded.id,
        payload["memory"]["write_ids"][0],
    }
    categories = [event["category"] for event in payload["timeline"]]
    assert categories.count("model") == 2
    assert categories.count("memory") == 2
    assert categories.index("model") < categories.index("memory")
    assert payload["safety"]["private_reasoning_stored"] is False
    assert "private reasoning must not be persisted" not in repr(payload)

    summary = AgentObservabilityService(db).recent_summary()
    assert summary["window_size"] == 1
    assert summary["total_tokens"] == 350
    assert summary["model_requests"] == 2
    assert summary["usage_reported_runs"] == 1


def test_observability_api_returns_projection_and_404(monkeypatch, tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    provider = ReplayProvider()
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda self, selected=None, selected_model=None: provider,
    )
    client = TestClient(
        create_app(
            settings=Settings(
                DEEPSEEK_API_KEY="test-key",
                KNOWLEDGE_DIR=tmp_path,
            ),
            db=db,
        )
    )

    run = client.post("/api/agent/runs", json={"prompt": "Review risk memory"}).json()
    response = client.get(f"/api/agent/runs/{run['id']}/observability")

    assert response.status_code == 200
    assert response.json()["run"]["id"] == run["id"]
    assert response.json()["usage"]["total_tokens"] == 350
    overview = client.get("/api/harness/overview").json()
    assert overview["observability"]["total_tokens"] == 350
    assert overview["observability"]["private_reasoning_stored"] is False
    assert client.get("/api/agent/runs/run_missing/observability").status_code == 404
