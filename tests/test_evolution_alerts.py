from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypertrade.arc.evolution import EvolutionConfig
from hypertrade.arc.evolution_alerts import (
    ALERT_CYCLES_ERRORING,
    ALERT_OPERATOR_BLOCKED,
    ALERT_STALLED,
    acknowledge_alert,
    alert_id,
    evolution_alerts_once,
    list_alerts,
)
from hypertrade.arc.evolution_continuation import blocker_resolution, readiness
from hypertrade.arc.evolution_models import EvolutionAlert, EvolutionContinuation, EvolutionCycle
from hypertrade.arc.store import configure_store, reset_store
from hypertrade.config import get_settings
from hypertrade.db import Database

NOW = datetime(2026, 9, 14, 6, 0, tzinfo=UTC)


@pytest.fixture
def db():
    database = Database("sqlite:///:memory:")
    database.create_all()
    configure_store(database)
    yield database
    reset_store()


@pytest.fixture
def webhook(monkeypatch):
    sent: list[dict] = []

    def post(url: str, payload: dict) -> None:
        sent.append({"url": url, "payload": payload})

    monkeypatch.setattr(
        get_settings(), "feishu_webhook_url", "https://feishu.example/hook", raising=False
    )
    return sent, post


def seed_continuation(
    db: Database,
    strategy_id: int,
    *,
    blockers: list[dict],
    next_eligible_at: str | None = None,
    sampling_reason: str | None = None,
    observed_at: datetime = NOW,
) -> None:
    with db.session() as session:
        session.add(
            EvolutionContinuation(
                id=f"src_{strategy_id}",
                payload_json={
                    "strategy_id": strategy_id,
                    "observed_at": observed_at.isoformat(),
                    "next_eligible_at": next_eligible_at,
                    "blockers": blockers,
                    "evidence_cursor": {"sampling": {"reason_code": sampling_reason}},
                },
            )
        )


def seed_cycles(db: Database, statuses: list[tuple[str, datetime]]) -> None:
    with db.session() as session:
        for index, (status, created) in enumerate(statuses):
            session.add(
                EvolutionCycle(
                    id=f"cycle_{int(created.timestamp() * 1000)}_{index}",
                    status=status,
                    payload_json={},
                    created_at=created,
                )
            )


def touch_continuation(db: Database, strategy_id: int, observed_at: datetime) -> None:
    """Simulate the hourly scan refresh of a still-blocked strategy."""
    with db.session() as session:
        row = session.get(EvolutionContinuation, f"src_{strategy_id}")
        payload = dict(row.payload_json)
        payload["observed_at"] = observed_at.isoformat()
        row.payload_json = payload


def test_blocker_resolution_classification() -> None:
    assert blocker_resolution("session_identity") == "operator"
    assert blocker_resolution("session_start") == "operator"
    assert blocker_resolution("running_state") == "operator"
    assert blocker_resolution("minimum_trades") == "time"
    assert blocker_resolution("completed_utc_window") == "time"
    assert blocker_resolution("evidence_recheck") == "time"
    assert (
        blocker_resolution("evidence_recheck", sampling_reason="recent_read_unavailable")
        == "operator"
    )
    assert (
        blocker_resolution("evidence_recheck", sampling_reason="cost_metadata_unavailable")
        == "operator"
    )


def test_readiness_marks_resolution_and_attention() -> None:
    diagnostic = {
        "status": "unavailable",
        "reason": "gaps",
        "data_readiness": {"sampling": {}, "blocking_reason": "gaps"},
    }
    state = readiness({}, diagnostic, EvolutionConfig(), NOW)
    by_code = {b["code"]: b for b in state["blockers"]}
    assert by_code["session_identity"]["resolution"] == "operator"
    assert by_code["evidence_recheck"]["resolution"] == "time"
    assert state["attention_required"] is True

    running = {
        "instance_id": "paper-1",
        "strategy_id": 1,
        "strategy_version": "v1",
        "config_version": "c1",
        "status": "running",
        "trade_count": 100,
        "session": {"started_at": "2026-01-01T00:00:00Z"},
    }
    stable = readiness(running, {"status": "stable", "window": {}}, EvolutionConfig(), NOW)
    assert [b["code"] for b in stable["blockers"]] == ["degradation_threshold"]
    assert stable["blockers"][0]["resolution"] == "time"
    assert stable["attention_required"] is False


def test_operator_blocker_opens_and_delivers_once(db, webhook) -> None:
    sent, post = webhook
    seed_continuation(
        db, 333, blockers=[{"code": "session_identity"}, {"code": "evidence_recheck"}]
    )
    first = evolution_alerts_once(db, now=NOW, post=post)
    assert first["opened"] == 1 and first["delivered"] == 1
    assert len(sent) == 1
    assert "333" in sent[0]["payload"]["content"]["text"]
    assert "session_identity" in sent[0]["payload"]["content"]["text"]

    second = evolution_alerts_once(db, now=NOW + timedelta(hours=1), post=post)
    assert second["opened"] == 0 and second["delivered"] == 0
    assert len(sent) == 1  # deduplicated: no duplicate page for the same condition

    alerts = list_alerts(db)
    assert len(alerts) == 1
    assert alerts[0]["code"] == ALERT_OPERATOR_BLOCKED
    assert alerts[0]["status"] == "open"
    assert alerts[0]["delivery_result"] == "sent"


