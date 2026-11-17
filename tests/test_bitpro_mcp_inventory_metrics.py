from __future__ import annotations

from typing import Any

import httpx
import pytest
from hypertrade.bitpro.mcp import (
    BitProMcpClient,
    BitProToolAdapter,
    _paper_monitor_summary,
)
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.monitoring import MonitorService


def _build_adapter(
    strategy_items: list[dict[str, Any]],
    *,
    dashboard_payload: dict[str, Any] | None = None,
) -> BitProToolAdapter:
    dashboard_data = (
        dashboard_payload
        if dashboard_payload is not None
        else {
            "system": {
                "state": "running",
                "mode": "paper",
                "strategy_id": 105,
                "strategy": "[合约][1H][CTA] SOL · 基准版 · 100U",
                "uptime": "5D",
            },
            "equity": {"current": 102.4},
            "performance": {"total_pnl_pct": 2.4, "sharpe_ratio": 1.1, "max_drawdown": 3.2},
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/system/health":
            return httpx.Response(200, json={"success": True, "data": {"status": "healthy"}})
        if request.url.path == "/api/v2/live/dashboard":
            return httpx.Response(200, json={"success": True, "data": dashboard_data})
        if request.url.path == "/api/v2/strategies":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "items": strategy_items,
                        "total": len(strategy_items),
                    },
                },
            )
        if request.url.path == "/api/v2/live/events":
            return httpx.Response(200, json={"success": True, "data": {"items": [], "total": 0}})
        if request.url.path == "/api/v2/live/equity_curve":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "curve": [
                            {
                                "timestamp": "2026-11-18T00:00:00Z",
                                "equity": 102.4,
                                "drawdown_pct": 3.2,
                            }
                        ]
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return BitProToolAdapter(
        BitProMcpClient(
            settings=Settings(_env_file=None, BITPRO_MCP_API_BASE="http://bitpro.local/api/v2"),
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
    )


@pytest.mark.parametrize(
    "metric_fields",
    [
        {"total_pnl_pct": 1.25},
        {"return_pct": 2.5},
        {"cumulative_return_pct": 3.1},
        {"pnl_pct": -0.4},
        {"paper_metrics": {"total_pnl_pct": 4.2}},
        {"max_drawdown": 5.0},
        {"max_drawdown_pct": 6.1},
        {"paper_metrics": {"max_drawdown_pct": 7.3}},
        {"total_pnl_pct": 0.0, "max_drawdown_pct": None},
    ],
)
def test_paper_dashboard_accepts_all_inventory_metric_field_variants(
    metric_fields: dict[str, Any],
) -> None:
    adapter = _build_adapter(
        [
            {
                "id": 105,
                "name": "[合约][1H][CTA] SOL · 基准版 · 100U",
                "status": "running",
                "symbols": ["SOL/USDT:USDT"],
                **metric_fields,
            }
        ]
    )

    result = adapter.paper_dashboard()
    monitor = result["monitor_summary"]

    assert "missing_strategy_metrics" not in {alert["code"] for alert in monitor["alerts"]}
    assert monitor["data_gaps"] == []


@pytest.mark.parametrize(
    "item",
    [
        {"id": 1, "total_pnl_pct": 1.25},
        {"id": 1, "return_pct": 2.5},
        {"id": 1, "cumulative_return_pct": 3.1},
        {"id": 1, "pnl_pct": -0.4},
        {"id": 1, "paper_metrics": {"total_pnl_pct": 4.2}},
        {"id": 1, "max_drawdown": 5.0},
        {"id": 1, "max_drawdown_pct": 6.1},
        {"id": 1, "paper_metrics": {"max_drawdown_pct": 7.3}},
    ],
)
def test_paper_monitor_summary_recognizes_raw_inventory_metric_aliases(
    item: dict[str, Any],
) -> None:
    summary = _paper_monitor_summary(
        {
            "system": {"strategy_id": 1, "state": "running", "mode": "paper"},
            "equity": {"current": 100},
            "performance": {"total_pnl_pct": 1.0, "max_drawdown_pct": 2.0},
        },
        running_strategies={"items": [item], "total": 1, "source_tool": "strategy_search"},
        strategy_id_filter=None,
    )

    assert "missing_strategy_metrics" not in {alert["code"] for alert in summary["alerts"]}
    assert summary["data_gaps"] == []


def test_lightweight_inventory_with_healthy_dashboard_does_not_trigger_monitor_data_gap() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    adapter = _build_adapter(
        [
            {
                "id": 105,
                "name": "[合约][1H][CTA] SOL · 基准版 · 100U",
                "status": "running",
                "symbols": ["SOL/USDT:USDT"],
            }
        ]
    )

    dashboard = adapter.paper_dashboard()
    monitor_summary = dashboard["monitor_summary"]
    assert any(
        alert["code"] == "missing_strategy_metrics" and alert["level"] == "info"
        for alert in monitor_summary["alerts"]
    )
    assert monitor_summary["data_gaps"] == []

    service = MonitorService(db, bitpro_adapter=adapter)
    service.ensure_default_monitors()
    run_result = service.run_monitor("mon_bitpro_paper_all")
    assert "monitor_data_gap" not in {alert["code"] for alert in run_result["alerts"]}
    assert run_result["data_gaps"] == []


def test_missing_dashboard_and_inventory_metrics_still_report_monitor_data_gap() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    adapter = _build_adapter(
        [
            {
                "id": 105,
                "name": "[合约][1H][CTA] SOL · 基准版 · 100U",
                "status": "running",
                "symbols": ["SOL/USDT:USDT"],
            }
        ],
        dashboard_payload={
            "system": {"state": "running", "mode": "paper", "strategy_id": 105},
            "equity": {},
            "performance": {},
        },
    )

    monitor_summary = adapter.paper_dashboard()["monitor_summary"]
    assert (
        "running strategy inventory does not include per-strategy PnL/drawdown metrics"
        in monitor_summary["data_gaps"]
    )

    service = MonitorService(db, bitpro_adapter=adapter)
    service.ensure_default_monitors()
    run_result = service.run_monitor("mon_bitpro_paper_all")
    assert "monitor_data_gap" in {alert["code"] for alert in run_result["alerts"]}
