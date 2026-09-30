from __future__ import annotations

import io
from typing import Any

from fastapi.testclient import TestClient
from hypertrade.cli import main as cli_main
from hypertrade.db import Database
from hypertrade.main import create_app


def test_reflexion_api_endpoints() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()

    app = create_app(db=db)
    client = TestClient(app)

    # 1. Test reflexion alert endpoint (without webhook -> skipped)
    res_alert = client.post("/api/research/reflexion/alerts/test")
    assert res_alert.status_code == 200
    data_alert = res_alert.json()
    assert "alert_id" in data_alert
    assert "status" in data_alert

    # 2. Test RSI evolution cycle endpoint (no alert to avoid network)
    res_rsi = client.post(
        "/api/research/evolution/rsi-cycle",
        json={"symbol": "ETH-USDT-SWAP", "timeframe": "1H", "dispatch_alert": False},
    )
    assert res_rsi.status_code == 200
    data_rsi = res_rsi.json()
    assert data_rsi["status"] == "completed"
    assert data_rsi["symbol"] == "ETH-USDT-SWAP"
    assert data_rsi["initial_candidate_id"] != ""
    assert data_rsi["mutated_candidate_id"] != ""
    assert len(data_rsi["negative_constraints"]) > 0

    # 3. Test reflexion history endpoint
    res_hist = client.post("/api/research/reflexion/history")
    # Note: GET method
    res_hist = client.get("/api/research/reflexion/history")
    assert res_hist.status_code == 200
    data_hist = res_hist.json()
    assert "negative_constraints" in data_hist


def test_reflexion_cli_commands(monkeypatch: Any) -> None:
    # 1. Test alert command
    out = io.StringIO()
    code = cli_main(["reflexion", "alert", "--test"], output=out)
    assert code == 0
    assert "Reflexion alert status" in out.getvalue()

    # 2. Test evolve-rsi command
    out = io.StringIO()
    code = cli_main(
        ["reflexion", "evolve-rsi", "--symbol", "ETH-USDT-SWAP", "--no-alert"],
        output=out,
    )
    assert code == 0
    val = out.getvalue()
    assert "RSI 策略自主进化与交易反思闭环报告" in val
    assert "ETH-USDT-SWAP" in val
    assert "提炼反思约束" in val

    # 3. Test list command
    out = io.StringIO()
    code = cli_main(["reflexion", "list"], output=out)
    assert code == 0
    assert "Active Negative Constraints" in out.getvalue()
