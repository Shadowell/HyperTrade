from pathlib import Path

import pytest
from discovery_fixtures import NOW, FakeDiscoveryAdapter, discovery_request, seeded_discovery_db
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import AgentToolCall, StrategyDiscoveryCandidate
from hypertrade.main import create_app
from hypertrade.research.discovery import StrategyDiscoveryService
from sqlalchemy import func, select


def test_discovery_creates_dynamic_db_research_candidate_without_trading_authority() -> None:
    db, refs = seeded_discovery_db()
    adapter = FakeDiscoveryAdapter()
    result = StrategyDiscoveryService(db, adapter=adapter).discover(
        discovery_request(refs), actor="test", now=NOW
    )

    candidate = result["candidates"][0]
    assert result["status"] == "candidates_ready"
    assert candidate["status"] == "candidate_ready"
    assert candidate["bitpro_strategy_id"] == "8128"
    assert candidate["manifest_id"] and candidate["strategy_version_id"]
    assert adapter.calls == ["strategy_validate_code", "strategy_create"]
    assert adapter.created_config["research_candidate"] is True
    assert adapter.created_config["paper_enabled"] is False
    assert adapter.created_config["live_enabled"] is False
    assert result["execution_authorized"] is False
    assert result["mutation_boundary"] == {
        "bitpro_strategy_create": True,
        "paper_writes": False,
        "live_writes": False,
        "order_writes": False,
        "capital_writes": False,
    }
    with db.session() as session:
        assert session.scalar(select(func.count(StrategyDiscoveryCandidate.id))) == 1
        assert session.scalar(select(func.count(AgentToolCall.id))) == 0


def test_fingerprint_is_idempotent_and_code_failure_is_preserved() -> None:
    db, refs = seeded_discovery_db()
    adapter = FakeDiscoveryAdapter()
    service = StrategyDiscoveryService(db, adapter=adapter)
    first = service.discover(discovery_request(refs), actor="test", now=NOW)
    replay = service.discover(discovery_request(refs), actor="test", now=NOW)
    assert replay["id"] == first["id"]
    assert replay["replay"] == "idempotency"
    assert adapter.calls == ["strategy_validate_code", "strategy_create"]

    bad = discovery_request(
        refs,
        key="discovery-malicious-code",
        proposal_changes={
            "strategy_code": "class Bad(BaseStrategy):\n    x = open('/etc/passwd')\n"
        },
    )
    with pytest.raises(ValueError, match="nondeterministic"):
        service.discover(bad, actor="test", now=NOW)

    bad_db, bad_refs = seeded_discovery_db()
    bad = discovery_request(
        bad_refs,
        key="discovery-malicious-code-v2",
        proposal_changes={
            "strategy_code": "class Bad(BaseStrategy):\n    x = open('/etc/passwd')\n",
            "template_version": "discovery-template-v2",
        },
    )
    failed = StrategyDiscoveryService(
        bad_db, adapter=FakeDiscoveryAdapter()
    ).discover(bad, actor="test", now=NOW)
    assert failed["candidates"][0]["status"] == "sandbox_failed"
    assert "filesystem_access" in failed["candidates"][0]["rejection_reasons"]


def test_budget_and_prompt_injection_cannot_dispatch_trading_tools() -> None:
    db, refs = seeded_discovery_db()
    request = discovery_request(
        refs,
        key="discovery-budget-exhausted",
        proposal_changes={"model_calls": 2},
        mandate_changes={"max_model_calls": 1},
    )
    result = StrategyDiscoveryService(db, adapter=FakeDiscoveryAdapter()).discover(
        request, actor="test", now=NOW
    )
    assert result["candidates"][0]["status"] == "budget_exhausted"
    assert result["candidates"][0]["rejection_reasons"] == ["max_model_calls_exhausted"]
    with db.session() as session:
        assert session.scalar(select(func.count(AgentToolCall.id))) == 0

    source = (
        Path(__file__).parents[1]
        / "backend"
        / "src"
        / "hypertrade"
        / "research"
        / "discovery.py"
    ).read_text(encoding="utf-8")
    assert "paper_start" not in source
    assert "live_order" not in source
    assert "capital_allocation" not in source


def test_discovery_queue_api_is_authenticated_and_read_only(tmp_path) -> None:
    db, _ = seeded_discovery_db()
    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                KNOWLEDGE_DIR=tmp_path,
                DEEPSEEK_API_KEY="",
            ),
            db=db,
        )
    )

    assert client.get("/api/research/discovery-runs").status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "admin", "password": "secret"}
    ).status_code == 200
    response = client.get("/api/research/discovery-runs")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_provider_failure_is_a_terminal_redacted_fact() -> None:
    class FailingAdapter(FakeDiscoveryAdapter):
        def strategy_validate_code(self, **kwargs):
            raise RuntimeError("credential-like upstream detail must not be stored")

    db, refs = seeded_discovery_db()
    result = StrategyDiscoveryService(db, adapter=FailingAdapter()).discover(
        discovery_request(refs), actor="test", now=NOW
    )

    candidate = result["candidates"][0]
    assert candidate["status"] == "sandbox_failed"
    assert candidate["rejection_reasons"] == ["bitpro_strategy_validation_unavailable"]
    assert "credential-like" not in str(candidate)
