from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypertrade.research.evidence_schemas import (
    EvidenceScope,
    EvidenceSourceRef,
    FactEvidenceInput,
    InferenceEvidenceInput,
    evidence_content_hash,
)
from pydantic import ValidationError


def _source(source_id: str = "evt_1", *, observed_at: datetime | None = None) -> EvidenceSourceRef:
    return EvidenceSourceRef(
        source_type="tool",
        source_id=source_id,
        tool_name="market_ticker",
        observed_at=observed_at or datetime(2026, 7, 14, 8, tzinfo=UTC),
    )


def test_canonical_hash_normalizes_utc_decimal_scope_and_source_order() -> None:
    utc_time = datetime(2026, 7, 14, 8, tzinfo=UTC)
    china_time = datetime(2026, 7, 14, 16, tzinfo=timezone(timedelta(hours=8)))
    first = FactEvidenceInput(
        claim=" BTC price is 70000 ",
        scope=EvidenceScope(symbols=["ETH", "btc", "BTC"], timeframes=["4h", "1h"]),
        sources=[_source("evt_2"), _source("evt_1")],
        confidence=Decimal("0.8000"),
        as_of=utc_time,
        task_id="task_1",
    )
    second = FactEvidenceInput(
        claim="BTC   price is 70000",
        scope=EvidenceScope(symbols=["BTC", "ETH"], timeframes=["1H", "4H"]),
        sources=[
            _source("evt_1", observed_at=china_time),
            _source("evt_2", observed_at=china_time),
        ],
        confidence=Decimal("0.8"),
        as_of=china_time,
        task_id="task_1",
    )

    assert first.scope.symbols == ["BTC", "ETH"]
    assert evidence_content_hash(first) == evidence_content_hash(second)


def test_evidence_schema_rejects_ambiguous_time_and_unanchored_inference() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        _source(observed_at=datetime(2026, 7, 14, 8))

    with pytest.raises(ValidationError, match="supporting_evidence_ids"):
        InferenceEvidenceInput(
            claim="Trend likely persists",
            scope=EvidenceScope(symbols=["BTC"]),
            sources=[],
            confidence=Decimal("0.5"),
            as_of=datetime.now(UTC),
            role_key="market_regime",
            inference_method="bounded synthesis",
        )


def test_bitpro_and_snapshot_sources_require_content_hash() -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        EvidenceSourceRef(
            source_type="bitpro_result",
            source_id="result-1",
            observed_at=datetime.now(UTC),
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FactEvidenceInput.model_validate(
            {
                "evidence_type": "fact",
                "claim": "A valid-looking claim",
                "confidence": "0.5",
                "as_of": datetime.now(UTC).isoformat(),
                "private_reasoning": "must never enter evidence storage",
            }
        )
