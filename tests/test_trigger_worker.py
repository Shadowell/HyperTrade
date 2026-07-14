from __future__ import annotations

from datetime import timedelta

from hypertrade.agent.tasks import AgentTaskService
from hypertrade.config import Settings
from hypertrade.db import Database, ResearchTrigger, utc_now
from hypertrade.research.schemas import ResearchMandateCreate
from hypertrade.research.service import ResearchProgramService
from hypertrade.research.triggers import ResearchTriggerCreate, ResearchTriggerService
from hypertrade.worker import research_trigger_worker_once


def _scheduled(tmp_path) -> tuple[Database, Settings, str]:
    db = Database(f"sqlite:///{tmp_path / 'triggers.db'}")
    db.create_all()
    mandate = ResearchProgramService(db).create_mandate(
        ResearchMandateCreate(
            name="Scheduled trigger mandate",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
        )
    )
    settings = Settings(
        RESEARCH_TRIGGERS_ENABLED=True,
        RESEARCH_TRIGGER_LEASE_SECONDS=60,
    )
    trigger = ResearchTriggerService(db, settings=settings).create(
        ResearchTriggerCreate(
            name="Hourly evidence refresh",
            trigger_type="schedule",
            mandate_id=str(mandate["id"]),
            objective_template="Refresh evidence for the bounded research mandate.",
            enabled=True,
            cooldown_seconds=60,
        ),
        actor="test",
    )
    with db.session() as session:
        row = session.get(ResearchTrigger, str(trigger["id"]))
        assert row is not None
        row.next_run_at = utc_now() - timedelta(seconds=1)
    return db, settings, str(trigger["id"])


def test_trigger_worker_respects_disabled_feature(tmp_path) -> None:
    db, _, trigger_id = _scheduled(tmp_path)

    result = research_trigger_worker_once(
        db,
        settings=Settings(RESEARCH_TRIGGERS_ENABLED=False),
        worker_id="disabled",
    )

    assert result == {"status": "disabled", "trigger_id": None}
    assert AgentTaskService(db).list_tasks(limit=10) == []
    assert ResearchTriggerService(db).list_fires(trigger_id=trigger_id) == []


def test_two_workers_and_restart_create_one_due_task(tmp_path) -> None:
    db, settings, trigger_id = _scheduled(tmp_path)

    first = research_trigger_worker_once(db, settings=settings, worker_id="worker-a")
    second = research_trigger_worker_once(db, settings=settings, worker_id="worker-b")
    restarted = research_trigger_worker_once(db, settings=settings, worker_id="worker-a")

    assert first["status"] == "created"
    assert first["trigger_id"] == trigger_id
    assert second["status"] == "idle"
    assert restarted["status"] == "idle"
    assert len(AgentTaskService(db).list_tasks(limit=10)) == 1
    fires = ResearchTriggerService(db, settings=settings).list_fires(trigger_id=trigger_id)
    assert len(fires) == 1
    trigger = ResearchTriggerService(db, settings=settings).get(trigger_id)
    assert trigger["next_run_at"] is not None
    assert trigger["lease_owner"] is None


def test_claim_lease_is_exclusive_and_wrong_owner_cannot_run(tmp_path) -> None:
    db, settings, trigger_id = _scheduled(tmp_path)
    service = ResearchTriggerService(db, settings=settings)

    claimed = service.claim_due("worker-a")

    assert claimed is not None and claimed["id"] == trigger_id
    assert service.claim_due("worker-b") is None
    try:
        service.run_claimed(trigger_id, "worker-b")
    except PermissionError as exc:
        assert "lease owner" in str(exc)
    else:
        raise AssertionError("wrong lease owner should fail closed")
