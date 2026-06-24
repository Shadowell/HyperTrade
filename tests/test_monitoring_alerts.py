from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import Any

from fastapi.testclient import TestClient
from hypertrade.cli import handle_slash_command
from hypertrade.config import Settings
from hypertrade.db import Database, MonitorAlertEvent, MonitorDefinition, MonitorRun, utc_now
from hypertrade.main import create_app
from hypertrade.monitoring import MonitorService
from sqlalchemy import select


class ReplayMonitorAdapter:
    def __init__(
        self,
        *,
        equity: str | None,
        pnl: str | None,
        drawdown: str | None,
        errors: int,
        health_status: str = "ok",
    ) -> None:
        self.equity = equity
        self.pnl = pnl
        self.drawdown = drawdown
        self.errors = errors
        self.health_status = health_status

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "health": {"status": self.health_status},
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success"},
                {"tool": "bitpro_health", "status": "success"},
            ],
        }

    def paper_dashboard(self, *, strategy_id: int | None = None) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "dashboard": {"system": {"strategy_id": strategy_id, "strategy": "monitor"}},
            "monitor_summary": {
                "mode": "read_only",
                "current_dashboard": {
                    "strategy_id": strategy_id,
                    "strategy_name": "monitor",
                    "state": "running",
                    "mode": "paper",
                    "equity": self.equity,
                    "total_pnl_pct": self.pnl,
                    "max_drawdown_pct": self.drawdown,
                },
                "alerts": [],
                "data_gaps": [],
                "recommended_actions": ["Inspect BitPro paper evidence."],
            },
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success"},
                {"tool": "bitpro_health", "status": "success"},
                {"tool": "paper_dashboard", "status": "success"},
            ],
        }

    def paper_events(self, *, strategy_id: int | None = None, limit: int = 50) -> dict[str, Any]:
        return {
            "status": "ok",
            "event_summary": {
                "count": self.errors,
                "error_count": self.errors,
                "latest_event_at": "2026-06-23T06:00:00+00:00",
            },
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success"},
                {"tool": "bitpro_health", "status": "success"},
                {"tool": "paper_events", "status": "success", "parameters": {"limit": limit}},
            ],
        }

    def paper_equity_curve(
        self,
        *,
        strategy_id: int | None = None,
        sample_limit: int = 50,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "count": 1 if self.equity is not None else 0,
            "sample_count": 1 if self.equity is not None else 0,
            "latest_at": "2026-06-23T06:00:00+00:00" if self.equity is not None else None,
            "latest_equity": self.equity,
            "latest_drawdown_pct": self.drawdown,
            "max_drawdown_pct": self.drawdown,
        }
        return {
            "status": "ok",
            "equity_summary": summary,
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success"},
                {"tool": "bitpro_health", "status": "success"},
                {
                    "tool": "paper_equity_curve",
                    "status": "success",
                    "parameters": {"sample_limit": sample_limit},
                },
            ],
        }


