from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypertrade.bitpro.strategy_evidence import (
    BitProStrategyEvidenceError,
    BitProStrategyEvidenceStore,
    validate_return_series,
)
from hypertrade.db import BitProStrategyEvidenceRecord, Database
from sqlalchemy import select
from strategy_evidence_fixtures import rehash, return_series_payload

NOW = datetime(2026, 7, 21, tzinfo=UTC)


def test_complete_costed_series_validates_and_only_bounded_summary_persists() -> None:
    payload = return_series_payload()
    assert validate_return_series(payload, now=NOW)["source_hash"] == payload["source_hash"]
    db = Database("sqlite:///:memory:")
    db.create_all()
    result = BitProStrategyEvidenceStore(db).persist(payload, actor="contract-test")
    replay = BitProStrategyEvidenceStore(db).persist(payload, actor="contract-test")

    assert result["raw_series_persisted"] is False
    assert result["execution_authorized"] is False
    assert result["summary"]["point_count"] == 2
    assert replay["id"] == result["id"] and replay["idempotent"] is True
    with db.session() as session:
        row = session.scalar(select(BitProStrategyEvidenceRecord))
        assert row is not None
        assert "points" not in row.summary_json
        assert "equity" not in repr(row.summary_json)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value.update(schema_version="strategy_return_series.v2"), "unsupported"),
        (lambda value: value["cost_model"]["fees"].pop("taker_fee_bps"), "taker fee"),
        (lambda value: value["points"].append(dict(value["points"][-1])), "increasing"),
        (
            lambda value: value["points"][-1].update(timestamp="2030-01-01T00:00:00+00:00"),
            "future",
        ),
        (lambda value: value["pagination"].update(total_points=501), "500-point"),
    ],
)
def test_invalid_series_contract_fails_closed(mutator, message: str) -> None:
    payload = return_series_payload()
    mutator(payload)
    payload = rehash(payload, volatile={"freshness", "recorded_at"})
    with pytest.raises(BitProStrategyEvidenceError, match=message):
        validate_return_series(payload, now=NOW)


def test_tampered_content_or_source_hash_fails_closed() -> None:
    content = return_series_payload()
    content["net_return"] = "999"
    with pytest.raises(BitProStrategyEvidenceError, match="content_hash"):
        validate_return_series(content, now=NOW)

    source = return_series_payload()
    source["source_hash"] = "sha256:" + "0" * 64
    source = rehash(source, volatile={"freshness", "recorded_at"})
    with pytest.raises(BitProStrategyEvidenceError, match="source_hash"):
        validate_return_series(source, now=NOW)
