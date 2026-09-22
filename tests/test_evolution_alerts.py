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


def test_source_provenance_alert_is_not_hidden_by_waiting_window(db, webhook):
    sent, post = webhook
    snapshot = {
        "strategy_id": 511,
        "instance_id": "paper_original",
        "strategy_version": "v1",
        "config_version": "c1",
        "status": "running",
        "trade_count": 80,
        "session": {"started_at": (NOW - timedelta(days=2)).isoformat()},
    }
    diagnostic = {"status": "unavailable", "reason": "window incomplete"}
    original = readiness(snapshot, diagnostic, EvolutionConfig(), NOW)
    diagnostic["attribution_report"] = {
        "provenance": {
            "status": "unknown",
            "blocking_reasons": [
                "historical_cost_metadata_missing",
                "historical_code_version_missing",
                "execution_version_unverified",
            ],
        }
    }
    state = readiness(snapshot, diagnostic, EvolutionConfig(), NOW)
    # Alert visibility must not rewrite the eligibility conditions or time lower bound.
    assert state["blockers"] == original["blockers"]
    assert state["next_eligible_at"] == original["next_eligible_at"]
    assert state["attention_required"] is True
    with db.session() as session:
        session.add(EvolutionContinuation(id="src_511", payload_json={**state, "strategy_id": 511}))
    evolution_alerts_once(db, now=NOW, post=post)
    message = list_alerts(db)[0]["message"]
    assert len(sent) == 1
    assert "历史成本" in message and "历史源码" in message and "执行版本" in message
    assert "禁止" in message and "最早时间条件" in message

    diagnostic["attribution_report"]["provenance"] = {
        "status": "verified", "blocking_reasons": []
    }
    recovered = readiness(snapshot, diagnostic, EvolutionConfig(), NOW + timedelta(minutes=1))
    with db.session() as session:
        session.get(EvolutionContinuation, "src_511").payload_json = {
            **recovered, "strategy_id": 511
        }
    evolution_alerts_once(db, now=NOW + timedelta(minutes=1), post=post)
    assert list_alerts(db)[0]["status"] == "resolved"


def test_source_alert_does_not_hide_sampling_failure_or_echo_unknown_reason(db, webhook):
    _, post = webhook
    seed_continuation(
        db, 511, blockers=[{"code": "evidence_recheck"}],
        sampling_reason="recent_read_unavailable",
    )
    with db.session() as session:
        row = session.get(EvolutionContinuation, "src_511")
        row.payload_json = {
            **row.payload_json,
            "evidence_cursor": {
                **row.payload_json["evidence_cursor"],
                "source_provenance": {
                    "status": "unknown",
                    "blocking_reasons": ["historical_cost_metadata_missing"],
                },
            },
        }
    evolution_alerts_once(db, now=NOW, post=post)
    assert "近期证据读取失败" in list_alerts(db)[0]["message"]
    assert "历史成本" in list_alerts(db)[0]["message"]
    with db.session() as session:
        row = session.get(EvolutionContinuation, "src_511")
        row.payload_json = {
            **row.payload_json,
            "blockers": [],
            "evidence_cursor": {
                "source_provenance": {
                    "status": "unknown", "blocking_reasons": ["secret-token-do-not-copy"]
                }
            },
        }
    evolution_alerts_once(db, now=NOW + timedelta(minutes=1), post=post)
    message = list_alerts(db)[0]["message"]
    assert "来源核验" in message
    assert "secret-token" not in message


@pytest.mark.parametrize("body", [{"code": 19024}, {}, {"StatusCode": 1}, {"code": False}])
def test_http_success_with_business_failure_is_not_delivered(db, monkeypatch, webhook, body):
    import httpx

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(
            200, json=body, request=httpx.Request("POST", "https://example.test")
        ),
    )
    seed_continuation(db, 511, blockers=[{"code": "session_identity"}])
    result = evolution_alerts_once(db, now=NOW)
    assert result["delivered"] == 0
    assert result["failed"] == 1
    assert list_alerts(db)[0]["delivered_at"] is None