def test_monitor_service_persists_runs_and_alert_events_without_write_tools() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = MonitorService(db, bitpro_adapter=ReplayMonitorAdapter(
        equity="104",
        pnl="4",
        drawdown="1.5",
        errors=0,
    ))
    monitor = service.upsert_monitor(
        monitor_id="mon_test_paper",
        name="BitPro paper strategy 105",
        monitor_type="bitpro_paper",
        scope={"strategy_id": 105},
        thresholds={
            "max_drawdown_pct": "3",
            "error_count": 1,
            "equity_drop": "1",
            "pnl_drop_pct": "1",
        },
    )

    baseline = service.run_monitor(monitor["id"])
    degraded = MonitorService(db, bitpro_adapter=ReplayMonitorAdapter(
        equity="100",
        pnl="1.5",
        drawdown="4.2",
        errors=2,
    )).run_monitor(monitor["id"])

    assert baseline["status"] == "completed"
    assert baseline["drift"]["mode"] == "baseline"
    assert degraded["status"] == "completed"
    assert degraded["previous_run_id"] == baseline["run_id"]
    assert degraded["metric_snapshot"]["latest_equity"] == "100"
    assert degraded["drift"]["equity_delta"] == "-4"
    assert {alert["code"] for alert in degraded["alerts"]} == {
        "drawdown_threshold_breached",
        "error_count_threshold_breached",
        "equity_drop_threshold_breached",
        "pnl_drop_threshold_breached",
    }
    assert all(alert["source_id"] == degraded["run_id"] for alert in degraded["alerts"])
    assert all(alert["threshold"] for alert in degraded["alerts"])
    tool_names = [call["tool"] for call in degraded["source_tools"]]
    assert tool_names == [
        "bitpro_capabilities",
        "bitpro_health",
        "paper_dashboard",
        "bitpro_capabilities",
        "bitpro_health",
        "paper_events",
        "bitpro_capabilities",
        "bitpro_health",
        "paper_equity_curve",
    ]
    assert not any(
        name in {"paper_pause", "paper_resume", "paper_start", "paper_stop"}
        for name in tool_names
    )

    with db.session() as session:
        definitions = session.scalars(select(MonitorDefinition)).all()
        runs = session.scalars(select(MonitorRun)).all()
        alerts = session.scalars(select(MonitorAlertEvent)).all()

    assert "mon_test_paper" in {definition.id for definition in definitions}
    assert [run.id for run in runs] == [baseline["run_id"], degraded["run_id"]]
    assert {alert.code for alert in alerts} == {alert["code"] for alert in degraded["alerts"]}


def test_monitor_service_reports_missing_data_as_alert_and_gap() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = MonitorService(
        db,
        bitpro_adapter=ReplayMonitorAdapter(equity=None, pnl=None, drawdown=None, errors=0),
    )
    monitor = service.upsert_monitor(
        monitor_id="mon_missing_data",
        name="BitPro missing data",
        monitor_type="bitpro_paper",
        scope={"strategy_id": 105},
        thresholds={"missing_data": True},
    )

    result = service.run_monitor(monitor["id"])

    assert result["status"] == "completed"
    assert "missing latest_equity" in result["data_gaps"]
    assert "missing max_drawdown_pct" in result["data_gaps"]
    assert {alert["code"] for alert in result["alerts"]} == {"monitor_data_gap"}


def test_monitor_api_lists_runs_and_alerts() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(DEEPSEEK_API_KEY=""),
        db=db,
        bitpro_adapter=ReplayMonitorAdapter(
            equity="100",
            pnl="-1",
            drawdown="5",
            errors=3,
        ),
    )
    client = TestClient(app)

    monitors = client.get("/api/monitors").json()["items"]
    assert {monitor["id"] for monitor in monitors} >= {
        "mon_bitpro_paper_all",
        "mon_strategy_library_freshness",
        "mon_connector_health",
    }

    run_response = client.post("/api/monitors/mon_bitpro_paper_all/run")

    assert run_response.status_code == 200
    run_body = run_response.json()
    assert run_body["monitor_id"] == "mon_bitpro_paper_all"
    assert run_body["status"] == "completed"
    assert run_body["source_tools"]
    alerts = client.get("/api/alerts").json()["items"]
    assert alerts
    assert alerts[0]["run_id"] == run_body["run_id"]
    assert "paper_" not in alerts[0]["code"] or alerts[0]["level"] in {"warning", "critical"}


def test_default_monitors_use_conservative_interval_schedules() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = MonitorService(
        db,
        bitpro_adapter=ReplayMonitorAdapter(equity="100", pnl="0", drawdown="0", errors=0),
    )

    schedules = {monitor["id"]: monitor["schedule"] for monitor in service.list_monitors()}

    assert schedules["mon_bitpro_paper_all"] == {
        "mode": "interval",
        "interval_seconds": 300,
    }
    assert schedules["mon_connector_health"] == {
        "mode": "interval",
        "interval_seconds": 600,
    }
    assert schedules["mon_strategy_library_freshness"] == {
        "mode": "interval",
        "interval_seconds": 3600,
    }


