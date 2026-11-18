from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from hypertrade.agent.observability import AgentObservabilityService
from hypertrade.arc.evolution_models import ArcRuntimeError
from hypertrade.arc.runtime_journal import list_runtime_errors, record_runtime_error
from hypertrade.bitpro.mcp import bitpro_capabilities
from hypertrade.config import Settings
from hypertrade.db import (
    AgentMission,
    AgentMissionEvent,
    AgentStepAttempt,
    AgentThread,
    AgentToolCall,
    BacktestRun,
    Database,
    LiveOrderIntent,
    PaperSession,
    StrategyExperiment,
    StrategyResearch,
)
from hypertrade.main import create_app
from hypertrade.market.repository import MarketRepository
from hypertrade.memory.service import MemoryService
from hypertrade.paper.service import PaperTradingService
from hypertrade.runtime.adapters.capability_catalog import (
    CatalogCapabilityPolicy,
    InMemoryCapabilityCatalog,
    builtin_capabilities,
)
from hypertrade.runtime.adapters.research_planner import DeterministicResearchPlanner
from hypertrade.runtime.adapters.sql_store import SqlAlchemyMissionStore
from hypertrade.runtime.adapters.thread_store import InMemoryThreadStore, SqlAlchemyThreadStore
from hypertrade.runtime.adapters.tool_runtime import (
    GovernedToolExecutor,
    InMemoryObservationStore,
    builtin_handlers,
)
from hypertrade.runtime.application.service import MissionRuntime
from hypertrade.runtime.domain.models import MissionCreate, SuccessCriterionV1
from sqlalchemy import func, select


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    assert response.status_code == 200


