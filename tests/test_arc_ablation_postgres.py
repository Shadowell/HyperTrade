"""Ablation migration, ORM writes and unique pairs on an isolated PostgreSQL cluster."""

from __future__ import annotations

import pytest
from hypertrade.arc.evolution_models import ArcAblationRun, ArcAblationStep
from hypertrade.db import Database
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_arc_event_journal_postgres import _alembic, _cluster


def test_postgres_upgrade_write_unique_pair_and_downgrade(tmp_path) -> None:
    with _cluster(tmp_path) as url:
        db = Database(url)
        with db.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
            )
            connection.execute(
                text("INSERT INTO alembic_version VALUES ('0050_arc_forward_outcomes')")
            )

        _alembic(url, "upgrade", "0051_arc_ablation_runs")

        run = {
            "outcome_id": "outcome-1",
            "target_id": "bitpro",
            "parent_strategy_id": "41",
            "challenger_strategy_id": "42",
        }
        with db.session() as session:
            session.add(ArcAblationRun(id="run-1", **run))
            session.add(
                ArcAblationStep(
                    id="step-1", run_id="run-1", step_key="baseline:41", kind="baseline"
                )
            )
            session.add(
                ArcAblationStep(
                    id="step-2", run_id="run-1", step_key="change:fast_window", kind="change"
                )
            )

        with pytest.raises(IntegrityError), db.session() as session:
            session.add(
                ArcAblationRun(
                    id="run-2",
                    **{**run, "outcome_id": "outcome-2"},
                )
            )

        db.engine.dispose()
        _alembic(url, "downgrade", "0050_arc_forward_outcomes")
        downgraded = Database(url)
        with downgraded.engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0050_arc_forward_outcomes"
            tables = set(inspect(connection).get_table_names())
            assert "arc_ablation_runs" not in tables
            assert "arc_ablation_steps" not in tables
        downgraded.engine.dispose()

        _alembic(url, "upgrade", "0051_arc_ablation_runs")
        rerun = Database(url)
        with rerun.engine.connect() as connection:
            assert {"arc_ablation_runs", "arc_ablation_steps"}.issubset(
                set(inspect(connection).get_table_names())
            )
        rerun.engine.dispose()
