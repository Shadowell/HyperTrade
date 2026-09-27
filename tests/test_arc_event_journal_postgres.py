"""Event journal on a real PostgreSQL: migrations, row locks and two writer processes."""

import multiprocessing
import os
import shutil
import socket
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def _cluster(tmp_path):
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl or os.getuid() == 0:
        pytest.skip("isolated PostgreSQL binaries require an unprivileged local user")
    cluster = tmp_path / "pg"
    subprocess.run(
        [initdb, "-D", str(cluster), "-A", "trust", "-U", "journal_test", "--no-locale",
         "-E", "UTF8"],
        check=True,
        capture_output=True,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    subprocess.run(
        [pg_ctl, "-D", str(cluster), "-l", str(tmp_path / "pg.log"), "-w", "start", "-o",
         f"-p {port} -h 127.0.0.1 -k /tmp"],
        check=True,
        capture_output=True,
    )
    try:
        yield f"postgresql+psycopg://journal_test@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(cluster), "-w", "-m", "fast", "stop"],
            check=True,
            capture_output=True,
        )


def _alembic(url, *args):
    done = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr[-3000:]


def _writer(url, mission_id, tag, ready, count):
    from hypertrade.arc.store import configure_store, get_controller
    from hypertrade.db import Database

    db = Database(url)
    configure_store(db)
    ready.wait(timeout=30)
    for i in range(count):
        controller = get_controller(mission_id)
        controller.apply_event("paper_observed", {"observation": {"writer": tag, "i": i}})
    db.engine.dispose()


def test_legacy_rows_survive_upgrade_concurrent_writers_backfill_and_downgrade(tmp_path):
    with _cluster(tmp_path) as url:
        from hypertrade.arc import event_migration, store
        from hypertrade.db import ArcMission, Database
        from sqlalchemy import text
        from test_arc_store_concurrency import _paper_observing_mission

        db = Database(url)
        with db.engine.begin() as connection:
            # arc_missions as of 0047; the earlier chain needs pgvector, absent locally.
            connection.execute(text(
                "CREATE TABLE arc_missions (mission_id VARCHAR(64) PRIMARY KEY,"
                " state VARCHAR(48) NOT NULL, projection_json JSON NOT NULL,"
                " revision INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL,"
                " updated_at TIMESTAMPTZ NOT NULL)"
            ))
            connection.execute(text(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
            ))
            connection.execute(text(
                "INSERT INTO alembic_version VALUES ('0047_arc_runtime_journal')"
            ))
        legacy = []
        for extra in (40, 0):
            store.reset_store()
            controller = _paper_observing_mission()  # in-memory store
            for i in range(extra):
                controller.apply_event("paper_observed", {"observation": {"seed": i}})
            legacy.append(controller)
        with db.engine.begin() as connection:
            for controller in legacy:
                connection.execute(
                    text(
                        "INSERT INTO arc_missions (mission_id, state, projection_json, revision,"
                        " created_at, updated_at) VALUES (:m, :s, CAST(:p AS json), :r, now(),"
                        " now())"
                    ),
                    {
                        "m": controller.mission_id,
                        "s": controller.projection.state,
                        "p": controller.projection.model_dump_json(),
                        "r": len(controller.projection.events),
                    },
                )
        expected = {c.mission_id: c.projection.model_dump(mode="json") for c in legacy}

        _alembic(url, "upgrade", "head")
        store.reset_store()
        store.configure_store(db)
        before = event_migration.verify(db)
        assert before["inline_events"] == 46 and before["journal_rows"] == 0
        for controller in legacy:
            assert store.get_controller(controller.mission_id).projection.model_dump(
                mode="json"
            ) == expected[controller.mission_id]

        busy = legacy[0].mission_id
        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Barrier(2)
        writers = [
            ctx.Process(target=_writer, args=(url, busy, tag, ready, 15)) for tag in ("api", "wk")
        ]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join(timeout=60)
            assert writer.exitcode == 0

        report = event_migration.migrate(db)
        assert report["verified"]
        after = event_migration.verify(db)
        assert after["inline_events"] == 0 and after["journal_rows"] == 76
        store.reset_runtime()
        busy_events = store.get_controller(busy).projection.events
        assert len(busy_events) == len({e.event_id for e in busy_events}) == 73
        assert [e.event_id for e in busy_events[:43]] == [
            e["event_id"] for e in expected[busy]["events"]
        ]
        for tag in ("api", "wk"):
            order = [
                e.payload["observation"]["i"]
                for e in busy_events
                if e.payload.get("observation", {}).get("writer") == tag
            ]
            assert order == list(range(15))
        with db.session() as session:
            row = session.get(ArcMission, busy)
            assert row.revision == 73 and row.event_count == 73
            assert row.projection_json["events"] == []
        digests = {k: v["sha256"] for k, v in after["per_mission"].items()}

        store.reset_store()
        db.engine.dispose()
        _alembic(url, "downgrade", "0047_arc_runtime_journal")
        with db.engine.begin() as connection:
            inline = connection.execute(
                text("SELECT json_array_length(projection_json->'events') FROM arc_missions"
                     " WHERE mission_id = :m"),
                {"m": busy},
            ).scalar_one()
        assert inline == 73
        _alembic(url, "upgrade", "head")
        store.configure_store(db)
        assert event_migration.migrate(db)["moved_events"] == 76
        again = event_migration.verify(db)
        assert {k: v["sha256"] for k, v in again["per_mission"].items()} == digests
        store.reset_store()
        db.engine.dispose()
