from __future__ import annotations

import io
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hypertrade.cli import main as cli_main
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.research.optimization.service import OptimizationService


def test_optimization_service_lifecycle() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()

    svc = OptimizationService(db)

    # 1. Start Study
    study = svc.start_study(
        strategy_identifier="test_e2e_strategy",
        symbols=["BTC-USDT-SWAP"],
        timeframes=["1H"],
        search_method="grid",
        max_trials=4,
        is_ratio=0.70,
        objective="composite_score",
    )

    study_id = study["id"]
    assert study["status"] == "completed"
    assert study["completed_trials"] > 0
    assert study["best_score"] is not None
    assert study["best_parameters"] is not None

    # 2. Get Study
    fetched = svc.get_study(study_id)
    assert fetched is not None
    assert fetched["id"] == study_id

    # 3. List Studies
    studies = svc.list_studies()
    assert len(studies) >= 1
    assert any(s["id"] == study_id for s in studies)

    # 4. Get Trials
    trials = svc.get_study_trials(study_id)
    assert len(trials) == study["completed_trials"]
    for t in trials:
        assert "parameters" in t
        assert "is_metrics" in t
        assert "oos_metrics" in t
        assert "composite_score" in t

    # 5. Export to QuantLab
    ql_export = svc.export_study(study_id, target_format="quantlab")
    assert ql_export["target_id"] == "quantlab"
    assert ql_export["strategy_id"] == "test_e2e_strategy"
    assert ql_export["optimized_parameters"] == study["best_parameters"]

    # 6. Export to BitPro
    bp_export = svc.export_study(study_id, target_format="bitpro")
    assert bp_export["target_id"] == "bitpro"
    assert bp_export["strategy_key"] == "test_e2e_strategy"
    assert bp_export["parameters"] == study["best_parameters"]


def test_optimization_api_endpoints() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(db=db)
    client = TestClient(app)

    # 1. Start study via API
    res = client.post(
        "/api/research/optimization/start",
        json={
            "strategy_identifier": "api_trend_strategy",
            "symbols": ["BTC-USDT-SWAP"],
            "timeframes": ["1H"],
            "search_method": "random",
            "max_trials": 3,
            "is_ratio": 0.70,
            "objective": "composite_score",
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    study_id = data["id"]
    assert data["status"] == "completed"
    assert data["completed_trials"] == 3

    # 2. List studies
    list_res = client.get("/api/research/optimization/studies")
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    assert any(item["id"] == study_id for item in items)

    # 3. Get study details
    get_res = client.get(f"/api/research/optimization/studies/{study_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == study_id

    # 4. Get study trials
    trials_res = client.get(f"/api/research/optimization/studies/{study_id}/trials")
    assert trials_res.status_code == 200
    assert len(trials_res.json()["trials"]) == 3

    # 5. Export QuantLab via API
    export_res = client.post(
        f"/api/research/optimization/studies/{study_id}/export",
        json={"target_format": "quantlab"},
    )
    assert export_res.status_code == 200
    exp_data = export_res.json()
    assert exp_data["target_id"] == "quantlab"
    assert exp_data["strategy_id"] == "api_trend_strategy"

    # 6. Export BitPro via API
    bp_res = client.post(
        f"/api/research/optimization/studies/{study_id}/export",
        json={"target_format": "bitpro"},
    )
    assert bp_res.status_code == 200
    assert bp_res.json()["target_id"] == "bitpro"


def test_optimization_cli_commands(tmp_path: Any, monkeypatch: Any) -> None:
    db_file = tmp_path / "cli_test.db"
    db_url = f"sqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("HYPERTRADE_DATABASE_URL", db_url)

    # Initialize db schema
    db = Database(db_url)
    db.create_all()

    # 1. Run optimization
    buf = io.StringIO()
    code = cli_main(
        [
            "--local",
            "optimize",
            "run",
            "--strategy",
            "cli_test_strategy",
            "--trials",
            "2",
            "--method",
            "grid",
        ],
        output=buf,
    )
    assert code == 0
    run_output = json.loads(buf.getvalue().strip())
    study_id = run_output["id"]
    assert run_output["status"] == "completed"

    # 2. List studies
    buf = io.StringIO()
    code = cli_main(["--local", "optimize", "list"], output=buf)
    assert code == 0
    list_output = json.loads(buf.getvalue().strip())
    assert any(s["id"] == study_id for s in list_output)

    # 3. Status
    buf = io.StringIO()
    code = cli_main(["--local", "optimize", "status", study_id], output=buf)
    assert code == 0
    status_output = json.loads(buf.getvalue().strip())
    assert status_output["id"] == study_id
    assert status_output["trials_count"] > 0

    # 4. Export
    buf = io.StringIO()
    code = cli_main(["--local", "optimize", "export", study_id, "--format", "quantlab"], output=buf)
    assert code == 0
    export_output = json.loads(buf.getvalue().strip())
    assert export_output["target_id"] == "quantlab"
    assert export_output["strategy_id"] == "cli_test_strategy"
