from __future__ import annotations

from typing import Any

from hypertrade.bitpro.paper_monitor import BitProPaperMonitorService
from hypertrade.db import BitProPaperMonitorSnapshot, Database


class SnapshotReplayAdapter:
    def __init__(self, *, equity: str, pnl: str, drawdown: str, errors: int) -> None:
        self.equity = equity
        self.pnl = pnl
        self.drawdown = drawdown
        self.errors = errors

    def paper_dashboard(self, *, strategy_id: int | None = None) -> dict[str, Any]:
        return {
            "status": "ok",
            "contract_version": "bitpro-mcp-v1",
            "dashboard": {
                "system": {
                    "strategy_id": strategy_id,
                    "strategy": "SOL paper monitor",
                    "state": "running",
                    "mode": "paper",
                }
            },
            "monitor_summary": {
                "mode": "read_only",
                "current_dashboard": {
                    "strategy_id": strategy_id,
                    "strategy_name": "SOL paper monitor",
                    "state": "running",
                    "mode": "paper",
                    "equity": self.equity,
                    "total_pnl_pct": self.pnl,
                    "max_drawdown_pct": self.drawdown,
                },
                "running_inventory": {
                    "listed_count": 1,
                    "reported_total": 1,
                    "is_truncated": False,
                },
                "alerts": [],
                "data_gaps": [],
                "recommended_actions": [],
            },
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {"tool": "paper_dashboard", "status": "success", "parameters": {}},
            ],
        }

    def paper_events(self, *, strategy_id: int | None = None, limit: int = 50) -> dict[str, Any]:
        return {
            "status": "ok",
            "strategy_id": strategy_id,
            "events": [],
            "event_summary": {
                "count": self.errors,
                "sample_count": 0,
                "error_count": self.errors,
                "latest_event_at": "2026-06-23T06:00:05+00:00",
            },
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {
                    "tool": "paper_events",
                    "status": "success",
                    "parameters": {"strategy_id": strategy_id, "limit": limit},
                },
            ],
        }

    def paper_equity_curve(
        self,
        *,
        strategy_id: int | None = None,
        sample_limit: int = 50,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "strategy_id": strategy_id,
            "equity_curve": [
                {
                    "timestamp": "2026-06-23T06:00:05+00:00",
                    "equity": self.equity,
                    "drawdown_pct": self.drawdown,
                }
            ],
            "equity_summary": {
                "count": 1,
                "sample_count": 1,
                "latest_at": "2026-06-23T06:00:05+00:00",
                "latest_equity": self.equity,
                "latest_drawdown_pct": self.drawdown,
                "max_drawdown_pct": self.drawdown,
            },
            "tool_calls": [
                {"tool": "bitpro_capabilities", "status": "success", "parameters": {}},
                {"tool": "bitpro_health", "status": "success", "parameters": {}},
                {"tool": "paper_equity_curve", "status": "success", "parameters": {}},
            ],
        }


def test_bitpro_paper_monitor_snapshot_persists_baseline_and_drift() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()

    first = BitProPaperMonitorService(
        db,
        bitpro_adapter=SnapshotReplayAdapter(equity="104", pnl="4.0", drawdown="2.0", errors=0),
    ).capture(strategy_id=105)
    second = BitProPaperMonitorService(
        db,
        bitpro_adapter=SnapshotReplayAdapter(equity="101.5", pnl="1.5", drawdown="5.2", errors=2),
    ).capture(strategy_id=105)

    assert first["drift"]["mode"] == "baseline"
    assert first["previous_snapshot_id"] is None
    assert first["metrics"]["latest_equity"] == "104"

    assert second["previous_snapshot_id"] == first["snapshot_id"]
    assert second["drift"]["mode"] == "compared"
    assert second["drift"]["equity_delta"] == "-2.5"
    assert second["drift"]["total_pnl_delta_pct"] == "-2.5"
    assert second["drift"]["max_drawdown_delta_pct"] == "3.2"
    assert second["drift"]["error_count_delta"] == 2
    assert {alert["code"] for alert in second["drift"]["alerts"]} == {
        "equity_drop",
        "pnl_drop",
        "drawdown_expanded",
        "new_event_errors",
    }
    assert [call["tool"] for call in second["tool_calls"]] == [
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

    with db.session() as session:
        rows = session.query(BitProPaperMonitorSnapshot).order_by(
            BitProPaperMonitorSnapshot.created_at
        ).all()

    assert [row.id for row in rows] == [first["snapshot_id"], second["snapshot_id"]]
    assert rows[1].previous_snapshot_id == rows[0].id
    assert rows[1].strategy_id == 105
    assert rows[1].metrics_json["latest_equity"] == "101.5"
    assert rows[1].drift_json["max_drawdown_delta_pct"] == "3.2"
