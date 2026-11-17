"""Footprint, correctness, and non-residency invariants for ARC HTTP API endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypertrade.arc import router as arc_router
from hypertrade.arc import store
from hypertrade.arc.auth import hash_service_token
from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evidence_view import build_mission_summary
from hypertrade.arc.evolution_models import EvolutionCycle
from hypertrade.arc.pipeline_view import build_pipeline_view
from hypertrade.config import Settings
from hypertrade.db import ArcMission, ArcMissionEvent, Database
from hypertrade.main import create_app
from sqlalchemy import select

READ_TOKEN = "ht_svc_api_footprint_read"


@pytest.fixture
def db_client() -> Iterator[tuple[TestClient, Database]]:
    store.reset_store()
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="arc-api-footprint-secret",
        ARC_SERVICE_TOKENS=f"reader:arc:read:{hash_service_token(READ_TOKEN)}",
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        yield client, database
    store.reset_store()


def _headers() -> dict[str, str]:
    return {"X-HyperTrade-Service-Token": READ_TOKEN}


def _create_observing_mission(
    *,
    objective: str = "api footprint",
    ticks: int = 150,
    paper_review_required: bool = True,
    with_preflight: bool = False,
    with_red_team: bool = False,
) -> ARCController:
    goal = ARCGoalV1(
        objective=objective,
        research_mode="avo" if paper_review_required else "arc",
        paper_review_required=paper_review_required,
        research_windows=ResearchWindowsV1(),
        paper_initial_equity=Decimal("100"),
        budget=ARCBudgetV1(max_candidates=5),
    )
    ctrl = ARCController(goal=goal)
    ctrl.apply_event("goal_compiled", {"goal": goal.model_dump(mode="json")})
    ctrl.apply_event("provider_status", {"status": "ok"})
    attempt = ARCCandidateAttemptV1(
        attempt_id="att_1",
        candidate_id="cand_1",
        hypothesis="trend hypothesis",
        strategy_code="class SecretStrategy:\n    pass\n",
        strategy_spec={"family": "trend_following", "timeframe": "1H"},
    )
    ctrl.apply_event("candidate_proposed", {"attempt": attempt.model_dump(mode="json")})
    if with_red_team:
        ctrl.apply_event(
            "red_team_tested",
            {
                "attempt_id": "att_1",
                "passed": True,
                "metrics": {"ranking_sharpe": 1.25},
            },
        )
    ctrl.apply_event("paper_started", {"attempt_id": "att_1", "paper_instance_id": "paper_42"})
    for tick in range(ticks):
        ctrl.apply_event(
            "paper_observed",
            {"observation": {"tick": tick, "trades": tick, "equity": 100.0 + tick}},
        )
    if with_preflight:
        ctrl.apply_event(
            "operator_needed",
            {
                "reason": "evidence_window_unavailable",
                "preflight": {
                    "source_origin": "okx_swap",
                    "window_as_of": "2026-11-11T00:00:00+00:00",
                    "bars_available": 800,
                },
            },
        )
    return ctrl


def test_list_arc_missions_skips_journal_reads_and_matches_full_projection(
    db_client: tuple[TestClient, Database], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, database = db_client
    first = _create_observing_mission(objective="first", ticks=40)
    second = _create_observing_mission(
        objective="second",
        ticks=120,
        paper_review_required=False,
        with_preflight=True,
        with_red_team=True,
    )
    expected = {}
    for ctrl in (first, second):
        expected[ctrl.mission_id] = build_mission_summary(ctrl.projection)

    store.reset_runtime()
    journal_reads: list[str] = []
    real_stored = store._stored_events
    monkeypatch.setattr(
        store,
        "_stored_events",
        lambda session, mid: (journal_reads.append(mid), real_stored(session, mid))[1],
    )

    validated_event_batches: list[list[str]] = []
    real_validate = store.ARCMissionProjection.model_validate

    def spy_validate(obj: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(obj, dict):
            validated_event_batches.append(
                [
                    str(e.get("event_type") or "")
                    for e in (obj.get("events") or [])
                    if isinstance(e, dict)
                ]
            )
        return real_validate(obj, *args, **kwargs)

    threadpool_calls: list[str] = []
    real_threadpool = arc_router.run_in_threadpool

    async def spy_threadpool(func: Any, *args: Any, **kwargs: Any) -> Any:
        threadpool_calls.append(getattr(func, "__name__", repr(func)))
        return await real_threadpool(func, *args, **kwargs)

    monkeypatch.setattr(arc_router, "run_in_threadpool", spy_threadpool)
    monkeypatch.setattr(store.ARCMissionProjection, "model_validate", spy_validate)

    resp = client.get("/api/v1/arc/missions?limit=10", headers=_headers())
    assert resp.status_code == 200
    assert threadpool_calls == ["list_mission_summaries"]
    assert journal_reads == []
    assert store.cache_stats() == {"missions": 0, "events": 0, "by_state": {}}
    assert validated_event_batches
    assert all("paper_observed" not in batch for batch in validated_event_batches)

    items = resp.json()["missions"]
    assert len(items) == 2
    by_id = {item["mission_id"]: item for item in items}
    assert by_id == expected

    # State filtering + limit respected without scanning beyond limit
    validated_event_batches.clear()
    filtered = client.get(
        "/api/v1/arc/missions?state=needs_operator&limit=1", headers=_headers()
    )
    assert filtered.status_code == 200
    assert [m["mission_id"] for m in filtered.json()["missions"]] == [second.mission_id]
    assert len(validated_event_batches) == 1
    assert "paper_observed" not in validated_event_batches[0]


def test_list_mission_summaries_supports_in_memory_and_legacy_inline_events(
    db_client: tuple[TestClient, Database],
) -> None:
    client, database = db_client
    legacy = _create_observing_mission(objective="legacy inline", ticks=5)
    expected_legacy = build_mission_summary(legacy.projection)
    inline = [e.model_dump(mode="json") for e in legacy.projection.events]
    with database.session() as session:
        session.query(ArcMissionEvent).filter_by(mission_id=legacy.mission_id).delete()
        row = session.get(ArcMission, legacy.mission_id)
        assert row is not None
        row.projection_json = {**row.projection_json, "events": inline}
        row.event_count = 0
    store.reset_runtime()

    resp = client.get("/api/v1/arc/missions", headers=_headers())
    assert resp.status_code == 200
    assert resp.json()["missions"] == [expected_legacy]
    assert store.cache_stats()["missions"] == 0

    # Pure in-memory mode (_database is None) remains 100% compatible.
    store.reset_store()
    try:
        mem = _create_observing_mission(objective="memory", ticks=3)
        expected_mem = build_mission_summary(mem.projection)
        assert store.list_mission_summaries(state="paper_observing", limit=10) == [expected_mem]
    finally:
        store.reset_store()


def test_readonly_detail_endpoints_use_peek_and_threadpool_without_populating_missions(
    db_client: tuple[TestClient, Database], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = db_client
    active = _create_observing_mission(objective="active", ticks=2)
    # Put an active mission into exploring_candidates so even an active mission wouldn't get
    # cached by read-only endpoints once evicted from MISSIONS by reset_runtime().
    active_research = ARCController(
        goal=ARCGoalV1(objective="active research", budget=ARCBudgetV1(max_candidates=2))
    )
    active_research.apply_event(
        "goal_compiled", {"goal": active_research.projection.goal.model_dump()}
    )
    active_research.apply_event(
        "candidate_proposed",
        {
            "attempt": ARCCandidateAttemptV1(
                attempt_id="att_active",
                candidate_id="cand_active",
                hypothesis="h",
                strategy_code="class Active: pass",
                strategy_spec={"family": "trend_following"},
            ).model_dump(mode="json")
        },
    )
    store.reset_runtime()

    threadpool_hits = 0
    real_threadpool = arc_router.run_in_threadpool

    async def spy_threadpool(func: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal threadpool_hits
        threadpool_hits += 1
        return await real_threadpool(func, *args, **kwargs)

    monkeypatch.setattr(arc_router, "run_in_threadpool", spy_threadpool)

    for path in (
        f"/api/v1/arc/missions/{active_research.mission_id}",
        f"/api/v1/arc/missions/{active_research.mission_id}/evidence",
        f"/api/v1/arc/missions/{active_research.mission_id}/candidates/att_active",
        f"/api/v1/arc/missions/{active_research.mission_id}/paper-review",
        f"/api/v1/arc/missions/{active.mission_id}",
        f"/api/v1/arc/missions/{active.mission_id}/evidence",
    ):
        r = client.get(path, headers=_headers())
        assert r.status_code == 200, path
        assert store.MISSIONS == {}, f"{path} polluted store.MISSIONS"

    assert threadpool_hits == 6


def test_progress_endpoint_reads_latest_100_and_stage_events_matching_full_projection(
    db_client: tuple[TestClient, Database], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = db_client
    mission = _create_observing_mission(
        objective="heavy progress",
        ticks=240,
        paper_review_required=False,
        with_preflight=True,
        with_red_team=True,
    )
    full_projection = mission.projection
    assert len(full_projection.events) == 246

    store.reset_runtime()
    journal_reads: list[str] = []
    real_stored = store._stored_events
    monkeypatch.setattr(
        store,
        "_stored_events",
        lambda session, mid: (journal_reads.append(mid), real_stored(session, mid))[1],
    )

    fixed_now = datetime(2026, 11, 18, 12, tzinfo=UTC)
    real_build_pipeline = arc_router.build_pipeline_view

    def build_at_fixed_now(proj: Any, **kwargs: Any) -> dict[str, Any]:
        return real_build_pipeline(proj, now=fixed_now, **kwargs)

    monkeypatch.setattr(arc_router, "build_pipeline_view", build_at_fixed_now)

    validated_counts: list[int] = []
    real_validate = store.ARCMissionProjection.model_validate

    def spy_validate(obj: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(obj, dict):
            validated_counts.append(len(obj.get("events") or []))
        return real_validate(obj, *args, **kwargs)

    monkeypatch.setattr(store.ARCMissionProjection, "model_validate", spy_validate)

    threadpool_hits = 0
    real_threadpool = arc_router.run_in_threadpool

    async def spy_threadpool(func: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal threadpool_hits
        threadpool_hits += 1
        return await real_threadpool(func, *args, **kwargs)

    monkeypatch.setattr(arc_router, "run_in_threadpool", spy_threadpool)

    resp = client.get(f"/api/v1/arc/missions/{mission.mission_id}/progress", headers=_headers())
    assert resp.status_code == 200
    assert threadpool_hits == 1
    assert journal_reads == []
    assert store.MISSIONS == {}
    # 100 latest events (incl. trailing operator_needed) + 3 earlier stage events = 103, not 246.
    assert validated_counts == [103]

    expected = build_pipeline_view(full_projection, now=fixed_now)
    actual = resp.json()
    assert actual == expected
    assert actual["event_count"] == 246
    assert len(actual["activity"]) == 100

    # Also test when preflight/operator_needed occurred BEFORE >100 paper_observed ticks and when
    # seq=1 is not in _SUMMARY_EVENT_TYPES (created_at parity for list_mission_summaries).
    older = ARCController(
        goal=ARCGoalV1(
            objective="early preflight",
            research_mode="avo",
            paper_review_required=True,
            budget=ARCBudgetV1(max_candidates=3),
        )
    )
    older.apply_event("avo_initialized", {"messages": [{"role": "user", "content": "hi"}]})
    older.apply_event("goal_compiled", {"goal": older.projection.goal.model_dump(mode="json")})
    older.apply_event(
        "operator_needed",
        {
            "reason": "evidence_window_unavailable",
            "preflight": {
                "source_origin": "okx_swap",
                "window_as_of": "2026-11-10T00:00:00+00:00",
                "bars_available": 600,
            },
        },
    )
    for tick in range(120):
        older.apply_event("paper_observed", {"observation": {"tick": tick}})
    expected_older_progress = build_pipeline_view(older.projection, now=fixed_now)
    expected_older_summary = build_mission_summary(older.projection)
    store.reset_runtime()
    journal_reads.clear()

    older_prog_resp = client.get(
        f"/api/v1/arc/missions/{older.mission_id}/progress", headers=_headers()
    )
    assert older_prog_resp.status_code == 200
    assert older_prog_resp.json() == expected_older_progress
    assert journal_reads == []

    listed = client.get("/api/v1/arc/missions?limit=10", headers=_headers())
    assert listed.status_code == 200
    older_summary = next(
        m for m in listed.json()["missions"] if m["mission_id"] == older.mission_id
    )
    assert older_summary == expected_older_summary
    assert journal_reads == []


def test_evolution_endpoint_compact_and_cycles_limit_preserve_db_and_compatibility(
    db_client: tuple[TestClient, Database],
) -> None:
    client, database = db_client
    base_time = datetime(2026, 11, 18, 0, tzinfo=UTC)
    with database.session() as session:
        for idx in range(5):
            session.add(
                EvolutionCycle(
                    id=f"evo_0_{idx}",
                    status="no_action",
                    created_at=base_time + timedelta(hours=idx),
                    updated_at=base_time + timedelta(hours=idx),
                    payload_json={
                        "preview": False,
                        "revision": 0,
                        "diagnostics": [
                            {"strategy_id": 100 + idx, "status": "stable"},
                            {"strategy_id": 200 + idx, "status": "unavailable"},
                        ],
                    },
                )
            )

    # Default (no params): 100% backward compatible full diagnostics on all cycles.
    full_resp = client.get("/api/v1/arc/evolution", headers=_headers())
    assert full_resp.status_code == 200
    full_cycles = full_resp.json()["cycles"]
    assert len(full_cycles) == 5
    assert all("diagnostics" in c["payload"] for c in full_cycles)

    # compact=true: newest 2 cycles keep full diagnostics; older cycles carry summary only.
    compact_resp = client.get("/api/v1/arc/evolution?compact=true", headers=_headers())
    assert compact_resp.status_code == 200
    compact_cycles = compact_resp.json()["cycles"]
    assert [c["id"] for c in compact_cycles] == [
        "evo_0_4",
        "evo_0_3",
        "evo_0_2",
        "evo_0_1",
        "evo_0_0",
    ]
    assert "diagnostics" in compact_cycles[0]["payload"]
    assert "diagnostics" in compact_cycles[1]["payload"]
    assert "diagnostics_summary" not in compact_cycles[0]["payload"]
    for older in compact_cycles[2:]:
        assert "diagnostics" not in older["payload"]
        assert older["payload"]["diagnostics_summary"] == {
            "count": 2,
            "by_status": {"stable": 1, "unavailable": 1},
        }
        assert older["payload"]["preview"] is False
        assert older["payload"]["revision"] == 0

    # cycles_limit restricts count; validation enforces 1 <= cycles_limit <= 20.
    limited_resp = client.get(
        "/api/v1/arc/evolution?compact=true&cycles_limit=3", headers=_headers()
    )
    assert limited_resp.status_code == 200
    assert [c["id"] for c in limited_resp.json()["cycles"]] == ["evo_0_4", "evo_0_3", "evo_0_2"]
    assert client.get("/api/v1/arc/evolution?cycles_limit=0", headers=_headers()).status_code == 422
    assert (
        client.get("/api/v1/arc/evolution?cycles_limit=21", headers=_headers()).status_code == 422
    )

    # Database rows remain completely untouched.
    with database.session() as session:
        stored = session.scalars(select(EvolutionCycle)).all()
        assert all("diagnostics" in row.payload_json for row in stored)
    after_full = client.get("/api/v1/arc/evolution", headers=_headers())
    assert after_full.status_code == 200
    assert all("diagnostics" in c["payload"] for c in after_full.json()["cycles"])
