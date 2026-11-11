"""The worker heartbeat's JSON on a real PostgreSQL: a stall's evidence round-trips."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from test_arc_event_journal_postgres import _cluster

T0 = datetime(2026, 11, 11, 7, 0, tzinfo=UTC)

EVIDENCE = {
    "cause": "other_thread",
    "scope": "process",
    "window_seconds": 11.1,
    "stack_source": "dump",
    "threads": [
        {"name": "MainThread", "loop": True, "cpu_seconds": 0.01, "stack": ["worker.py:124 once"]},
        {"name": "asyncio_2", "cpu_seconds": 10.4, "stack": ["avo.py:812 run", "thread.py:90 _w"]},
    ],
    "cpu": {"process_seconds": 10.5, "loop_thread_wait_seconds": 0.02},
    "gc": {"collections": 3, "pause_seconds": 0.04},
    "host": {"steal_seconds": 0.0, "major_faults": 0},
    "ongoing": False,
    "none": None,
}


def test_the_stall_evidence_survives_a_postgres_json_column(tmp_path) -> None:
    with _cluster(tmp_path) as url:
        from hypertrade.db import Database
        from hypertrade.runtime.heartbeat import (
            HeartbeatRegistry,
            WorkerHeartbeat,
            flush_heartbeat,
            read_worker_status,
        )

        db = Database(url)
        WorkerHeartbeat.__table__.create(db.engine)  # only the table under test
        registry = HeartbeatRegistry()
        registry.note_stall(10.6, ["worker.py:124 once"], new_episode=True, now=T0)
        registry.note_stall(10.8, evidence=EVIDENCE)
        registry.note_stall_cause("other_thread")
        stats = {"python": "3.14.2", "cpus": 2, "rss_mb": 812.3, "gc": {"collections": [10, 2, 1]}}

        for _ in range(2):  # the second flush updates the row the first one inserted
            assert flush_heartbeat(
                db,
                worker_id="worker",
                started_at=T0,
                registry=registry,
                now=T0,
                stats=lambda: stats,
            )

        (view,) = read_worker_status(db, now=T0 + timedelta(seconds=60))["instances"]

    assert view["last_stall"] == {
        "seconds": 10.8,
        "age_seconds": 60.0,
        "running": ["worker.py:124 once"],
        **EVIDENCE,
    }
    assert view["stall_causes"] == {"other_thread": 1}
    assert view["process"] == stats
    assert view["stalls_total"] == 1
