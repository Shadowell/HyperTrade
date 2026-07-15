from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypertrade.cli import handle_slash_command
from hypertrade.config import Settings
from hypertrade.db import Database, PortfolioObservationWindow
from hypertrade.main import create_app
from hypertrade.portfolio.evidence import PortfolioEvidenceService
from hypertrade.portfolio.evidence_schemas import PortfolioObservationCaptureV1
from hypertrade.research.strategy_cards import StrategyCardService
from sqlalchemy import func, select

NOW = datetime(2026, 7, 15, 4, 0, tzinfo=UTC)


def _card(card_id: str, strategy_id: str = "") -> dict[str, Any]:
    return {
        "schema_version": "strategy_card.v2",
        "card_id": card_id,
        "snapshot_id": f"snapshot_{card_id}",
        "strategy_key": f"strategy_{card_id}",
        "bitpro_strategy_id": strategy_id,
        "version": {"id": f"version_{card_id}"},
        "source_refs": {"manifest_id": f"manifest_{card_id}"},
        "allowed_symbols": ["BTC-USDT-SWAP"],
        "allowed_timeframes": ["1h"],
        "strategy_category": ["TREND"],
        "direction_exposure": "long",
        "capacity": "10000",
        "liquidity": "available",
    }


def _curve(values: list[int], *, end: datetime = NOW - timedelta(minutes=1)) -> list[dict]:
    start = end - timedelta(hours=len(values) - 1)
    return [
        {"timestamp": (start + timedelta(hours=index)).isoformat(), "equity": str(value)}
        for index, value in enumerate(values)
    ]


class ReadAdapter:
    def __init__(self, curves: dict[int, list[dict]], *, healthy: bool = True) -> None:
        self.curves = curves
        self.healthy = healthy
        self.snapshot_calls: list[int] = []
        self.curve_calls: list[tuple[int, int]] = []

    def health(self) -> dict[str, Any]:
        return {"status": "ok" if self.healthy else "error", "contract_version": "test"}

    def paper_snapshot(
        self, *, strategy_id: int | None = None, instance_id: str | None = None
    ) -> dict[str, Any]:
        assert strategy_id is not None
        self.snapshot_calls.append(strategy_id)
        return {"status": "ok", "snapshot": {"strategy_id": strategy_id}}

    def paper_equity_curve(
        self, *, strategy_id: int | None = None, sample_limit: int = 50
    ) -> dict[str, Any]:
        assert strategy_id is not None
        self.curve_calls.append((strategy_id, sample_limit))
        return {
            "status": "ok",
            "strategy_id": strategy_id,
            "equity_curve": self.curves[strategy_id][:sample_limit],
        }


def _payload(key: str = "portfolio-window-key-001", **values: Any) -> PortfolioObservationCaptureV1:
    return PortfolioObservationCaptureV1(idempotency_key=key, max_points=50, **values)


def test_capture_persists_bounded_summaries_and_decimal_pairwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    monkeypatch.setattr(
        StrategyCardService,
        "list",
        lambda _: [_card("left", "101"), _card("right", "102")],
    )
    adapter = ReadAdapter(
        {
            101: _curve([100, 102, 101, 105, 108, 107, 112, 115, 114]),
            102: _curve([200, 203, 201, 209, 215, 213, 222, 229, 227]),
        }
    )

    result = PortfolioEvidenceService(db, adapter=adapter).capture(
        _payload(), actor="test", now=NOW
    )

    assert result["status"] == "available"
    assert result["quality"]["denominator"] == 2
    assert result["quality"]["available_count"] == 2
    assert result["quality"]["coverage_ratio"] == "1.00000000"
    assert len(result["strategies"]) == 2
    assert result["pairwise"][0]["status"] == "available"
    assert result["pairwise"][0]["sample_count"] == 8
    assert isinstance(result["pairwise"][0]["correlation"], str)
    assert result["execution_authorized"] is False
    assert result["raw_series_persisted"] is False
    with db.session() as session:
        row = session.scalar(select(PortfolioObservationWindow))
        assert row is not None
        assert all(
            "equity_curve" not in item and "returns" not in item
            for item in row.strategy_summaries_json
        )
        assert all("returns" not in item for item in row.pairwise_json)


def test_manifest_only_card_remains_in_denominator_without_bitpro_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    monkeypatch.setattr(StrategyCardService, "list", lambda _: [_card("manifest-only")])
    adapter = ReadAdapter({})

    result = PortfolioEvidenceService(db, adapter=adapter).capture(
        _payload(), actor="test", now=NOW
    )

    assert result["status"] == "no_window"
    assert result["quality"]["denominator"] == 1
    assert result["quality"]["identity_count"] == 0
    assert result["strategies"][0]["status"] == "no_window"
    assert "paper_identity_unavailable" in result["strategies"][0]["unknown_reasons"]
    assert adapter.snapshot_calls == []
    assert adapter.curve_calls == []


def test_stale_and_zero_variance_sources_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    monkeypatch.setattr(
        StrategyCardService,
        "list",
        lambda _: [_card("stale", "201"), _card("flat", "202")],
    )
    adapter = ReadAdapter(
        {
            201: _curve([100, 101, 102, 103, 104, 105, 106, 107], end=NOW - timedelta(days=2)),
            202: _curve([100] * 8),
        }
    )

    result = PortfolioEvidenceService(db, adapter=adapter).capture(
        _payload(freshness_minutes=60, min_aligned_returns=5), actor="test", now=NOW
    )

    rows = {row["card_id"]: row for row in result["strategies"]}
    assert rows["stale"]["status"] == "stale"
    assert rows["flat"]["status"] == "available"
    assert result["pairwise"][0]["status"] == "unknown"
    assert result["pairwise"][0]["unknown_reason"] == "strategy_window_unavailable"