def _seed_mission_row(
    session: Any,
    *,
    mission_id: str,
    status: str,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> AgentMission:
    now = created_at or datetime.now(UTC)
    row = AgentMission(
        id=mission_id,
        objective=f"Inspect {mission_id}",
        original_objective=f"Inspect {mission_id}",
        success_criteria_json=[
            {
                "criterion_id": "validated_steps",
                "kind": "all_steps_validated",
                "description": "Every approved step succeeded.",
                "expected": True,
            }
        ],
        constraints_json=["Research-only read scope."],
        status=status,
        budget_json={"max_tool_calls": 10, "max_tokens": 10000},
        usage_json={
            "plan_versions": 1,
            "step_attempts": 1,
            "model_calls": 0,
            "tool_calls": 1,
            "tokens": 0,
            "duration_ms": 0,
        },
        permission_profile_ref="read_only.v1",
        context_policy_ref="mission_context.v1",
        created_by="admin",
        idempotency_key=f"idem-{mission_id}",
        request_hash="a" * 64,
        created_at=now,
        updated_at=updated_at or now,
    )
    session.add(row)
    return row


def test_harness_overview_headless_mode_and_missions_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    assert Settings().headless_mode is False

    db = Database("sqlite:///:memory:")
    db.create_all()

    MarketRepository(db).upsert_ticker_snapshot(
        inst_id="BTC-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("71000"),
        volume_ccy_24h=Decimal("50000"),
        change_utc0_pct=Decimal("2.5"),
    )
    with db.session() as session:
        session.add(
            StrategyResearch(
                id="res_seed_1",
                prompt="Seed research",
                strategy_key="seed_strat",
                title="Seed Strategy",
                report_markdown="# Seed",
            )
        )
        session.add(
            BacktestRun(
                id="bt_seed_1",
                research_id="res_seed_1",
                strategy_key="seed_strat",
                status="completed",
                start_cash=Decimal("10000"),
                end_value=Decimal("11000"),
                total_return_pct=Decimal("10.0"),
                max_drawdown_pct=Decimal("2.5"),
                trade_count=4,
            )
        )
        session.add(
            StrategyExperiment(
                id="exp_seed_1",
                prompt="Seed experiment",
                status="completed",
                research_id="res_seed_1",
                backtest_id="bt_seed_1",
            )
        )
        session.add(
            LiveOrderIntent(
                id="loi_seed_1",
                inst_id="BTC-USDT-SWAP",
                side="buy",
                size=Decimal("0.01"),
                reason="seed order",
                status="pending_approval",
            )
        )
        for mission_id, mission_status in (
            ("mis_active_1", "running"),
            ("mis_completed_1", "completed"),
            ("mis_failed_1", "failed"),
            ("mis_canceled_1", "canceled"),
            ("mis_budget_1", "budget_exhausted"),
        ):
            _seed_mission_row(session, mission_id=mission_id, status=mission_status)
        for idx in range(2):
            session.add(
                AgentThread(
                    id=f"thr_seed_{idx}",
                    tenant_id="default",
                    owner="admin",
                    title=f"Thread {idx}",
                    status="active",
                    retention="durable",
                    active_turn_id="",
                    version=1,
                    event_cursor=1,
                    projection_hash="b" * 64,
                )
            )

    def _forbid(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Legacy surface must not be queried in headless mode")

    monkeypatch.setattr(MarketRepository, "top_movers", _forbid)
    monkeypatch.setattr(PaperTradingService, "status", _forbid)

    headless_app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            SESSION_SECRET="headless-overview-secret",
            KNOWLEDGE_DIR=tmp_path,
            HYPERTRADE_HEADLESS_MODE=True,
        ),
        db=db,
    )
    headless_client = TestClient(headless_app)
    resp = headless_client.get("/api/harness/overview")
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["headless_mode"] is True
    assert payload["missions_summary"] == {
        "total_count": 5,
        "active_count": 1,
        "completed_count": 1,
        "failed_count": 1,
        "threads_count": 2,
    }
    assert payload["market"] == {
        "ticker_count": 0,
        "latest_ticker_at": None,
        "latest_update_age_seconds": None,
        "top_movers": [],
    }
    assert payload["paper"] == {
        "session": {
            "id": "",
            "status": "disabled_headless",
            "cash": "0",
            "equity": "0",
            "realized_pnl": "0",
        },
        "positions": [],
        "recent_fills": [],
        "recent_events": [],
    }
    assert payload["strategy_lab"] == {
        "latest_research": None,
        "latest_backtest": None,
        "latest_experiment": None,
    }
    assert payload["live_orders"] == {
        "total_count": 0,
        "pending_approval_count": 0,
        "recent": [],
    }
    expected_tools = list(
        dict.fromkeys(
            tool_name
            for group_tools in bitpro_capabilities()["tool_groups"].values()
            for tool_name in group_tools
        )
    )
    assert payload["bitpro"]["tools"] == expected_tools
    assert len(payload["bitpro"]["tools"]) == len(set(payload["bitpro"]["tools"]))

    with db.session() as session:
        assert session.scalar(select(func.count()).select_from(PaperSession)) == 0

    monkeypatch.undo()

    live_app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            SESSION_SECRET="non-headless-overview-secret",
            KNOWLEDGE_DIR=tmp_path,
            HYPERTRADE_HEADLESS_MODE=False,
        ),
        db=db,
    )
    live_payload = TestClient(live_app).get("/api/harness/overview").json()
    assert live_payload["headless_mode"] is False
    assert live_payload["missions_summary"] == payload["missions_summary"]
    assert live_payload["market"]["ticker_count"] == 1
    assert live_payload["market"]["top_movers"][0]["inst_id"] == "BTC-USDT-SWAP"
    assert live_payload["paper"]["session"]["status"] == "running"
    assert live_payload["strategy_lab"]["latest_research"]["id"] == "res_seed_1"
    assert live_payload["strategy_lab"]["latest_backtest"]["id"] == "bt_seed_1"
    assert live_payload["strategy_lab"]["latest_experiment"]["id"] == "exp_seed_1"
    assert live_payload["live_orders"]["total_count"] == 1
    assert live_payload["live_orders"]["pending_approval_count"] == 1
    assert live_payload["bitpro"]["tools"] == expected_tools


