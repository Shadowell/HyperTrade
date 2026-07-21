from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypertrade.bitpro.strategy_evidence import (
    BitProStrategyEvidenceError,
    validate_aligned_matrix,
)
from strategy_evidence_fixtures import matrix_payload, rehash

NOW = datetime(2026, 7, 21, tzinfo=UTC)


def test_matrix_preserves_fixed_denominator_and_missing_reason() -> None:
    result = validate_aligned_matrix(matrix_payload(), now=NOW)
    assert result["denominator"] == 2
    assert result["available_count"] == 1
    assert result["missing_members"] == [
        {"member": "backtest:missing", "reason": "source_not_found"}
    ]
    assert result["comparable"] is False


def test_matrix_rejects_silent_member_loss_and_hash_mismatch() -> None:
    silent = matrix_payload()
    silent["missing_members"] = []
    silent = rehash(silent, volatile={"recorded_at"})
    with pytest.raises(BitProStrategyEvidenceError, match="denominator"):
        validate_aligned_matrix(silent, now=NOW)

    tampered = matrix_payload()
    tampered["rows"][0]["returns"][1] = "99"
    with pytest.raises(BitProStrategyEvidenceError, match="content_hash"):
        validate_aligned_matrix(tampered, now=NOW)
