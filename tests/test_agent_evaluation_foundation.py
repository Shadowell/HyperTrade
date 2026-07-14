from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from hypertrade.agent.kernel import AgentKernel
from hypertrade.config import Settings
from hypertrade.db import Database, MemoryItem
from hypertrade.evals.langfuse import LangfuseTraceExporter
from hypertrade.evals.trajectory import build_trajectory_from_api_payload
from hypertrade.main import create_app
from hypertrade.providers.chat import ChatResponse, ToolCallRequest
from sqlalchemy import func, select


class WriteAttemptProvider:
    name = "replay"
    model = "evaluation-mode-test"

    def __init__(self) -> None:
        self.responses = [
            ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_write_memory",
                        name="memory_write",
                        arguments={"content": "do not persist this", "kind": "agent_note"},
                    )
                ],
            ),
            ChatResponse(content="The write attempt was evaluated."),
        ]

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> ChatResponse:
        del messages, tools
        return self.responses.pop(0)


def _settings(tmp_path) -> Settings:
    return Settings(
        DATABASE_URL="sqlite:///:memory:",
        DEEPSEEK_API_KEY="test-key",
        KNOWLEDGE_DIR=tmp_path,
    )


def _install_write_attempt_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        "hypertrade.providers.runtime.ProviderRuntime.get_chat_provider",
        lambda self, selected=None, selected_model=None: WriteAttemptProvider(),
    )


def test_evaluation_mode_blocks_write_tool_before_memory_dispatch(monkeypatch, tmp_path) -> None:
    _install_write_attempt_provider(monkeypatch)
    db = Database("sqlite:///:memory:")
    db.create_all()

    run = AgentKernel(
        db,
        knowledge_dir=str(tmp_path),
        settings=_settings(tmp_path),
        evaluation_mode=True,
    ).run_chat("Persist this note")

    memory_event = next(event for event in run.trace_events if event.tool_name == "memory_write")
    assert memory_event.output_json["execution_status"] == "denied"
    assert "evaluation mode permits only" in memory_event.output_json["denial_reason"]
    assert run.run_state_json["execution_mode"] == "evaluation"
    assert run.report_json["execution_mode"] == "evaluation"
    with db.session() as session:
        assert session.scalar(select(func.count()).select_from(MemoryItem)) == 0


