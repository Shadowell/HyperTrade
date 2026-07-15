from __future__ import annotations

from typing import Any

import pytest
from hypertrade.agent.sessions import AgentSessionCreate, AgentSessionService
from hypertrade.agent.tasks import AgentTaskCreate, AgentTaskService
from hypertrade.config import Settings
from hypertrade.db import AgentMission, Database
from hypertrade.research.graph import ResearchGraphCreate, ResearchGraphTaskService
from hypertrade.research.schemas import ResearchMandateCreate
from hypertrade.research.service import ResearchProgramService
from hypertrade.runtime.adapters.sql_store import SqlAlchemyMissionStore
from hypertrade.runtime.application.entrypoint import mission_request_for_prompt
from hypertrade.worker import agent_task_worker_once, mission_worker_once, monitor_scheduler_once


def test_monitor_scheduler_once_respects_disabled_setting(monkeypatch) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    monkeypatch.setattr(
        "hypertrade.worker.MonitorService",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not run")),
    )

    result = monitor_scheduler_once(
        db,
        settings=Settings(DEEPSEEK_API_KEY="", MONITOR_SCHEDULER_ENABLED=False),
    )

    assert result == {
        "status": "disabled",
        "ran": [],
        "skipped": [],
        "failed": [],
    }


def test_monitor_scheduler_once_wires_bitpro_adapter_and_runs_due_monitors(monkeypatch) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, *, settings: Settings) -> None:
            captured["client_settings"] = settings

    class FakeAdapter:
        def __init__(self, client: FakeClient) -> None:
            captured["adapter_client"] = client

    class FakeMonitorService:
        def __init__(self, service_db: Database, *, bitpro_adapter: FakeAdapter) -> None:
            captured["service_db"] = service_db
            captured["bitpro_adapter"] = bitpro_adapter

        def run_due_monitors(self) -> dict[str, Any]:
            return {
                "status": "completed",
                "ran": [{"monitor_id": "mon_bitpro_paper_all"}],
                "skipped": [],
                "failed": [],
            }

    monkeypatch.setattr("hypertrade.worker.BitProMcpClient", FakeClient)
    monkeypatch.setattr("hypertrade.worker.BitProToolAdapter", FakeAdapter)
    monkeypatch.setattr("hypertrade.worker.MonitorService", FakeMonitorService)
    settings = Settings(DEEPSEEK_API_KEY="", BITPRO_MCP_API_BASE="http://127.0.0.1:9")

    result = monitor_scheduler_once(db, settings=settings)

    assert result["ran"] == [{"monitor_id": "mon_bitpro_paper_all"}]
    assert captured["service_db"] is db
    assert captured["client_settings"] is settings
    assert captured["bitpro_adapter"] is not None


def test_agent_task_worker_claims_and_completes_queued_chat_task(tmp_path) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    agent_session = AgentSessionService(db).create(
        AgentSessionCreate(title="worker session", surface="background")
    )
    task = AgentTaskService(db).create(
        AgentTaskCreate(
            session_id=agent_session.id,
            objective="summarize bounded task without a provider",
            idempotency_key="worker-task-1",
        )
    )
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    settings = Settings(
        DEEPSEEK_API_KEY="",
        ACTIVE_CHAT_PROVIDER="deepseek",
        KNOWLEDGE_DIR=knowledge,
        AGENT_TASK_WORKER_ENABLED=True,
    )

    result = agent_task_worker_once(db, settings=settings, worker_id="worker-test")

    assert result["status"] == "completed"
    assert result["task_id"] == task.id
    stored = AgentTaskService(db).get(task.id)
    assert stored.status == "completed"
    assert stored.resource_type == "agent_run"
    assert stored.resource_id.startswith("run_")


def test_agent_task_worker_dispatches_research_graph_kind(monkeypatch, tmp_path) -> None:
    db = Database(f"sqlite:///{tmp_path / 'worker-graph.db'}")
    db.create_all()
    mandate = ResearchProgramService(db).create_mandate(
        ResearchMandateCreate(
            name="Worker graph mandate",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
        )
    )
    task_payload = ResearchGraphTaskService(db).create(
        ResearchGraphCreate(
            mandate_id=str(mandate["id"]),
            objective="Run a bounded worker graph without any trading write",
            idempotency_key="worker-graph-task-001",
        ),
        created_by="test",
    )
    task_id = str(task_payload["task"]["id"])
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()

    class FakeClient:
        def __init__(self, *, settings: Settings) -> None:
            self.settings = settings

    class FakeAdapter:
        def __init__(self, client: FakeClient) -> None:
            self.client = client

        def capabilities(self):
            return {"status": "available"}

        def health(self):
            return {"status": "ok"}

        def market_klines(self, **kwargs):
            return {"status": "available", "request": kwargs, "candles": []}

        def backtest_get_job(self, **kwargs):
            return {"status": "completed", "request": kwargs}

        def backtest_get_result(self, **kwargs):
            return {"status": "completed", "request": kwargs, "metrics": {}}

    monkeypatch.setattr("hypertrade.worker.BitProMcpClient", FakeClient)
    monkeypatch.setattr("hypertrade.worker.BitProToolAdapter", FakeAdapter)
    settings = Settings(
        DEEPSEEK_API_KEY="",
        ACTIVE_CHAT_PROVIDER="deepseek",
        KNOWLEDGE_DIR=knowledge,
        AGENT_TASK_WORKER_ENABLED=True,
    )

    result = agent_task_worker_once(db, settings=settings, worker_id="graph-worker-test")

    assert result["status"] == "completed"
    assert result["task_id"] == task_id
    assert result["evidence_count"] >= 13
    assert AgentTaskService(db).get(task_id).status == "completed"


@pytest.mark.anyio
async def test_mission_worker_claims_with_lease_and_completes_without_legacy_rows(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'mission-worker.db'}"
    db = Database(database_url)
    db.create_all()
    settings = Settings(
        DATABASE_URL=database_url,
        DEEPSEEK_API_KEY="",
        KNOWLEDGE_DIR=tmp_path,
        MISSION_RUNTIME_ENABLED=True,
        MISSION_RUNTIME_WORKER_ENABLED=True,
        MISSION_RUNTIME_LEASE_SECONDS=10,
    )
    store = SqlAlchemyMissionStore(database_url)
    try:
        mission = await store.create(
            mission_request_for_prompt(
                "研究 BTC 当前市场状态",
                actor="test",
                idempotency_key="mission-worker-lease-001",
            )
        )
        claimed = await store.claim_next("worker-a", lease_seconds=10)
        assert claimed is not None
        assert claimed.mission_id == mission.mission_id

        blocked = await mission_worker_once(db, settings=settings, worker_id="worker-b")
        assert blocked == {"status": "idle", "mission_id": None}

        await store.release(mission.mission_id, "worker-a")
        result = await mission_worker_once(db, settings=settings, worker_id="worker-b")
        completed = await store.get(mission.mission_id)
    finally:
        await store.dispose()

    assert result["status"] == "completed"
    assert result["mission_id"] == mission.mission_id
    assert completed.status.value == "completed"
    with db.session() as session:
        row = session.get(AgentMission, mission.mission_id)
        assert row is not None
        assert row.lease_owner is None
        assert row.lease_expires_at is None