def test_arc_runtime_errors_endpoint_lists_and_filters_receipts(tmp_path: Any) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()

    first = record_runtime_error(
        "observation",
        RuntimeError("snapshot api_key=super-secret-value failed"),
        mission_id="arc_obs_1",
        context={"strategy_id": 44, "api_key": "must-redact"},
        db=db,
    )
    second = record_runtime_error(
        "evolution",
        ValueError("first message"),
        mission_id="arc_evo_1",
        context={"strategy_id": 77},
        db=db,
    )
    third = record_runtime_error(
        "evolution",
        ValueError("second message"),
        mission_id="arc_evo_1",
        context={"strategy_id": 77},
        db=db,
    )
    assert first["error_id"] is not None
    assert second["error_id"] == third["error_id"]

    t0 = datetime(2026, 11, 18, 1, 0, 0, tzinfo=UTC)
    with db.session() as session:
        err_obs = session.get(ArcRuntimeError, first["error_id"])
        err_evo = session.get(ArcRuntimeError, second["error_id"])
        assert err_obs is not None and err_evo is not None
        err_obs.first_seen_at = t0
        err_obs.last_seen_at = t0
        err_evo.first_seen_at = t0 + timedelta(minutes=1)
        err_evo.last_seen_at = t0 + timedelta(minutes=5)

    assert len(list_runtime_errors(db, limit=0)) == 1
    assert len(list_runtime_errors(db, limit=500)) == 2

    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            SESSION_SECRET="arc-runtime-errors-secret",
            KNOWLEDGE_DIR=tmp_path,
        ),
        db=db,
    )
    with TestClient(app) as client:
        unauth = client.get("/api/v1/arc/runtime-errors")
        assert unauth.status_code in (401, 403)

        _login(client)
        listed = client.get("/api/v1/arc/runtime-errors")
        assert listed.status_code == 200
        items = listed.json()["items"]
        assert [row["component"] for row in items] == ["evolution", "observation"]

        evo_row, obs_row = items
        assert evo_row["error_id"] == second["error_id"]
        assert evo_row["exception_type"] == "builtins.ValueError"
        assert evo_row["message"] == "second message"
        assert evo_row["mission_id"] == "arc_evo_1"
        assert evo_row["occurrences"] == 2
        assert evo_row["recent_messages"] == ["first message", "second message"]
        assert evo_row["context"] == {"strategy_id": 77}
        assert isinstance(evo_row["frames"], list)
        assert datetime.fromisoformat(evo_row["first_seen_at"])
        assert datetime.fromisoformat(evo_row["last_seen_at"])

        assert "super-secret-value" not in obs_row["message"]
        assert obs_row["context"]["api_key"] == "[REDACTED]"

        filtered = client.get("/api/v1/arc/runtime-errors?component=observation&limit=1")
        assert filtered.status_code == 200
        assert len(filtered.json()["items"]) == 1
        assert filtered.json()["items"][0]["error_id"] == first["error_id"]

        assert client.get("/api/v1/arc/runtime-errors?limit=0").status_code == 422
        assert client.get("/api/v1/arc/runtime-errors?limit=101").status_code == 422


