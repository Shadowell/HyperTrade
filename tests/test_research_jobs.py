from __future__ import annotations

import pytest
from hypertrade.db import Database
from hypertrade.research.schemas import ResearchJobCreate, ResearchMandateCreate
from hypertrade.research.service import ResearchProgramService


def _service_with_mandate() -> tuple[ResearchProgramService, str]:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = ResearchProgramService(db)
    mandate = service.create_mandate(
        ResearchMandateCreate(
            name="BTC trend program",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
        )
    )
    return service, str(mandate["id"])


def test_research_job_is_idempotent_and_auditable() -> None:
    service, mandate_id = _service_with_mandate()
    payload = ResearchJobCreate(
        prompt="evaluate a bounded BTC trend hypothesis",
        idempotency_key="research-job-key-0001",
        source_run_id="run_001",
    )

    queued = service.queue_job(mandate_id, payload)
    replayed = service.queue_job(mandate_id, payload)

    assert queued["status"] == "queued"
    assert queued["strategy_spec"]["strategy_category"] == "TREND"
    assert queued["transitions"][0]["trace_ref"] == "research.job.transition"
    assert replayed["id"] == queued["id"]
    assert replayed["idempotency_replayed"] is True
    assert service.cancel_job(str(queued["id"]))["status"] == "canceled"
    with pytest.raises(ValueError, match="cannot transition"):
        service.cancel_job(str(queued["id"]))


def test_paused_mandate_cannot_queue_research_job() -> None:
    service, mandate_id = _service_with_mandate()
    service.pause_mandate(mandate_id)

    with pytest.raises(ValueError, match="not active"):
        service.queue_job(
            mandate_id,
            ResearchJobCreate(
                prompt="evaluate a bounded BTC trend hypothesis",
                idempotency_key="research-job-key-0002",
            ),
        )