def test_idempotency_binds_request_and_content_replay_does_not_append(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    monkeypatch.setattr(StrategyCardService, "list", lambda _: [_card("only", "301")])
    adapter = ReadAdapter({301: _curve([100, 101, 103, 102, 106, 105, 109, 111])})
    service = PortfolioEvidenceService(db, adapter=adapter)

    first = service.capture(_payload(), actor="test", now=NOW)
    replay = service.capture(_payload(), actor="test", now=NOW)
    duplicate = service.capture(
        _payload(key="portfolio-window-key-002"),
        actor="test",
        now=NOW + timedelta(minutes=10),
    )

    assert replay["id"] == first["id"]
    assert replay["idempotent"] is True
    assert duplicate["id"] == first["id"]
    assert duplicate["idempotent_content"] is True
    with db.session() as session:
        assert session.scalar(select(func.count(PortfolioObservationWindow.id))) == 1
    with pytest.raises(ValueError, match="bound to another request"):
        service.capture(_payload(horizon_days=60), actor="test", now=NOW)


def test_unhealthy_source_and_invalid_points_do_not_create_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    monkeypatch.setattr(StrategyCardService, "list", lambda _: [_card("unhealthy", "401")])
    adapter = ReadAdapter({401: []}, healthy=False)

    result = PortfolioEvidenceService(db, adapter=adapter).capture(
        _payload(), actor="test", now=NOW
    )

    assert result["status"] == "source_unhealthy"
    assert result["strategies"][0]["sample_count"] == 0
    assert result["strategies"][0]["metrics"]["total_return_pct"] == "unknown"
    assert adapter.snapshot_calls == []
    assert adapter.curve_calls == []


def test_snapshot_failure_does_not_block_curve_but_curve_failure_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    monkeypatch.setattr(StrategyCardService, "list", lambda _: [_card("partial", "402")])

    class SnapshotFailureAdapter(ReadAdapter):
        def paper_snapshot(
            self, *, strategy_id: int | None = None, instance_id: str | None = None
        ) -> dict[str, Any]:
            raise RuntimeError("snapshot unavailable")

    partial = PortfolioEvidenceService(
        db,
        adapter=SnapshotFailureAdapter(
            {402: _curve([100, 101, 103, 102, 105, 107, 106, 109])}
        ),
    ).capture(_payload(), actor="test", now=NOW)

    assert partial["status"] == "available"
    assert partial["strategies"][0]["sample_count"] == 7
    assert "bitpro_snapshot_read_failed:RuntimeError" in partial["strategies"][0][
        "unknown_reasons"
    ]

    class CurveFailureAdapter(ReadAdapter):
        def paper_equity_curve(
            self, *, strategy_id: int | None = None, sample_limit: int = 50
        ) -> dict[str, Any]:
            raise RuntimeError("curve unavailable")

    failed = PortfolioEvidenceService(
        db,
        adapter=CurveFailureAdapter({402: []}),
    ).capture(
        _payload(key="portfolio-window-key-curve-failure"),
        actor="test",
        now=NOW,
    )

    assert failed["status"] == "source_unhealthy"
    assert failed["strategies"][0]["status"] == "source_unhealthy"


def test_evidence_module_exposes_no_mutation_adapter_surface() -> None:
    source = (
        Path(__file__).parents[1]
        / "backend"
        / "src"
        / "hypertrade"
        / "portfolio"
        / "evidence.py"
    ).read_text(encoding="utf-8")

    assert "hypertrade.paper.service" not in source
    assert "hypertrade.live" not in source
    assert "live_order" not in source
    assert "paper_start" not in source
    assert "capital_allocation" not in source


def test_observation_window_api_requires_admin_and_uses_server_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    monkeypatch.setattr(StrategyCardService, "list", lambda _: [_card("api", "501")])
    adapter = ReadAdapter({501: _curve([100, 101, 103, 105, 104, 108, 110, 112])})
    client = TestClient(
        create_app(
            settings=Settings(
                ADMIN_USERNAME="admin",
                ADMIN_PASSWORD="secret",
                SESSION_SECRET="portfolio-window-api-test",
            ),
            db=db,
            bitpro_adapter=adapter,  # type: ignore[arg-type]
        )
    )

    assert client.get("/api/portfolio/observation-windows").status_code == 401
    assert (
        client.post("/api/auth/login", json={"username": "admin", "password": "secret"}).status_code
        == 200
    )
    response = client.post(
        "/api/portfolio/observation-windows",
        json={
            "max_points": 50,
            "idempotency_key": "portfolio-window-api-key-001",
        },
    )
    assert response.status_code == 200
    window = response.json()
    assert window["raw_series_persisted"] is False
    assert client.get("/api/portfolio/observation-windows").json()["items"][0]["id"] == window["id"]
    assert client.get(f"/api/portfolio/observation-windows/{window['id']}").status_code == 200


def test_windows_cli_renders_server_quality_without_recalculation() -> None:
    class WindowClient:
        def list_portfolio_observation_windows(self) -> list[dict[str, Any]]:
            return [
                {
                    "id": "pwin_1",
                    "status": "available",
                    "horizon_days": 30,
                    "bucket_minutes": 60,
                    "quality": {
                        "denominator": 3,
                        "available_count": 2,
                        "coverage_ratio": "0.66666667",
                    },
                }
            ]

    output = StringIO()
    handle_slash_command("/windows", client=WindowClient(), output=output)  # type: ignore[arg-type]

    rendered = output.getvalue()
    assert "pwin_1 [available]" in rendered
    assert "cards=3 available=2 coverage=0.66666667" in rendered
