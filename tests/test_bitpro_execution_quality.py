from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypertrade.bitpro.strategy_evidence import (
    BitProStrategyEvidenceError,
    validate_execution_quality,
)
from strategy_evidence_fixtures import execution_quality_payload, rehash

NOW = datetime(2026, 7, 21, tzinfo=UTC)


def test_execution_quality_keeps_unavailable_facts_explicit() -> None:
    result = validate_execution_quality(execution_quality_payload(), now=NOW)
    assert result["fill_count"] == 3
    assert result["order_count"] is None
    assert "order_count_unavailable" in result["data_gaps"]


def test_execution_quality_rejects_invalid_ratio_and_unbounded_errors() -> None:
    ratio = execution_quality_payload()
    ratio["fill_ratio"] = "1.1"
    ratio = rehash(ratio, volatile={"recorded_at"})
    with pytest.raises(BitProStrategyEvidenceError, match="between zero and one"):
        validate_execution_quality(ratio, now=NOW)

    errors = execution_quality_payload()
    errors["errors"] = ["bounded"] * 21
    errors = rehash(errors, volatile={"recorded_at"})
    with pytest.raises(BitProStrategyEvidenceError, match="bounded summary"):
        validate_execution_quality(errors, now=NOW)
