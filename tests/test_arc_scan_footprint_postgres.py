"""The queries of the scan footprint change, on a real PostgreSQL (the other tests run on SQLite).

The state filter, the revisions of many missions at once, the newest event of a type, and what the
scans and the budget make of them: the same answers as on SQLite, from the production dialect.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from test_arc_event_journal_postgres import _cluster
from test_arc_scan_footprint import STATES, _ledger, _research_mission

NOW = datetime(2026, 11, 11, 12, tzinfo=UTC)


def test_the_scan_queries_answer_the_same_on_postgresql(tmp_path, monkeypatch):
    with _cluster(tmp_path) as url:
        from hypertrade.arc import avo, evolution_continuation, research_budget, store
        from hypertrade.arc.evolution import EvolutionConfig
        from hypertrade.arc.evolution_continuation import ContinuationLedger
        from hypertrade.db import ArcMission, Database

        db = Database(url)
        db.create_all()
        store.reset_store()
        store.configure_store(db)
        try:
            missions = {state: _research_mission(state, n) for n, state in enumerate(STATES)}
            ids = {state: mission.mission_id for state, mission in missions.items()}
            store.reset_runtime()

            # The state filter and the revisions of many missions in one query.
            assert sorted(store.list_mission_ids(states={"failed", "completed"})) == sorted(
                [ids["failed"], ids["completed"]]
            )
            assert store.list_mission_ids(state="failed", states={"completed"}) == []
            assert store.list_mission_ids(states=set()) == []
            unknown = [f"arc_unknown_{number}" for number in range(700)]
            revisions = store.committed_revisions([*unknown, *ids.values()])
            assert revisions == {m.mission_id: m.revision for m in missions.values()}

            # The newest event of a type, with nothing else of the journal.
            waiting = missions["needs_operator"]
            waiting.apply_event("budget_extended", {"extra_candidates": 1})
            waiting.apply_event("operator_needed", {"reason": "second stop"})
            store.reset_runtime()
            with db.session() as session:
                row = session.get(ArcMission, waiting.mission_id)
                tail = store.load_projection_tail(session, row, ("operator_needed",))
                full = store.load_projection(session, row)
            assert [e.payload["reason"] for e in tail.events] == ["second stop"]
            assert len(full.events) > 1

            # The budget reads the same from the tail as from the whole journal.
            config = EvolutionConfig()
            with db.session() as session:
                fast = research_budget.usage(session, config, NOW)
            real = research_budget.load_projection
            monkeypatch.setattr(research_budget, "load_projection", lambda s, r, **_: real(s, r))
            monkeypatch.setattr(research_budget, "load_projection_tail", lambda s, r, t: real(s, r))
            with db.session() as session:
                reference = research_budget.usage(session, config, NOW)
            assert fast == reference and fast["total_used"] == len(STATES)
            monkeypatch.undo()

            # The AVO scan looks at what can need research and parks what cannot.
            looked: list[str] = []
            real_peek = avo.peek_controller
            monkeypatch.setattr(
                avo, "peek_controller", lambda m: (looked.append(m), real_peek(m))[1]
            )
            monkeypatch.setattr(avo, "run_avo_research", lambda m: {"status": "busy"})
            store.reset_runtime()
            avo.run_pending_avo_once()
            assert sorted(looked) == sorted([ids["exploring_candidates"], waiting.mission_id])
            assert store.cache_stats()["missions"] == 0
            looked.clear()
            avo.run_pending_avo_once()
            assert looked == [ids["exploring_candidates"]]
            monkeypatch.undo()

            # The ledger: computed once, and again only after a mission moves.
            monkeypatch.setattr(evolution_continuation, "_REFRESHED", None)
            ledger = ContinuationLedger(db)
            ledger.refresh(NOW)
            first = _ledger(db)
            assert first[0] and first[1]
            ledger.refresh(NOW + timedelta(minutes=1))
            assert _ledger(db) == first
            missions["exploring_candidates"].apply_event("operator_needed", {"reason": "x"})
            ledger.refresh(NOW + timedelta(minutes=2))
            assert _ledger(db) != first
            with db.session() as session:
                assert len(session.scalars(select(ArcMission)).all()) == len(STATES)
        finally:
            store.reset_store()
            db.engine.dispose()
