"""Exercise production row/advisory locking on an isolated local PostgreSQL cluster."""

import multiprocessing
import os
import shutil
import socket
import subprocess
from datetime import UTC, datetime

import pytest


def _submit(url, ready, output, source):
    from hypertrade.arc.contracts import ARCGoalV1
    from hypertrade.arc.controller import ARCController
    from hypertrade.arc.research_budget import admit
    from hypertrade.arc.store import configure_store
    from hypertrade.db import Database

    db = Database(url)
    configure_store(db)
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="concurrent admission",
            evolution_context={
                "source_instance_id": source,
                "source_strategy_id": 44,
                "trigger_source": "degradation",
            },
        )
    )
    ready.wait(timeout=20)
    result = admit(ctrl, now=datetime.now(UTC), db=db)
    output.put(result)
    db.engine.dispose()


def test_two_postgres_workers_share_one_atomic_credit(tmp_path):
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl or os.getuid() == 0:
        pytest.skip("isolated PostgreSQL binaries require an unprivileged local user")
    from hypertrade.arc.evolution import EvolutionConfig, EvolutionService
    from hypertrade.arc.evolution_models import EvolutionControl, EvolutionCycle
    from hypertrade.arc.store import configure_store, reset_store
    from hypertrade.db import ArcMission, Database
    from sqlalchemy import select

    cluster = tmp_path / "pg"
    subprocess.run(
        [
            initdb,
            "-D",
            str(cluster),
            "-A",
            "trust",
            "-U",
            "budget_test",
            "--no-locale",
            "-E",
            "UTF8",
        ],
        check=True,
        capture_output=True,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    subprocess.run(
        [
            pg_ctl,
            "-D",
            str(cluster),
            "-l",
            str(tmp_path / "pg.log"),
            "-w",
            "start",
            "-o",
            f"-p {port} -h 127.0.0.1 -k /tmp",
        ],
        check=True,
        capture_output=True,
    )
    db = Database(f"postgresql+psycopg://budget_test@127.0.0.1:{port}/postgres")
    try:
        for model in (EvolutionControl, EvolutionCycle, ArcMission):
            model.__table__.create(db.engine)
        configure_store(db)
        service = EvolutionService(db)
        service.configure(
            EvolutionConfig(enabled=True, max_research_per_day=1), revision=0, actor="test"
        )
        ctx = multiprocessing.get_context("spawn")
        ready, output = ctx.Barrier(2), ctx.Queue()
        workers = [
            ctx.Process(target=_submit, args=(db.url, ready, output, f"source-{i}"))
            for i in range(2)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=30)
            assert worker.exitcode == 0
        results = [output.get(timeout=5) for _ in workers]
        assert sum(row["accepted"] for row in results) == 1
        with db.session() as session:
            assert len(list(session.scalars(select(ArcMission)))) == 1
            assert (
                len(
                    list(
                        session.scalars(
                            select(EvolutionCycle).where(EvolutionCycle.status == "budget_admitted")
                        )
                    )
                )
                == 1
            )
        assert service.status()["budget"]["period_used"] == 1
    finally:
        reset_store()
        db.engine.dispose()
        subprocess.run(
            [pg_ctl, "-D", str(cluster), "-w", "-m", "fast", "stop"],
            check=True,
            capture_output=True,
        )
