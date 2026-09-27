"""Evolution failures and model replies must survive container rebuilds (DB, not stdout)."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypertrade.arc.avo import run_avo_research
from hypertrade.arc.contracts import ARCBudgetV1, ARCGoalV1, ARCSuccessCriteriaV1
from hypertrade.arc.controller import ARCController
from hypertrade.arc.store import (
    configure_store,
    get_controller,
    reset_runtime,
    reset_store,
    save_mission,
)
from hypertrade.db import Database
from hypertrade.providers.chat import ChatResponse, TokenUsage, ToolCallRequest
from sqlalchemy import select
from test_avo_research import Experiments

SECRET = "sk-live-abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.fixture
def db(tmp_path):
    reset_store()
    database = Database(f"sqlite:///{tmp_path}/persist.db")
    database.create_all()
    configure_store(database)
    yield database
    reset_store()


@pytest.fixture
def mission(db):
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="研究趋势策略",
            paper_review_required=True,
            research_mode="avo",
            budget=ARCBudgetV1(max_candidates=2),
            success_criteria=ARCSuccessCriteriaV1(required_validation_policy="arc_windowed_v1"),
        )
    )
    save_mission(ctrl)
    return ctrl


def _errors(db):
    from hypertrade.arc.evolution_models import ArcRuntimeError

    with db.session() as session:
        return session.scalars(select(ArcRuntimeError)).all()


class ProposeThenDevelop:
    name = "fixture"
    model = "unit-test"

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            call = ToolCallRequest("c1", "propose", {"hypothesis": "trend"})
        else:
            call = ToolCallRequest("c2", "develop", {"attempt_id": "whatever"})
        return ChatResponse(
            content="思考过程" * 400,
            reasoning_content=f"reasoning api_key={SECRET}",
            tool_calls=[call],
            usage=TokenUsage(input_tokens=11, output_tokens=7, reported=True),
        )


def test_runtime_interruption_persists_redacted_traceback(db, mission, monkeypatch):
    from hypertrade.arc import avo

    def exploding(controller, name, arguments, experiments, check_owner=None):
        raise RuntimeError(f"upstream exploded api_key={SECRET}")

    monkeypatch.setattr(avo, "_perform", exploding)
    run_avo_research(mission.mission_id, provider=ProposeThenDevelop(), experiments=Experiments())
    reset_runtime()
    restored = get_controller(mission.mission_id)
    stop = [e.payload for e in restored.projection.events if e.event_type == "operator_needed"][-1]
    assert stop["reason"] == "avo_runtime_interrupted"
    assert "upstream exploded" in stop["error_message"]
    assert SECRET not in str(stop)
    rows = [r for r in _errors(db) if r.component == "avo.research"]
    assert len(rows) == 1
    row = rows[0]
    assert stop["error_id"] == row.id
    assert row.component == "avo.research"
    assert row.mission_id == mission.mission_id
    assert row.exception_type.endswith("RuntimeError")
    assert "exploding" in row.traceback
    assert any(frame.endswith(":exploding") for frame in row.frames_json)
    assert SECRET not in row.traceback and SECRET not in row.message


def test_side_effect_free_tool_error_is_journalled(db, mission, monkeypatch):
    from hypertrade.arc import avo

    real = avo._perform

    def flaky(controller, name, arguments, experiments, check_owner=None):
        if name == "propose":
            raise KeyError("family_key")
        return real(controller, name, arguments, experiments, check_owner)

    monkeypatch.setattr(avo, "_perform", flaky)
    run_avo_research(mission.mission_id, provider=ProposeThenDevelop(), experiments=Experiments())
    rows = [r for r in _errors(db) if r.component == "avo.tool"]
    assert len(rows) == 1
    assert rows[0].context_json["tool"] == "propose"
    assert rows[0].context_json["tool_call_id"] == "c1"
    assert "family_key" in rows[0].message


def test_model_reply_content_and_reasoning_are_stored(db, mission):
    from hypertrade.arc.evolution_models import ArcModelExchange

    run_avo_research(mission.mission_id, provider=ProposeThenDevelop(), experiments=Experiments())
    reset_runtime()
    events = get_controller(mission.mission_id).projection.events
    replies = [e.payload for e in events if e.event_type == "avo_model_replied"]
    requests = [e.payload for e in events if e.event_type == "avo_model_requested"]
    assert replies and all(r["exchange_id"].startswith("mx_") for r in replies)
    with db.session() as session:
        rows = session.scalars(select(ArcModelExchange)).all()
        # A rejected batch (duplicate call id) keeps its raw reply without a reply event.
        assert {r["exchange_id"] for r in replies} < {r.id for r in rows}
        first = session.get(ArcModelExchange, replies[0]["exchange_id"])
        assert first.content == "思考过程" * 400
        assert "reasoning" in first.reasoning_content
        assert SECRET not in first.reasoning_content
        assert first.request_hash == requests[0]["request_hash"]
        assert first.context_record_id
        assert first.tool_calls_json[0]["name"] == "propose"
        assert first.usage_json["input_tokens"] == 11


def test_repeated_failure_folds_into_one_row(db):
    from hypertrade.arc.runtime_journal import record_runtime_error

    def fail(i):
        try:
            raise ValueError(f"attempt {i}")
        except ValueError as exc:
            return record_runtime_error("worker.arc_evolution", exc)

    ids = {fail(i)["error_id"] for i in range(30)}
    rows = _errors(db)
    assert len(ids) == 1 and len(rows) == 1
    assert rows[0].occurrences == 30
    assert rows[0].message == "attempt 29"
    assert len(rows[0].recent_messages_json) == 20


def test_journal_write_failure_never_masks_original_error(db, monkeypatch):
    from hypertrade.arc import runtime_journal

    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "session", broken)
    try:
        raise ValueError("original")
    except ValueError as exc:
        described = runtime_journal.record_runtime_error("worker.x", exc, db=db)
    assert described["error_id"] is None
    assert described["message"] == "original"


def test_evolution_error_cycle_keeps_message_and_error_receipt(db, monkeypatch):
    from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
    from hypertrade.arc.evolution_models import EvolutionCycle
    from test_evolution_continuation import EvidencePaper

    service = EvolutionService(db, EvidencePaper())
    service.configure(EvolutionConfig(enabled=True), revision=0, actor="test")

    def scan(*args, **kwargs):
        raise RuntimeError(f"BitPro MCP 502 password={SECRET}")

    monkeypatch.setattr(service, "_scan", scan)
    result = service.tick(datetime(2026, 8, 10, 12, tzinfo=UTC))
    assert result["status"] == "error"
    with db.session() as session:
        errored = select(EvolutionCycle).where(EvolutionCycle.status == "error")
        cycle = session.scalars(errored).one()
        payload = dict(cycle.payload_json)
    assert payload["error"] == "RuntimeError"
    assert "BitPro MCP 502" in payload["error_message"]
    assert SECRET not in str(payload)
    rows = _errors(db)
    assert [r.id for r in rows] == [payload["error_id"]]
    assert rows[0].component == "evolution.tick"
    assert rows[0].context_json["cycle_id"] == cycle.id


def test_worker_loop_failure_is_journalled(db):
    import asyncio

    from hypertrade import worker

    calls = {"n": 0}

    def once():
        calls["n"] += 1
        raise RuntimeError("loop body failed")

    async def run():
        assert await worker._guarded(db, "worker.test", once) is None
        assert await worker._guarded(db, "worker.test", once) is None

    asyncio.run(run())
    rows = _errors(db)
    assert calls["n"] == 2
    assert len(rows) == 1 and rows[0].component == "worker.test" and rows[0].occurrences == 2


def test_context_snapshot_retention_covers_a_year():
    from hypertrade.agent.context_journal import SNAPSHOT_TTL

    assert SNAPSHOT_TTL.days >= 365


def test_runtime_journal_migration_round_trip():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = Path(__file__).parents[1] / "backend/alembic/versions/0047_arc_runtime_journal.py"
    spec = importlib.util.spec_from_file_location("runtime_journal_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        module.upgrade()
        assert {"arc_runtime_errors", "arc_model_exchanges"} <= set(
            inspect(connection).get_table_names()
        )
        module.downgrade()
        assert inspect(connection).get_table_names() == []