def test_canonical_thread_listing_api_and_stores(tmp_path: Any) -> None:
    # Verify both InMemoryThreadStore and SqlAlchemyThreadStore implementations directly.
    async def _check_stores() -> None:
        mem = InMemoryThreadStore()
        s1 = await mem.create_thread(
            tenant_id="default", owner="admin", title="First", retention="durable"
        )
        s2 = await mem.create_thread(
            tenant_id="default", owner="admin", title="Second", retention="durable"
        )
        s3 = await mem.create_thread(
            tenant_id="other", owner="admin", title="Other Tenant", retention="durable"
        )
        assert s1.thread and s2.thread and s3.thread
        await mem.append(
            s1.thread.thread_id,
            "thread.archived",
            payload={},
            actor="admin",
            idempotency_key="arch-1",
        )
        listed_all = await mem.list_threads(limit=100)
        assert [row.thread_id for row in listed_all] == [s1.thread.thread_id, s2.thread.thread_id]
        assert [row.thread_id for row in await mem.list_threads(status="active")] == [
            s2.thread.thread_id
        ]
        assert [row.thread_id for row in await mem.list_threads(status="archived")] == [
            s1.thread.thread_id
        ]
        assert len(await mem.list_threads(limit=0)) == 1

        sql_url = f"sqlite:///{tmp_path / 'thread_store_unit.db'}"
        sql_db = Database(sql_url)
        sql_db.create_all()
        sql = SqlAlchemyThreadStore(sql_url)
        try:
            a = await sql.create_thread(
                tenant_id="default", owner="admin", title="SQL A", retention="durable"
            )
            b = await sql.create_thread(
                tenant_id="default", owner="admin", title="SQL B", retention="durable"
            )
            assert a.thread and b.thread
            await sql.append(
                a.thread.thread_id,
                "thread.archived",
                payload={},
                actor="admin",
                idempotency_key="sql-arch-a",
            )
            rows = await sql.list_threads(limit=100)
            assert [row.thread_id for row in rows] == [a.thread.thread_id, b.thread.thread_id]
            assert [row.thread_id for row in await sql.list_threads(status="active")] == [
                b.thread.thread_id
            ]
            assert [row.thread_id for row in await sql.list_threads(status="archived")] == [
                a.thread.thread_id
            ]
            assert len(await sql.list_threads(limit=0)) == 1
        finally:
            await sql.dispose()

    anyio.run(_check_stores)

    # Verify HTTP endpoint on file-backed SQLite (exercises SqlAlchemyThreadStore through FastAPI).
    db_url = f"sqlite:///{tmp_path / 'threads_api.db'}"
    database = Database(db_url)
    database.create_all()
    app = create_app(
        settings=Settings(
            DATABASE_URL=db_url,
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            SESSION_SECRET="thread-list-api-secret",
            KNOWLEDGE_DIR=tmp_path,
        ),
        db=database,
    )
    with TestClient(app) as client:
        assert client.get("/api/agent/v1/threads").status_code == 401
        _login(client)

        t1 = client.post(
            "/api/agent/v1/threads",
            json={"title": "Thread One", "retention": "durable"},
        ).json()["thread"]["thread_id"]
        t2 = client.post(
            "/api/agent/v1/threads",
            json={"title": "Thread Two", "retention": "durable"},
        ).json()["thread"]["thread_id"]
        t3 = client.post(
            "/api/agent/v1/threads",
            json={"title": "Thread Three", "retention": "durable"},
        ).json()["thread"]["thread_id"]

        assert client.post(f"/api/agent/v1/threads/{t1}/archive").status_code == 200

        all_threads = client.get("/api/agent/v1/threads")
        assert all_threads.status_code == 200
        ids = [item["thread_id"] for item in all_threads.json()["items"]]
        assert ids == [t1, t3, t2]

        active_limited = client.get("/api/agent/v1/threads?status=active&limit=1")
        assert active_limited.status_code == 200
        assert [item["thread_id"] for item in active_limited.json()["items"]] == [t3]

        archived_only = client.get("/api/agent/v1/threads?status=archived")
        assert archived_only.status_code == 200
        assert [item["thread_id"] for item in archived_only.json()["items"]] == [t1]