def test_api_passes_evaluation_mode_to_the_kernel(monkeypatch, tmp_path) -> None:
    _install_write_attempt_provider(monkeypatch)
    db = Database("sqlite:///:memory:")
    db.create_all()
    client = TestClient(create_app(settings=_settings(tmp_path), db=db))

    response = client.post(
        "/api/agent/runs",
        json={"prompt": "Persist this note", "evaluation_mode": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_state_json"]["execution_mode"] == "evaluation"
    memory_event = next(
        event for event in body["trace_events"] if event["tool_name"] == "memory_write"
    )
    assert memory_event["output_json"]["execution_status"] == "denied"


def test_langfuse_export_is_metadata_only_and_optional(monkeypatch) -> None:
    received_metadata: list[dict[str, Any]] = []

    class FakeSpan:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def update(self, *, metadata: dict[str, Any]) -> None:
            received_metadata.append(metadata)

    class FakeLangfuse:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.flushed = False

        def start_as_current_observation(self, **kwargs: Any) -> FakeSpan:
            del kwargs
            return FakeSpan()

        def flush(self) -> None:
            self.flushed = True

    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(Langfuse=FakeLangfuse))
    settings = Settings(
        LANGFUSE_ENABLED=True,
        LANGFUSE_PUBLIC_KEY="pk-lf-test",
        LANGFUSE_SECRET_KEY="sk-lf-test",
        LANGFUSE_BASE_URL="http://langfuse.internal",
    )
    run = SimpleNamespace(
        id="run_eval_001",
        status="completed",
        run_state_json={
            "execution_mode": "evaluation",
            "observability": {"provider": "replay", "model": "test", "usage": {}},
        },
        trace_events=[
            SimpleNamespace(
                id="evt_001",
                tool_name="memory_write",
                status="completed",
                input_json={"content": "secret input must not leave HyperTrade"},
                output_json={
                    "execution_status": "denied",
                    "policy": {"scope": "research_write"},
                },
            )
        ],
    )

    result = LangfuseTraceExporter(settings).export(run)

    assert result.status == "exported"
    assert result.event_count == 1
    assert received_metadata
    assert "secret input must not leave HyperTrade" not in repr(received_metadata)
    assert all(metadata["payload_mode"] == "metadata_only" for metadata in received_metadata)


def test_trajectory_projection_removes_prompt_and_sensitive_tool_arguments() -> None:
    trajectory = build_trajectory_from_api_payload(
        "market_ticker_eth",
        {
            "id": "run_eval_001",
            "status": "completed",
            "run_state_json": {"execution_mode": "evaluation"},
            "report_json": {
                "citations": [{"source_path": "docs/knowledge/risk.md"}],
                "tool_calls": [{"tool": "market_ticker"}, {"tool": "memory_write"}],
            },
            "trace_events": [
                {
                    "tool_name": "graph.intent_classify",
                    "input_json": {"prompt": "private prompt"},
                    "output_json": {},
                },
                {
                    "tool_name": "market_ticker",
                    "input_json": {"symbol": "ETH", "credential": "do-not-export"},
                    "output_json": {"execution_status": "completed"},
                },
                {
                    "tool_name": "memory_write",
                    "input_json": {"content": "do-not-export"},
                    "output_json": {"execution_status": "denied"},
                },
                {
                    "tool_name": "bitpro.health",
                    "input_json": {"token": "must-not-export"},
                    "output_json": {"execution_status": "completed"},
                },
            ],
        },
    )

    assert trajectory == {
        "schema_version": "agent-evaluation-trajectory-v1",
        "case_id": "market_ticker_eth",
        "run_id": "run_eval_001",
        "status": "completed",
        "execution_mode": "evaluation",
        "citation_count": 1,
        "metrics": {"duration_ms": None, "total_tokens": None},
        "research_os": {
            "task_status": "completed",
            "nodes": [],
            "evidence_types": [],
            "experiment_fingerprint": "",
            "validation_status": "",
        },
        "tool_calls": [
            {
                "name": "market_ticker",
                "args": {"symbol": "ETH"},
                "execution_status": "completed",
                "policy_outcome": "",
                "policy_scope": "read",
            },
            {
                "name": "memory_write",
                "args": {},
                "execution_status": "denied",
                "policy_outcome": "",
                "policy_scope": "research_write",
            },
        ],
    }


def test_research_os_trajectory_keeps_node_order_but_drops_node_payloads() -> None:
    trajectory = build_trajectory_from_api_payload(
        "research_graph",
        {
            "id": "run_research",
            "status": "completed",
            "nodes": [
                {
                    "node_key": "market_regime",
                    "role_key": "market_regime",
                    "status": "completed",
                    "attempt": 2,
                    "input_ref": {"prompt": "private"},
                    "output_ref": {"raw": "private"},
                }
            ],
            "evidence": [{"evidence_type": "data_gap", "claim": "private"}],
            "experiment": {"fingerprint": "a" * 64, "manifest": {"prompt": "private"}},
            "validation": {"final_status": "needs_data", "scenarios": ["private"]},
        },
    )

    assert trajectory["research_os"] == {
        "task_status": "completed",
        "nodes": [
            {
                "node_key": "market_regime",
                "role_key": "market_regime",
                "status": "completed",
                "attempt": 2,
            }
        ],
        "evidence_types": ["data_gap"],
        "experiment_fingerprint": "a" * 64,
        "validation_status": "needs_data",
    }
    assert "private" not in json.dumps(trajectory)


def test_langfuse_research_node_spans_export_metadata_only(monkeypatch) -> None:
    received_metadata: list[dict[str, Any]] = []

    class FakeSpan:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        def update(self, *, metadata: dict[str, Any]) -> None:
            received_metadata.append(metadata)

    class FakeLangfuse:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs

        def start_as_current_observation(self, **kwargs: Any) -> FakeSpan:
            del kwargs
            return FakeSpan()

        def flush(self) -> None:
            return None

    monkeypatch.setitem(sys.modules, "langfuse", SimpleNamespace(Langfuse=FakeLangfuse))
    run = SimpleNamespace(
        id="run_node_eval",
        status="completed",
        run_state_json={"execution_mode": "evaluation"},
        trace_events=[],
        node_runs=[
            SimpleNamespace(
                id="node_001",
                task_id="task_001",
                node_key="validation_reviewer",
                role_key="validation_reviewer",
                attempt=2,
                status="failed",
                input_ref_json={"prompt": "never export"},
                output_ref_json={"raw": "never export"},
                usage_json={"tokens": 123, "model_calls": 1, "tool_calls": 2},
                error_json={"code": "role_schema_invalid", "message": "private output"},
            )
        ],
    )
    settings = Settings(
        LANGFUSE_ENABLED=True,
        LANGFUSE_PUBLIC_KEY="pk-lf-test",
        LANGFUSE_SECRET_KEY="sk-lf-test",
        LANGFUSE_BASE_URL="http://langfuse.internal",
    )

    result = LangfuseTraceExporter(settings).export(run)

    assert result.status == "exported"
    assert result.event_count == 1
    node_metadata = next(item for item in received_metadata if item.get("node_run_id"))
    assert node_metadata["node_key"] == "validation_reviewer"
    assert node_metadata["error_code"] == "role_schema_invalid"
    assert "never export" not in repr(received_metadata)
    assert "private output" not in repr(received_metadata)
