from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from hypertrade.db import Database, MarketRegimeSnapshotV2
from hypertrade.portfolio.market_regime_v2 import MarketRegimeSnapshotServiceV2
from hypertrade.portfolio.regime_shadow_schemas import (
    MarketRegimeCaptureV2,
    MarketRegimeEvidenceV2,
)
from sqlalchemy import func, select

NOW = datetime(2026, 7, 23, 12, tzinfo=UTC)


def _request(
    *,
    key: str = "market-regime-snapshot-v2-001",
    as_of: datetime = NOW,
    changes: dict[str, object] | None = None,
) -> MarketRegimeCaptureV2:
    evidence: dict[str, object] = {
        "as_of": as_of,
        "available_at": as_of - timedelta(seconds=1),
        "source_refs": ["world-state:point-in-time:001"],
        "source_hash": "sha256:" + "a" * 64,
        "trend_score": "0.8",
        "range_score": "0.2",
        "high_volatility_score": "0.3",
        "stress_score": "0.1",
        "liquidity_score": "0.7",
        "correlation_score": "0.4",
        "ex_post_label": "trend",
    }
    evidence.update(changes or {})
    return MarketRegimeCaptureV2(
        evidence=MarketRegimeEvidenceV2.model_validate(evidence),
        freshness_minutes=60,
        idempotency_key=key,
    )


def test_regime_snapshot_is_probabilistic_source_bound_and_idempotent() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = MarketRegimeSnapshotServiceV2(db)

    created = service.capture(_request(), actor="test", now=NOW)
    replay = service.capture(_request(), actor="test", now=NOW)

    values = [Decimal(value) for value in created["probabilities"].values()]
    assert sum(values) == Decimal("1.000000000000")
    assert created["status"] == "available"
    assert created["ex_post"] == {"label": "trend", "used_for_decision": False}
    assert created["execution_authorized"] is False
    assert created["paper_lifecycle_authorized"] is False
    assert created["live_authorized"] is False
    assert replay["id"] == created["id"]
    assert replay["replay"] == "idempotency"
    with db.session() as session:
        assert session.scalar(select(func.count(MarketRegimeSnapshotV2.id))) == 1


def test_missing_scores_remain_unknown_and_stale_source_is_not_available() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    result = MarketRegimeSnapshotServiceV2(db).capture(
        _request(
            as_of=NOW - timedelta(hours=2),
            changes={"range_score": None, "correlation_score": None},
        ),
        actor="test",
        now=NOW,
    )

    assert result["status"] == "stale"
    assert result["probabilities"]["range"] == "unknown"
    assert result["probabilities"]["correlation"] == "unknown"
    assert "regime.source_stale" in result["unknowns"]


def test_future_or_lookahead_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="not available"):
        _request(changes={"available_at": NOW + timedelta(seconds=1)})

    db = Database("sqlite:///:memory:")
    db.create_all()
    with pytest.raises(ValueError, match="future"):
        MarketRegimeSnapshotServiceV2(db).capture(
            _request(as_of=NOW + timedelta(minutes=1), key="future-regime-key"),
            actor="test",
            now=NOW,
        )


def test_historical_lookup_never_selects_a_future_snapshot() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = MarketRegimeSnapshotServiceV2(db)
    older = service.capture(
        _request(
            key="older-regime-snapshot",
            as_of=NOW - timedelta(minutes=20),
        ),
        actor="test",
        now=NOW,
    )
    service.capture(
        _request(
            key="newer-regime-snapshot",
            as_of=NOW,
            changes={"source_hash": "sha256:" + "b" * 64},
        ),
        actor="test",
        now=NOW,
    )

    selected = service.latest_at(NOW - timedelta(minutes=10))

    assert selected is not None
    assert selected["id"] == older["id"]