def test_mission_flight_recorder_projection_and_404(tmp_path: Any) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()

    seeded_read = MemoryService(db).write(
        content="Monitor funding rate spikes before adding exposure.",
        kind="risk_note",
        source_run_id="run_seed",
        source_tool="fixture",
        tags=["risk"],
    )
    written_mem = MemoryService(db).write(
        content="BTC-USDT-SWAP volatility stayed bounded.",
        kind="strategy_observation",
        source_run_id="mis_flight_001",
        source_tool="memory.write",
        tags=["BTC"],
    )

    t0 = datetime(2026, 11, 18, 2, 0, 0, tzinfo=UTC)
    with db.session() as session:
        mission = _seed_mission_row(
            session,
            mission_id="mis_flight_001",
            status="completed",
            created_at=t0,
            updated_at=t0 + timedelta(seconds=2),
        )
        mission.usage_json = {
            "plan_versions": 1,
            "step_attempts": 3,
            "model_calls": 2,
            "tool_calls": 3,
            "tokens": 420,
            "input_tokens": 300,
            "output_tokens": 120,
            "duration_ms": 1450,
            "reported": True,
        }
        session.add_all(
            [
                AgentStepAttempt(
                    id="sat_mem_read",
                    mission_id="mis_flight_001",
                    plan_version=1,
                    step_id="step_mem",
                    attempt=1,
                    capability_id="memory.search",
                    status="succeeded",
                    observation_json={
                        "status": "succeeded",
                        "summary": "Found 1 risk memory item.",
                        "result": {"items": [{"memory_id": seeded_read.id}], "count": 1},
                        "source_refs": [f"memory:{seeded_read.id}"],
                        "usage": {"tool_calls": 1, "duration_ms": 25},
                    },
                    started_at=t0 + timedelta(milliseconds=100),
                    completed_at=t0 + timedelta(milliseconds=125),
                ),
                AgentStepAttempt(
                    id="sat_market_fail",
                    mission_id="mis_flight_001",
                    plan_version=1,
                    step_id="step_mkt",
                    attempt=1,
                    capability_id="market.summary",
                    status="failed",
                    observation_json={
                        "status": "failed",
                        "summary": "Upstream timeout.",
                        "source_refs": ["market:timeout"],
                        "error_category": "timeout",
                        "usage": {"tool_calls": 1, "duration_ms": 350},
                    },
                    started_at=t0 + timedelta(milliseconds=200),
                    completed_at=t0 + timedelta(milliseconds=550),
                ),
                AgentStepAttempt(
                    id="sat_mem_write",
                    mission_id="mis_flight_001",
                    plan_version=1,
                    step_id="step_write",
                    attempt=1,
                    capability_id="memory.write",
                    status="succeeded",
                    observation_json={
                        "status": "succeeded",
                        "summary": "Recorded observation.",
                        "result": {"memory_id": written_mem.id, "kind": "strategy_observation"},
                        "source_refs": [f"memory:{written_mem.id}"],
                        "usage": {"tool_calls": 1, "duration_ms": 15},
                    },
                    started_at=t0 + timedelta(milliseconds=600),
                    completed_at=t0 + timedelta(milliseconds=615),
                ),
                AgentToolCall(
                    id="tcall_linked_001",
                    intent_id="dint_linked_001",
                    mission_id="mis_flight_001",
                    capability_id="bitpro.paper_snapshot",
                    status="reconciled",
                    call_json={"duration_ms": 480, "reconciliation_outcome": "committed"},
                    created_at=t0 + timedelta(milliseconds=700),
                    updated_at=t0 + timedelta(milliseconds=1180),
                ),
                AgentMissionEvent(
                    id="mevt_01",
                    mission_id="mis_flight_001",
                    sequence=1,
                    event_type="mission.created",
                    aggregate_version=1,
                    payload_hash="c" * 64,
                    payload_json={},
                    occurred_at=t0,
                    recorded_at=t0,
                    created_at=t0,
                ),
                AgentMissionEvent(
                    id="mevt_02",
                    mission_id="mis_flight_001",
                    sequence=2,
                    event_type="plan.activated",
                    aggregate_version=2,
                    payload_hash="d" * 64,
                    payload_json={"plan": {"version": 1, "steps": [{"step_id": "step_mem"}]}},
                    occurred_at=t0 + timedelta(milliseconds=50),
                    recorded_at=t0 + timedelta(milliseconds=50),
                    created_at=t0 + timedelta(milliseconds=50),
                ),
                AgentMissionEvent(
                    id="mevt_03",
                    mission_id="mis_flight_001",
                    sequence=3,
                    event_type="attempt.completed",
                    aggregate_version=3,
                    payload_hash="e" * 64,
                    payload_json={
                        "attempt_id": "sat_mem_read",
                        "observation": {
                            "status": "succeeded",
                            "summary": "Found 1 risk memory item.",
                        },
                    },
                    occurred_at=t0 + timedelta(milliseconds=125),
                    recorded_at=t0 + timedelta(milliseconds=125),
                    created_at=t0 + timedelta(milliseconds=125),
                ),
                AgentMissionEvent(
                    id="mevt_04",
                    mission_id="mis_flight_001",
                    sequence=4,
                    event_type="mission.completion_proof_recorded",
                    aggregate_version=4,
                    payload_hash="f" * 64,
                    payload_json={"proof": {"passed": True, "gaps": []}},
                    occurred_at=t0 + timedelta(milliseconds=1400),
                    recorded_at=t0 + timedelta(milliseconds=1400),
                    created_at=t0 + timedelta(milliseconds=1400),
                ),
            ]
        )

    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            SESSION_SECRET="mission-flight-secret",
            KNOWLEDGE_DIR=tmp_path,
        ),
        db=db,
    )
    client = TestClient(app)

    assert client.get("/api/agent/runs/mis_missing/observability").status_code == 404
    assert client.get("/api/agent/runs/run_missing/observability").status_code == 404

    resp = client.get("/api/agent/runs/mis_flight_001/observability")
    assert resp.status_code == 200
    data = resp.json()

    assert data["schema_version"] == "agent-observability-v1"
    assert data["run"] == {
        "id": "mis_flight_001",
        "status": "completed",
        "provider": "mission_runtime",
        "model": "read_only.v1",
        "duration_ms": 1450.0,
        "started_at": t0.isoformat(),
        "completed_at": (t0 + timedelta(seconds=2)).isoformat(),
        "execution_mode": "governed_mission",
    }
    assert data["usage"] == {
        "input_tokens": 300,
        "output_tokens": 120,
        "cached_input_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 420,
        "request_count": 2,
        "reported_requests": 2,
        "unreported_requests": 0,
        "reported": True,
    }
    assert data["models"] == {"request_count": 2, "calls": []}
    assert data["tools"]["call_count"] == 4
    assert data["tools"]["error_count"] == 1
    assert data["tools"]["total_execution_ms"] == 870.0
    assert data["tools"]["slowest"]["tool_name"] == "bitpro.paper_snapshot"
    assert data["tools"]["slowest"]["execution_ms"] == 480.0

    assert data["memory"]["read_ids"] == [seeded_read.id]
    assert data["memory"]["write_ids"] == [written_mem.id]
    assert data["memory"]["read_count"] == 1
    assert data["memory"]["write_count"] == 1
    assert {item["id"] for item in data["memory"]["items"]} == {
        seeded_read.id,
        written_mem.id,
    }

    timeline = data["timeline"]
    assert [ev["sequence"] for ev in timeline] == list(range(1, len(timeline) + 1))
    valid_categories = {"graph", "model", "tool", "memory", "policy"}
    for ev in timeline:
        assert set(ev.keys()) >= {
            "id",
            "sequence",
            "category",
            "name",
            "status",
            "created_at",
            "offset_ms",
            "duration_ms",
            "summary",
        }
        assert ev["category"] in valid_categories
        assert ev["offset_ms"] >= 0
        assert ev["duration_ms"] >= 0

    mem_event = next(ev for ev in timeline if ev["id"] == "mevt_03")
    assert mem_event["category"] == "memory"
    assert mem_event["name"] == "memory.search"
    assert mem_event["memory_ids"] == [seeded_read.id]
    assert any(ev["id"] == "tcall_linked_001" and ev["category"] == "tool" for ev in timeline)
    assert any(ev["id"] == "mevt_04" and ev["category"] == "policy" for ev in timeline)

    assert sum(data["categories"].values()) == len(timeline)
    assert data["external_observability"] == {}
    assert data["safety"] == {
        "private_reasoning_stored": False,
        "secrets_redacted": True,
        "payload_mode": "summary",
        "evaluation_mode": False,
    }

    # Verify live SqlAlchemyMissionStore end-to-end projection with unreported (0-token) usage.
    mission_db_url = f"sqlite:///{tmp_path / 'mission_runtime.db'}"
    mission_db = Database(mission_db_url)
    mission_db.create_all()
    MarketRepository(mission_db).upsert_ticker_snapshot(
        inst_id="ETH-USDT-SWAP",
        inst_type="SWAP",
        last=Decimal("3200"),
        volume_ccy_24h=Decimal("90000"),
        change_utc0_pct=Decimal("1.2"),
    )

    async def _run_mission() -> str:
        store = SqlAlchemyMissionStore(mission_db_url)
        catalog = InMemoryCapabilityCatalog()
        await catalog.bootstrap(builtin_capabilities())
        runtime = MissionRuntime(
            store,
            DeterministicResearchPlanner(),
            GovernedToolExecutor(
                catalog,
                builtin_handlers(mission_db, knowledge_dir=str(tmp_path)),
                observations=InMemoryObservationStore(),
            ),
            CatalogCapabilityPolicy(catalog),
        )
        try:
            created = await runtime.create(
                MissionCreate(
                    objective="查看 ETH-USDT-SWAP 最新价格",
                    success_criteria=(
                        SuccessCriterionV1(
                            criterion_id="validated_steps",
                            kind="all_steps_validated",
                            description="Every step succeeded.",
                        ),
                    ),
                    idempotency_key="flight-e2e-1",
                )
            )
            finished = await runtime.run(created.mission_id)
            assert finished.status.value == "completed"
            return finished.mission_id
        finally:
            await store.dispose()

    live_mission_id = anyio.run(_run_mission)
    projected = AgentObservabilityService(mission_db).get(live_mission_id)
    assert projected["run"]["id"] == live_mission_id
    assert projected["run"]["provider"] == "mission_runtime"
    assert projected["run"]["execution_mode"] == "governed_mission"
    assert projected["usage"]["reported"] is False
    assert projected["tools"]["call_count"] >= 1
    assert projected["categories"]["policy"] >= 1
    assert projected["categories"]["graph"] >= 1
