"""Forward-outcome migration and unique pair on an isolated PostgreSQL cluster."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_arc_event_journal_postgres import _alembic, _cluster

INSERT = text(
    "INSERT INTO arc_forward_outcomes"
    " (id, target_id, parent_strategy_id, challenger_strategy_id, verdict,"
    " metrics_json, changes_json, scope_json)"
    " VALUES (:id, :target, :parent, :challenger, :verdict,"
    " CAST(:metrics AS json), CAST(:changes AS json), CAST(:scope AS json))"
)


def test_postgres_upgrade_write_unique_pair_and_downgrade(tmp_path) -> None:
    with _cluster(tmp_path) as url:
        from hypertrade.db import Database

        db = Database(url)
        with db.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
            )
            connection.execute(
                text("INSERT INTO alembic_version VALUES ('0049_arc_cognitive_memory')")
            )

        _alembic(url, "upgrade", "0050_arc_forward_outcomes")

        row = {
            "id": "fo_" + "a" * 32,
            "target": "bitpro",
            "parent": "41",
            "challenger": "42",
            "verdict": "handoff",
            "metrics": '{"relative_pnl": 0.08}',
            "changes": '{"fast_window": 7}',
            "scope": '{"symbols": ["BTC-USDT-SWAP"]}',
        }
        with db.engine.begin() as connection:
            connection.execute(INSERT, row)

        with db.engine.connect() as connection:
            stored = connection.execute(
                text(
                    "SELECT generation, verdict_source, lineage_status, evidence_sha256,"
                    " slot_no, mission_id, metrics_json, changes_json, scope_json"
                    " FROM arc_forward_outcomes WHERE id = :id"
                ),
                {"id": row["id"]},
            ).mappings().one()
        assert stored["generation"] == 1
        assert stored["verdict_source"] == "race_judge"
        assert stored["lineage_status"] == "pending"
        assert stored["evidence_sha256"] == ""
        assert stored["slot_no"] is None
        assert stored["mission_id"] is None
        assert stored["metrics_json"] == {"relative_pnl": 0.08}
        assert stored["changes_json"] == {"fast_window": 7}
        assert stored["scope_json"] == {"symbols": ["BTC-USDT-SWAP"]}

        with pytest.raises(IntegrityError), db.engine.begin() as connection:
            connection.execute(INSERT, {**row, "id": "fo_" + "b" * 32})

        db.engine.dispose()
        _alembic(url, "downgrade", "0049_arc_cognitive_memory")
        downgraded = Database(url)
        with downgraded.engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            assert version == "0049_arc_cognitive_memory"
            assert "arc_forward_outcomes" not in inspect(connection).get_table_names()
        downgraded.engine.dispose()
