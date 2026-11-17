"""The queries of the scan footprint change, on a real PostgreSQL (the other tests run on SQLite).

The state filter, the revisions of many missions at once, the newest event of a type, and what the
scans and the budget make of them: the same answers as on SQLite, from the production dialect.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import event, select, text
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

            # The budget reads lightweight fields + one batched operator_needed query and answers
            # the same as when every mission's whole journal is read.
            config = EvolutionConfig()
            with db.session() as session:
                fast = research_budget.usage(session, config, NOW)
            with db.session() as session:
                reference = research_budget._reduce_usage(
                    session, config, NOW, research_budget._usage_items_full(session)
                )
            assert fast == reference and fast["total_used"] == len(STATES)

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


def test_budget_usage_footprint_and_equivalence_on_postgresql(
    tmp_path: Any, monkeypatch: Any
) -> None:
    with _cluster(tmp_path) as url:
        from hypertrade.arc import research_budget, store
        from hypertrade.arc.contracts import ARCSuccessCriteriaV1
        from hypertrade.arc.evolution import EvolutionConfig
        from hypertrade.db import ArcMission, Database

        db = Database(url)
        db.create_all()
        store.reset_store()
        store.configure_store(db)
        try:
            missions = {state: _research_mission(state, n) for n, state in enumerate(STATES)}
            heavy_code = "x = 1\n" * 4000
            heavy_orders = [{"id": i, "blob": "z" * 120} for i in range(40)]
            for idx in range(6):
                extra_wait = _research_mission(
                    "needs_operator",
                    20 + idx,
                    reason=(
                        "avo_final_validation_failed"
                        if idx == 0
                        else ("avo_context_budget_exhausted" if idx % 2 else "manual_hold")
                    ),
                    success_criteria=ARCSuccessCriteriaV1(),
                )
                if idx == 0:
                    extra_wait.projection.avo["final_window_consumed"] = True
                    extra_wait.projection.self_test_records = [
                        {
                            "passed": False,
                            "backtest_id": "bt_pg_0",
                            "metrics": {"sharpe_ratio": 0.2, "trade_count": 25},
                        }
                    ]
                    store.save_mission(extra_wait)
                with db.session() as session:
                    row = session.get(ArcMission, extra_wait.mission_id)
                    assert row is not None
                    pj = dict(row.projection_json)
                    pj["goal"]["evolution_context"]["baseline"] = {
                        "strategy_code": heavy_code,
                        "strategy_spec": {"is_source_variant": True},
                    }
                    pj["goal"]["evolution_context"]["orders"] = heavy_orders
                    pj["attempts"] = [
                        {
                            "attempt_id": f"a_{idx}",
                            "candidate_id": f"c_{idx}",
                            "hypothesis": "h",
                            "strategy_code": heavy_code,
                            "strategy_spec": {"parameter_changes": {"k": idx}},
                        }
                    ]
                    row.projection_json = pj

            with db.session() as session:
                obs_row = session.get(ArcMission, missions["paper_observing"].mission_id)
                assert obs_row is not None
                obs_pj = dict(obs_row.projection_json)
                obs_pj["goal"]["evolution_context"]["variant_policy"] = {
                    "variant_creation_supported": True,
                    "baseline_backtest": {"policy": "pg-pol"},
                    "relay": {"slots": [1, 2, 3], "tried_variants": heavy_orders},
                }
                obs_pj["attempts"] = [
                    {
                        "attempt_id": "att_observed",
                        "candidate_id": "att_observed",
                        "hypothesis": "h",
                        "strategy_code": heavy_code,
                        "strategy_spec": {"parameter_changes": {"fast": True, "mult": 1.25}},
                    }
                ]
                obs_row.projection_json = obs_pj

                fail_row = session.get(ArcMission, missions["failed"].mission_id)
                assert fail_row is not None
                fail_pj = dict(fail_row.projection_json)
                fail_pj["avo"] = {
                    "terminal_execution_failure": {
                        "reasons": ["baseline_data_snapshot_unavailable"],
                        "message": "incomplete_official_bar_grid",
                    }
                }
                fail_pj["attempts"] = [
                    {
                        "attempt_id": "f_pg",
                        "candidate_id": "f_pg",
                        "hypothesis": "h",
                        "strategy_code": heavy_code,
                        "strategy_spec": {},
                    }
                ]
                fail_row.projection_json = fail_pj

                session.add(
                    ArcMission(
                        mission_id="arc_pg_bool_sid",
                        state="completed",
                        revision=1,
                        event_count=0,
                        projection_json={
                            "mission_id": "arc_pg_bool_sid",
                            "state": "completed",
                            "goal": {
                                "objective": "edge",
                                "feedback_parent": {},
                                "evolution_context": {
                                    "source_instance_id": "inst-pg-bool",
                                    "source_strategy_id": True,
                                },
                            },
                            "events": [],
                        },
                    )
                )
            store.reset_runtime()

            executed_sql: list[str] = []
            journal_reads: list[str] = []
            real_stored = store._stored_events
            monkeypatch.setattr(
                store,
                "_stored_events",
                lambda s, mid: (journal_reads.append(mid), real_stored(s, mid))[1],
            )

            def before_execute(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
                executed_sql.append(statement)

            config = EvolutionConfig()
            event.listen(db.engine, "before_cursor_execute", before_execute)
            try:
                with db.session() as session:
                    raw_bytes = int(
                        session.execute(
                            text(
                                "SELECT COALESCE(sum(length(projection_json::text)), 0)"
                                " FROM arc_missions"
                            )
                        ).scalar()
                        or 0
                    )
                    executed_sql.clear()
                    fast = research_budget.usage(session, config, NOW)
                    light_rows = store.load_budget_mission_rows(session)
                    assert light_rows is not None
                    light_bytes = len(json.dumps(light_rows, default=str).encode())
            finally:
                event.remove(db.engine, "before_cursor_execute", before_execute)

            event_queries = [stmt for stmt in executed_sql if "arc_mission_events" in stmt]
            assert journal_reads == []
            assert len(event_queries) == 1
            assert raw_bytes > 300_000 and light_bytes < raw_bytes // 10

            with db.session() as session:
                reference = research_budget._reduce_usage(
                    session, config, NOW, research_budget._usage_items_full(session)
                )
            assert fast == reference and fast["total_used"] == len(STATES) + 6
            assert all(
                src.get("source_instance_id") != "inst-pg-bool"
                for src in fast["sources"].values()
            )

            # Steady-state hot hit on PostgreSQL: 0 projection_json/json_to_record & 0 event reads.
            executed_sql.clear()
            event.listen(db.engine, "before_cursor_execute", before_execute)
            try:
                with db.session() as session:
                    hot = research_budget.usage(session, config, NOW)
            finally:
                event.remove(db.engine, "before_cursor_execute", before_execute)
            assert hot == fast
            assert not any("json_to_record" in stmt for stmt in executed_sql)
            assert not any("arc_mission_events" in stmt for stmt in executed_sql)

            # Incremental single-mission mutation invalidates and queries ONLY that row on PG.
            loaded_batches: list[list[str] | None] = []
            real_load = research_budget.load_budget_mission_rows
            monkeypatch.setattr(
                research_budget,
                "load_budget_mission_rows",
                lambda s, *, mission_ids=None: (
                    loaded_batches.append(list(mission_ids) if mission_ids is not None else None),
                    real_load(s, mission_ids=mission_ids),
                )[1],
            )
            missions["exploring_candidates"].apply_event(
                "operator_needed", {"reason": "avo_context_budget_exhausted"}
            )
            with db.session() as session:
                after_move = research_budget.usage(session, config, NOW)
            assert loaded_batches == [[missions["exploring_candidates"].mission_id]]
            with db.session() as session:
                assert after_move == research_budget._reduce_usage(
                    session, config, NOW, research_budget._usage_items_full(session)
                )
        finally:
            store.reset_store()
            db.engine.dispose()