def test_evidence_stall_tracks_then_opens_after_horizon(db, webhook) -> None:
    sent, post = webhook
    seed_continuation(
        db,
        342,
        blockers=[{"code": "evidence_recheck"}],
        next_eligible_at=None,
    )
    first = evolution_alerts_once(db, now=NOW, post=post)
    assert first["tracking"] == 1 and first["delivered"] == 0
    assert list_alerts(db)[0]["status"] == "tracking"

    touch_continuation(db, 342, NOW + timedelta(hours=48))
    early = evolution_alerts_once(db, now=NOW + timedelta(hours=48), post=post)
    assert early["opened"] == 0 and early["delivered"] == 0

    touch_continuation(db, 342, NOW + timedelta(hours=73))
    late = evolution_alerts_once(db, now=NOW + timedelta(hours=73), post=post)
    assert late["opened"] == 1 and late["delivered"] == 1
    alert = list_alerts(db)[0]
    assert alert["code"] == ALERT_STALLED
    assert alert["status"] == "open"
    assert "持续" in alert["message"]


def test_stale_continuation_never_alerts(db, webhook) -> None:
    """A paused/removed strategy's frozen blockers are not an alert condition."""
    sent, post = webhook
    seed_continuation(
        db,
        107,
        blockers=[{"code": "session_identity"}],
        observed_at=NOW - timedelta(hours=4),
    )
    result = evolution_alerts_once(db, now=NOW, post=post)
    assert result["opened"] == 0 and result["tracking"] == 0
    assert list_alerts(db) == []


def test_pausing_a_strategy_resolves_its_open_alert(db, webhook) -> None:
    _, post = webhook
    seed_continuation(db, 296, blockers=[{"code": "session_identity"}])
    evolution_alerts_once(db, now=NOW, post=post)
    assert list_alerts(db)[0]["status"] == "open"
    # Strategy paused: the scan stops refreshing the continuation.
    result = evolution_alerts_once(db, now=NOW + timedelta(hours=4), post=post)
    assert result["resolved"] == 1
    assert list_alerts(db)[0]["status"] == "resolved"


def test_condition_clearing_resolves_alert(db, webhook) -> None:
    _, post = webhook
    seed_continuation(db, 333, blockers=[{"code": "session_identity"}])
    evolution_alerts_once(db, now=NOW, post=post)
    with db.session() as session:
        row = session.get(EvolutionContinuation, "src_333")
        session.delete(row)
    result = evolution_alerts_once(db, now=NOW + timedelta(hours=1), post=post)
    assert result["resolved"] == 1
    assert list_alerts(db)[0]["status"] == "resolved"


def test_cycle_error_streak_opens_critical_and_clears(db, webhook) -> None:
    _, post = webhook
    seed_cycles(
        db,
        [
            ("error", NOW - timedelta(hours=3)),
            ("error", NOW - timedelta(hours=2)),
            ("error", NOW - timedelta(hours=1)),
        ],
    )
    first = evolution_alerts_once(db, now=NOW, post=post)
    assert first["opened"] == 1
    alert = list_alerts(db)[0]
    assert alert["code"] == ALERT_CYCLES_ERRORING
    assert alert["severity"] == "critical"
    assert alert["strategy_id"] is None

    seed_cycles(db, [("no_action", NOW)])
    cleared = evolution_alerts_once(db, now=NOW + timedelta(hours=1), post=post)
    assert cleared["resolved"] == 1


def test_acknowledged_alerts_do_not_repage(db, webhook) -> None:
    sent, post = webhook
    seed_continuation(db, 333, blockers=[{"code": "session_identity"}])
    evolution_alerts_once(db, now=NOW, post=post)
    acked = acknowledge_alert(db, alert_id(ALERT_OPERATOR_BLOCKED, 333), actor="tester")
    assert acked["status"] == "acknowledged"
    again = evolution_alerts_once(db, now=NOW + timedelta(hours=1), post=post)
    assert again["opened"] == 0 and again["delivered"] == 0
    assert len(sent) == 1
    assert list_alerts(db)[0]["status"] == "acknowledged"
    with pytest.raises(KeyError):
        acknowledge_alert(db, "evoalert_missing", actor="tester")


def test_without_webhook_the_ledger_still_records(db, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "feishu_webhook_url", "", raising=False)
    seed_continuation(db, 333, blockers=[{"code": "session_identity"}])
    result = evolution_alerts_once(db, now=NOW)
    assert result["opened"] == 1 and result["delivered"] == 0
    alert = list_alerts(db)[0]
    assert alert["status"] == "open"
    assert alert["delivery_result"] == "skipped_no_webhook"
    with db.session() as session:
        row = session.get(EvolutionAlert, alert["id"])
        assert row is not None and row.delivered_at is None


def test_webhook_configured_later_delivers_on_next_evaluation(db, monkeypatch) -> None:
    """Not-configured is not a failed attempt: no retry-cadence penalty."""
    monkeypatch.setattr(get_settings(), "feishu_webhook_url", "", raising=False)
    seed_continuation(db, 333, blockers=[{"code": "session_identity"}])
    assert evolution_alerts_once(db, now=NOW)["opened"] == 1
    assert list_alerts(db)[0]["delivery_result"] == "skipped_no_webhook"

    sent: list[dict] = []
    monkeypatch.setattr(
        get_settings(), "feishu_webhook_url", "https://feishu.example/hook", raising=False
    )
    second = evolution_alerts_once(
        db, now=NOW + timedelta(minutes=2), post=lambda url, payload: sent.append(payload)
    )
    assert second["delivered"] == 1
    assert len(sent) == 1
    assert list_alerts(db)[0]["delivery_result"] == "sent"


def test_alerts_migration_creates_and_removes_only_its_table() -> None:
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    path = Path(__file__).parents[1] / "backend/alembic/versions/0046_evolution_alerts.py"
    spec = importlib.util.spec_from_file_location("alerts_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
        module.upgrade()
        assert "arc_evolution_alerts" in inspect(connection).get_table_names()
        module.downgrade()
        assert inspect(connection).get_table_names() == []