def test_monitor_service_runs_due_monitors_and_skips_manual_disabled_or_not_due() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = MonitorService(
        db,
        bitpro_adapter=ReplayMonitorAdapter(equity="100", pnl="0", drawdown="0", errors=0),
    )
    service.upsert_monitor(
        monitor_id="mon_manual_test",
        name="Manual only",
        monitor_type="connector_health",
        scope={"connector": "bitpro_mcp"},
        thresholds={"missing_data": True},
        schedule={"mode": "manual"},
    )
    service.upsert_monitor(
        monitor_id="mon_disabled_test",
        name="Disabled interval",
        monitor_type="connector_health",
        scope={"connector": "bitpro_mcp"},
        thresholds={"missing_data": True},
        schedule={"mode": "interval", "interval_seconds": 60},
        enabled=False,
    )
    now = utc_now()

    first = service.run_due_monitors(now=now)

    assert {run["monitor_id"] for run in first["ran"]} == {
        "mon_bitpro_paper_all",
        "mon_connector_health",
        "mon_strategy_library_freshness",
    }
    first_skips = {skip["monitor_id"]: skip["reason"] for skip in first["skipped"]}
    assert first_skips["mon_manual_test"] == "manual_schedule"
    assert first_skips["mon_disabled_test"] == "disabled"

    second = service.run_due_monitors(now=now + timedelta(seconds=60))

    assert second["ran"] == []
    second_skips = {skip["monitor_id"]: skip["reason"] for skip in second["skipped"]}
    assert second_skips["mon_bitpro_paper_all"] == "not_due"
    assert second_skips["mon_connector_health"] == "not_due"
    assert second_skips["mon_strategy_library_freshness"] == "not_due"
    assert second_skips["mon_manual_test"] == "manual_schedule"
    assert second_skips["mon_disabled_test"] == "disabled"

    third = service.run_due_monitors(now=now + timedelta(seconds=301))

    assert {run["monitor_id"] for run in third["ran"]} == {"mon_bitpro_paper_all"}


class FakeMonitorClient:
    def list_monitors(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "mon_bitpro_paper_all",
                "name": "BitPro paper monitor",
                "monitor_type": "bitpro_paper",
                "enabled": True,
                "last_status": "completed",
                "last_run_id": "mrun_recent",
            }
        ]

    def run_monitor(self, monitor_id: str) -> dict[str, Any]:
        return {
            "run_id": "mrun_recent",
            "monitor_id": monitor_id,
            "status": "completed",
            "metric_snapshot": {"latest_equity": "100", "max_drawdown_pct": "5"},
            "alerts": [
                {
                    "level": "warning",
                    "code": "drawdown_threshold_breached",
                    "message": "max_drawdown_pct 5 breached threshold 3",
                }
            ],
            "data_gaps": [],
            "recommended_actions": ["Inspect BitPro paper evidence."],
        }

    def list_alerts(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "alrt_recent",
                "monitor_id": "mon_bitpro_paper_all",
                "run_id": "mrun_recent",
                "level": "warning",
                "code": "drawdown_threshold_breached",
                "message": "max_drawdown_pct 5 breached threshold 3",
                "created_at": "2026-06-23T06:00:00+00:00",
            }
        ]


def test_cli_renders_monitor_commands() -> None:
    client = FakeMonitorClient()
    output = StringIO()

    handle_slash_command("/monitors", client=client, output=output)  # type: ignore[arg-type]
    handle_slash_command("/monitor run mon_bitpro_paper_all", client=client, output=output)  # type: ignore[arg-type]
    handle_slash_command("/alerts", client=client, output=output)  # type: ignore[arg-type]

    rendered = output.getvalue()
    assert "Monitors:" in rendered
    assert "mon_bitpro_paper_all" in rendered
    assert "Monitor run: mrun_recent" in rendered
    assert "drawdown_threshold_breached" in rendered
    assert "Recent alerts:" in rendered