def test_daily_reminder_until_acknowledged(db, webhook):
    sent, post = webhook
    seed_continuation(db, 511, blockers=[{"code": "session_identity"}])
    evolution_alerts_once(db, now=NOW, post=post)
    touch_continuation(db, 511, NOW + timedelta(hours=23))
    evolution_alerts_once(db, now=NOW + timedelta(hours=23), post=post)
    assert len(sent) == 1
    touch_continuation(db, 511, NOW + timedelta(hours=24))
    evolution_alerts_once(db, now=NOW + timedelta(hours=24), post=post)
    assert len(sent) == 2
    alert = list_alerts(db)[0]
    assert alert["delivery_count"] == 2
    assert alert["delivery_verified"] is True
    acknowledge_alert(db, alert["id"], actor="operator")
    touch_continuation(db, 511, NOW + timedelta(hours=49))
    evolution_alerts_once(db, now=NOW + timedelta(hours=49), post=post)
    assert len(sent) == 2


def test_unresolved_delivery_retries_after_seven_days(db, webhook):
    sent, post = webhook
    seed_continuation(db, 511, blockers=[{"code": "session_identity"}])

    def fail(url, payload):
        raise TimeoutError()

    evolution_alerts_once(db, now=NOW, post=fail)
    later = NOW + timedelta(days=8)
    touch_continuation(db, 511, later)
    result = evolution_alerts_once(db, now=later, post=post)
    assert result["delivered"] == 1 and len(sent) == 1


def test_reappearing_alert_does_not_inherit_failed_attempt_cooldown(db, webhook):
    _, post = webhook
    seed_continuation(db, 511, blockers=[{"code": "session_identity"}])

    def fail(url, payload):
        raise TimeoutError()

    evolution_alerts_once(db, now=NOW, post=fail)
    with db.session() as session:
        session.delete(session.get(EvolutionContinuation, "src_511"))
    evolution_alerts_once(db, now=NOW + timedelta(hours=1), post=post)
    seed_continuation(
        db, 511, blockers=[{"code": "session_identity"}], observed_at=NOW + timedelta(hours=2)
    )
    result = evolution_alerts_once(db, now=NOW + timedelta(hours=2), post=post)
    assert result["delivered"] == 1


def test_operator_alert_explains_evidence_failure_and_next_action(db, webhook):
    sent, post = webhook
    seed_continuation(
        db,
        511,
        blockers=[{"code": "evidence_recheck"}],
        sampling_reason="source_point_limit_exceeded",
    )
    evolution_alerts_once(db, now=NOW, post=post)
    assert len(sent) == 1
    message = sent[0]["payload"]["content"]["text"]
    assert "采样点数" in message and "下一步" in message
    assert "evidence_recheck" not in message


def test_unresolved_alerts_are_not_hidden_by_recent_resolved_rows(db):
    with db.session() as session:
        for i in range(60):
            session.add(
                EvolutionAlert(
                    id=f"a{i}",
                    code=ALERT_OPERATOR_BLOCKED,
                    severity="warning",
                    strategy_id=i,
                    message="test",
                    status="open" if i == 0 else "resolved",
                    created_at=NOW + timedelta(minutes=i),
                    payload_json={},
                )
            )
    assert list_alerts(db, limit=10)[0]["id"] == "a0"


@pytest.mark.parametrize("body", [{"code": 0}, {"StatusCode": 0}, {"code": 0, "StatusCode": 0}])
def test_business_success_receipt_is_verified(db, monkeypatch, webhook, body):
    import httpx

    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **kw: httpx.Response(
            200, json=body, request=httpx.Request("POST", "https://example.test")
        ),
    )
    seed_continuation(db, 511, blockers=[{"code": "session_identity"}])
    evolution_alerts_once(db, now=NOW)
    assert list_alerts(db)[0]["delivery_verified"] is True
    assert list_alerts(db)[0]["delivery_business_code"] == 0


