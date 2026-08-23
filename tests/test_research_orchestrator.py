from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.research.experiment_ledger import ExperimentLedgerService
from hypertrade.research.orchestrator import ResearchOrchestrator
from hypertrade.research.robustness import RobustnessValidationService
from hypertrade.research.schemas import ResearchBudget, ResearchJobCreate, ResearchMandateCreate
from hypertrade.research.service import ResearchProgramService


class FixtureBitProAdapter:
    def __init__(
        self,
        *,
        missing_locked_metric: bool = False,
        unhealthy: bool = False,
        missing_robustness_result: bool = False,
        failed_backtest: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.missing_locked_metric = missing_locked_metric
        self.unhealthy = unhealthy
        self.missing_robustness_result = missing_robustness_result
        self.failed_backtest = failed_backtest
        self.result_number = 0

    def capabilities(self) -> dict[str, Any]:
        self.calls.append("bitpro_capabilities")
        return {
            "contract_version": "bitpro-mcp-v1",
            "tool_groups": {
                "research_backtest_paper_mutation": [
                    "strategy_validate_code",
                    "strategy_create",
                    "backtest_start_job",
                ]
            },
        }

    def health(self) -> dict[str, Any]:
        self.calls.append("bitpro_health")
        return {"health": {"status": "down" if self.unhealthy else "healthy"}, "tool_calls": []}

    def market_klines(self, **_: Any) -> dict[str, Any]:
        self.calls.append("market_klines")
        start = datetime(2026, 1, 1, tzinfo=UTC)
        return {
            "candles": [
                {"timestamp": (start + timedelta(hours=index)).isoformat()} for index in range(500)
            ],
            "tool_calls": [],
        }

    def strategy_validate_code(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("strategy_validate_code")
        assert (
            "from app.core.execution.base_strategy import BaseStrategy" in kwargs["script_content"]
        )
        assert "async def on_bar(self, bar):" in kwargs["script_content"]
        assert "def __init__" not in kwargs["script_content"]
        assert "get_recent_bars" not in kwargs["script_content"]
        assert kwargs["symbols"] == ["BTC"]
        assert kwargs["market_type"] == "swap"
        assert kwargs["timeframe"] == "1H"
        assert kwargs["smoke"] is True
        return {"validation": {"valid": True}, "tool_calls": []}

    def strategy_create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("strategy_create")
        assert kwargs["config"]["strategy_source"] == "db_script"
        assert kwargs["idempotency_key"]
        return {"strategy": {"id": 42}, "tool_calls": []}

    def strategy_update(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("strategy_update")
        assert kwargs["idempotency_key"]
        return {"strategy": {"id": 42}, "tool_calls": []}

    def backtest_start_job(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("backtest_start_job")
        self.result_number += 1
        if self.failed_backtest:
            return {
                "job": {"job_id": "bp_job_failed", "status": "failed"},
                "tool_calls": [],
            }
        metrics: dict[str, str] = {
            "total_return_pct": str(self.result_number),
            "max_drawdown_pct": "8.5",
            "trade_count": "30",
        }
        if self.missing_locked_metric and kwargs["start_date"] == "2026-01-17":
            metrics.pop("trade_count")
        if self.missing_robustness_result and self.result_number == 10:
            return {"job": {"job_id": "bp_job_10"}, "tool_calls": []}
        return {
            "job": {"job_id": f"bp_job_{self.result_number}"},
            "backtest_result": {"id": self.result_number, "metrics": metrics},
            "tool_calls": [],
        }

    def backtest_get_result(self, **_: Any) -> dict[str, Any]:
        raise AssertionError("worker must use completed backtest result returned by BitPro")


def _queued_job() -> tuple[Database, str]:
    db = Database("sqlite:///:memory:")
    db.create_all()
    program = ResearchProgramService(db)
    mandate = program.create_mandate(
        ResearchMandateCreate(
            name="BTC bounded matrix",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
        )
    )
    job = program.queue_job(
        str(mandate["id"]),
        ResearchJobCreate(
            prompt="test a bounded BTC trend hypothesis",
            idempotency_key="sprint82-job-key-0001",
        ),
    )
    return db, str(job["id"])


def test_orchestrator_persists_bitpro_matrix_evidence_without_paper_action() -> None:
    db, job_id = _queued_job()
    adapter = FixtureBitProAdapter()

    report = ResearchOrchestrator(db, bitpro_adapter=adapter).run(job_id)

    assert report["job"]["status"] == "evidence_recorded"
    assert len(report["evidence"]) == 3
    assert {row["status"] for row in report["evidence"]} == {"evidence_recorded"}
    assert (
        report["outcome"]["paper_promotion"]
        == "requestable_via_paper_promotion_request_pending_operator_approval"
    )
    assert "paper_configure" not in adapter.calls
    assert "paper_start" not in adapter.calls
    assert adapter.calls.count("backtest_start_job") == 13
    assert report["job"]["external_refs"]["sprint_82"]["bitpro_strategy_id"] == "42"
    assert report["job"]["external_refs"]["sprint_82"]["robustness_status"] == "validated"
    ledger = report["job"]["external_refs"]["experiment_ledger"]
    assert len(ledger["fingerprint"]) == 64
    execution = ExperimentLedgerService(db).executions(ledger["fingerprint"])[0]
    assert execution["status"] == "completed"
    assert execution["usage"] == {"backtests": 13, "tool_calls": 0}
    assert len(execution["artifacts"]["items"]) == 16
    assert len(execution["evidence"]) == 3


def test_orchestrator_reuses_completed_fingerprint_before_bitpro_writes() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    program = ResearchProgramService(db)
    mandate = program.create_mandate(
        ResearchMandateCreate(
            name="BTC deduplicated matrix",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
        )
    )
    first = program.queue_job(
        str(mandate["id"]),
        ResearchJobCreate(
            prompt="test a bounded BTC trend hypothesis",
            idempotency_key="sprint99-first-job-key",
        ),
    )
    second = program.queue_job(
        str(mandate["id"]),
        ResearchJobCreate(
            prompt="  test   a bounded BTC trend hypothesis ",
            idempotency_key="sprint99-second-job-key",
        ),
    )
    adapter = FixtureBitProAdapter()

    first_report = ResearchOrchestrator(db, bitpro_adapter=adapter).run(str(first["id"]))
    second_report = ResearchOrchestrator(db, bitpro_adapter=adapter).run(str(second["id"]))

    first_ledger = first_report["job"]["external_refs"]["experiment_ledger"]
    second_ledger = second_report["job"]["external_refs"]["experiment_ledger"]
    assert second_report["job"]["status"] == "evidence_recorded"
    assert second_ledger["reused"] is True
    assert second_ledger["execution_id"] == first_ledger["execution_id"]
    assert second_ledger["fingerprint"] == first_ledger["fingerprint"]
    assert adapter.calls.count("strategy_create") == 1
    assert adapter.calls.count("backtest_start_job") == 13


def test_orchestrator_rejects_missing_locked_metric_without_paper_action() -> None:
    db, job_id = _queued_job()
    adapter = FixtureBitProAdapter(missing_locked_metric=True)

    report = ResearchOrchestrator(db, bitpro_adapter=adapter).run(job_id)

    assert report["job"]["status"] == "rejected"
    assert any(
        "missing_metrics" in reason
        for row in report["evidence"]
        for reason in row["rejection_reasons"]
    )
    assert "paper_configure" not in adapter.calls


def test_orchestrator_reports_terminal_bitpro_backtest_failure() -> None:
    db, job_id = _queued_job()
    adapter = FixtureBitProAdapter(failed_backtest=True)

    report = ResearchOrchestrator(db, bitpro_adapter=adapter).run(job_id)

    assert report["job"]["status"] == "rejected"
    assert report["job"]["transitions"][-1]["reason"] == (
        "bitpro_backtest_failed:baseline:in_sample"
    )


def test_orchestrator_marks_partial_robustness_result_needs_data() -> None:
    db, job_id = _queued_job()
    adapter = FixtureBitProAdapter(missing_robustness_result=True)

    report = ResearchOrchestrator(db, bitpro_adapter=adapter).run(job_id)

    assert report["job"]["status"] == "rejected"
    refs = report["job"]["external_refs"]["sprint_82"]
    assert refs["robustness_status"] == "needs_data"
    validation = RobustnessValidationService(db).get(refs["robustness_validation_id"])
    assert validation["gates"]["walk_forward"]["outcome"] == "unknown"


def test_orchestrator_stops_before_strategy_write_when_bitpro_is_unhealthy() -> None:
    db, job_id = _queued_job()
    adapter = FixtureBitProAdapter(unhealthy=True)

    report = ResearchOrchestrator(db, bitpro_adapter=adapter).run(job_id)

    assert report["job"]["status"] == "failed"
    assert adapter.calls == ["bitpro_capabilities", "bitpro_health"]


def test_orchestrator_pre_reserves_robustness_budget_before_strategy_write() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    program = ResearchProgramService(db)
    mandate = program.create_mandate(
        ResearchMandateCreate(
            name="legacy nine backtest budget",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
            budget=ResearchBudget(max_total_backtests_per_day=9),
        )
    )
    job = program.queue_job(
        str(mandate["id"]),
        ResearchJobCreate(
            prompt="test bounded budget rejection",
            idempotency_key="sprint100-budget-job-key",
        ),
    )
    adapter = FixtureBitProAdapter()

    report = ResearchOrchestrator(db, bitpro_adapter=adapter).run(str(job["id"]))

    assert report["job"]["status"] == "rejected"
    assert "strategy_validate_code" not in adapter.calls
    assert "strategy_create" not in adapter.calls
    assert "backtest_start_job" not in adapter.calls


def test_research_job_api_runs_worker_and_exposes_read_only_report() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    adapter = FixtureBitProAdapter()
    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                SESSION_SECRET="sprint82-api-test",
            ),
            db=db,
            bitpro_adapter=adapter,
        )
    )
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code
        == 200
    )
    mandate = client.post(
        "/api/research/mandates",
        json={
            "name": "BTC API matrix",
            "symbols": ["BTC"],
            "timeframes": ["1H"],
            "strategy_categories": ["TREND"],
        },
    ).json()
    job = client.post(
        f"/api/research/mandates/{mandate['id']}/jobs",
        json={
            "prompt": "test a bounded BTC trend hypothesis",
            "idempotency_key": "sprint82-api-job-key-0001",
        },
    ).json()

    run = client.post(f"/api/research/jobs/{job['id']}/run")
    report = client.get(f"/api/research/jobs/{job['id']}/report")

    assert run.status_code == 200
    assert report.status_code == 200
    assert report.json()["job"]["status"] == "evidence_recorded"
