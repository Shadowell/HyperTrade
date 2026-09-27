"""Mission events live in an append-only table; the projection row stops growing with them.

Legacy rows keep their events inline in ``projection_json``. Readers merge both layouts
(deduplicated by ``event_id``) so a process still running the old code during a deploy
can neither lose nor duplicate events, and the next commit moves inline events into the
table. The backfill is idempotent, verified per mission and reversible.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path

import pytest
from hypertrade.arc import store
from hypertrade.arc.controller import ARCEventV1
from hypertrade.db import ArcMission, Database
from sqlalchemy import select
from test_arc_store_concurrency import _in_other_process, _paper_observing_mission


@pytest.fixture
def db(tmp_path) -> Iterator[Database]:
    store.reset_store()
    database = Database(f"sqlite:///{tmp_path}/events.db")
    database.create_all()
    store.configure_store(database)
    yield database
    store.reset_store()


def _observe(controller, count: int, start: int = 0) -> None:
    for i in range(start, start + count):
        controller.apply_event("paper_observed", {"observation": {"tick": i, "pad": "x" * 200}})


def _table_events(db: Database, mission_id: str) -> list[tuple[int, str]]:
    from hypertrade.db import ArcMissionEvent

    with db.session() as session:
        rows = session.scalars(
            select(ArcMissionEvent)
            .where(ArcMissionEvent.mission_id == mission_id)
            .order_by(ArcMissionEvent.seq)
        ).all()
        return [(r.seq, r.event_id) for r in rows]


def _row(db: Database, mission_id: str) -> tuple[dict, int, int]:
    with db.session() as session:
        row = session.get(ArcMission, mission_id)
        return dict(row.projection_json), int(row.revision), int(row.event_count)


def _cold(mission_id: str):
    store.reset_runtime()
    return store.get_controller(mission_id)


def _legacy(db: Database, controller) -> None:
    """Rewrite the row the way the pre-migration code stored it: events inline."""
    from hypertrade.db import ArcMissionEvent

    with db.session() as session:
        session.query(ArcMissionEvent).filter_by(mission_id=controller.mission_id).delete()
        row = session.get(ArcMission, controller.mission_id)
        row.projection_json = controller.projection.model_dump(mode="json")
        row.event_count = 0


def test_events_append_to_their_table_and_the_projection_row_stays_small(db):
    controller = _paper_observing_mission()
    _observe(controller, 60)
    projection, revision, count = _row(db, controller.mission_id)
    assert projection["events"] == []
    assert count == len(controller.projection.events) == 63
    assert revision == 63
    seqs = _table_events(db, controller.mission_id)
    assert [s for s, _ in seqs] == list(range(1, 64))
    assert [e for _, e in seqs] == [e.event_id for e in controller.projection.events]
    before = controller.projection.model_dump(mode="json")
    assert _cold(controller.mission_id).projection.model_dump(mode="json") == before


def test_two_processes_interleave_without_loss_or_duplicates(db):
    controller = _paper_observing_mission()
    for i in range(5):
        _in_other_process(controller.mission_id, "paper_observed", {"observation": {"w": i}})
        controller.apply_event("paper_observed", {"observation": {"a": i}})
    ids = [e for _, e in _table_events(db, controller.mission_id)]
    assert len(ids) == len(set(ids)) == 13
    assert ids == [e.event_id for e in controller.projection.events]
    assert _row(db, controller.mission_id)[1] == 13
    assert _cold(controller.mission_id).projection.model_dump(mode="json") == (
        controller.projection.model_dump(mode="json")
    )


def test_legacy_inline_row_reads_identically_and_next_commit_moves_events(db):
    controller = _paper_observing_mission()
    _observe(controller, 10)
    _legacy(db, controller)
    expected = controller.projection.model_dump(mode="json")
    loaded = _cold(controller.mission_id)
    assert loaded.projection.model_dump(mode="json") == expected
    assert loaded.revision == _row(db, controller.mission_id)[1]
    loaded.apply_event("paper_observed", {"observation": {"after": True}})
    ids = [e for _, e in _table_events(db, controller.mission_id)]
    assert ids == [e["event_id"] for e in expected["events"]] + [
        loaded.projection.events[-1].event_id
    ]
    assert _row(db, controller.mission_id)[0]["events"] == []


def test_old_code_writing_inline_during_deploy_is_merged_once(db):
    """A pre-migration process reads the stripped row (events=[]) and appends inline."""
    controller = _paper_observing_mission()
    late = ARCEventV1(mission_id=controller.mission_id, event_type="paper_observed",
                      payload={"observation": {"late": 1}})
    with db.session() as session:
        row = session.get(ArcMission, controller.mission_id)
        stale = dict(row.projection_json)
        stale["events"] = [late.model_dump(mode="json")]
        row.projection_json = stale
        row.revision = int(row.revision) + 1
    loaded = _cold(controller.mission_id)
    assert [e.event_id for e in loaded.projection.events][-1] == late.event_id
    assert len(loaded.projection.events) == 4
    loaded.apply_event("paper_observed", {"observation": {"next": 1}})
    ids = [e for _, e in _table_events(db, controller.mission_id)]
    assert len(ids) == len(set(ids)) == 5 and ids[3] == late.event_id


def test_readers_outside_the_store_see_every_event(db):
    from hypertrade.arc.store import load_projection

    controller = _paper_observing_mission()
    _observe(controller, 3)
    with db.session() as session:
        row = session.get(ArcMission, controller.mission_id)
        projection = load_projection(session, row)
    assert [e.event_id for e in projection.events] == [
        e.event_id for e in controller.projection.events
    ]


def test_backfill_is_idempotent_verified_and_reversible(db):
    from hypertrade.arc import event_migration

    first = _paper_observing_mission()
    _observe(first, 20)
    second = _paper_observing_mission()
    expected = {
        c.mission_id: c.projection.model_dump(mode="json") for c in (first, second)
    }
    revisions = {c.mission_id: _row(db, c.mission_id)[1] for c in (first, second)}
    for c in (first, second):
        _legacy(db, c)

    dry = event_migration.migrate(db, dry_run=True)
    assert dry["moved_events"] == 26 and dry["verified"]
    assert _table_events(db, first.mission_id) == []

    report = event_migration.migrate(db)
    assert report["verified"] and report["moved_events"] == 26 and report["missions"] == 2
    for mission_id, projection in expected.items():
        assert _row(db, mission_id)[0]["events"] == []
        assert _row(db, mission_id)[1] == revisions[mission_id]
        assert _cold(mission_id).projection.model_dump(mode="json") == projection
        item = report["per_mission"][mission_id]
        assert item["before_sha256"] == item["after_sha256"]
    again = event_migration.migrate(db)
    assert again["moved_events"] == 0 and again["verified"]

    back = event_migration.rollback(db)
    assert back["verified"] and back["restored_events"] == 26
    for mission_id, projection in expected.items():
        assert _row(db, mission_id)[0]["events"] == projection["events"]
        assert _table_events(db, mission_id) == []
        assert _cold(mission_id).projection.model_dump(mode="json") == projection


def test_migration_schema_round_trip_folds_events_back(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text

    path = Path(__file__).parents[1] / "backend/alembic/versions/0048_arc_mission_events.py"
    spec = importlib.util.spec_from_file_location("arc_events_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{tmp_path}/m.db")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE arc_missions (mission_id VARCHAR(64) PRIMARY KEY, state VARCHAR(48),"
            " projection_json JSON, revision INTEGER, created_at DATETIME, updated_at DATETIME)"
        ))
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        module.upgrade()
        assert "arc_mission_events" in inspect(connection).get_table_names()
        columns = {c["name"] for c in inspect(connection).get_columns("arc_missions")}
        assert "event_count" in columns
        module.downgrade()
        assert "arc_mission_events" not in inspect(connection).get_table_names()