def test_legacy_sent_is_unverified_until_next_real_delivery(db, webhook):
    _, post = webhook
    seed_continuation(db, 511, blockers=[{"code": "session_identity"}])
    evolution_alerts_once(db, now=NOW, post=post)
    with db.session() as session:
        row = session.get(EvolutionAlert, alert_id(ALERT_OPERATOR_BLOCKED, 511))
        row.payload_json = {
            k: v for k, v in row.payload_json.items() if not k.startswith("delivery_")
        }
    assert list_alerts(db)[0]["delivery_verified"] is False
    later = NOW + timedelta(days=1)
    touch_continuation(db, 511, later)
    evolution_alerts_once(db, now=later, post=post)
    assert list_alerts(db)[0]["delivery_verified"] is True


@pytest.mark.parametrize("preview_revision,resolved", [(1, True), (0, False)])
def test_fresh_preview_refreshes_alerts_without_rewriting_research_eligibility(
    db, webhook, preview_revision, resolved
):
    from hypertrade.arc.evolution_models import EvolutionControl

    _, post = webhook
    seed_continuation(db, 511, blockers=[{"code": "session_identity"}])
    evolution_alerts_once(db, now=NOW, post=post)
    with db.session() as session:
        original = dict(session.get(EvolutionContinuation, "src_511").payload_json)
        session.add(EvolutionControl(id="global", revision=1, config_json={"enabled": True}))
        session.add(
            EvolutionCycle(
                id="preview_fresh",
                status="preview_complete",
                created_at=NOW,
                payload_json={
                    "revision": preview_revision,
                    "preview": True,
                    "diagnostics": [
                        {
                            "strategy_id": 511,
                            "continuation": {
                                "observed_at": (NOW + timedelta(minutes=1)).isoformat(),
                                "blockers": [
                                    {"code": "completed_utc_window", "resolution": "time"}
                                ],
                                "next_eligible_at": "2026-10-03T00:00:00+00:00",
                            },
                        }
                    ],
                },
            )
        )
    evolution_alerts_once(db, now=NOW + timedelta(minutes=2), post=post)
    assert (list_alerts(db)[0]["status"] == "resolved") == resolved
    with db.session() as session:
        assert session.get(EvolutionContinuation, "src_511").payload_json == original


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
    assert "会话身份" in sent[0]["payload"]["content"]["text"]

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


def test_reappearing_stall_starts_a_fresh_episode(db, webhook) -> None:
    """Horizons are anchored to the loop clock, not the row insert clock.

    A resolved condition that reappears must serve a fresh 72h tracking window
    instead of inheriting the old episode's age (which would page instantly).
    """
    _, post = webhook
    seed_continuation(db, 342, blockers=[{"code": "evidence_recheck"}], next_eligible_at=None)
    evolution_alerts_once(db, now=NOW, post=post)

    with db.session() as session:  # condition clears -> resolved
        session.delete(session.get(EvolutionContinuation, "src_342"))
    evolution_alerts_once(db, now=NOW + timedelta(hours=1), post=post)
    assert list_alerts(db)[0]["status"] == "resolved"

    later = NOW + timedelta(hours=100)
    seed_continuation(
        db,
        342,
        blockers=[{"code": "evidence_recheck"}],
        next_eligible_at=None,
        observed_at=later,
    )
    again = evolution_alerts_once(db, now=later, post=post)
    assert again["tracking"] == 1 and again["opened"] == 0

    touch_continuation(db, 342, later + timedelta(hours=73))
    opened = evolution_alerts_once(db, now=later + timedelta(hours=73), post=post)
    assert opened["opened"] == 1 and opened["delivered"] == 1
    assert "已持续约 73 小时" in list_alerts(db)[0]["message"]


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
