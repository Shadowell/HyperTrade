from datetime import timedelta

import pytest
from discovery_fixtures import NOW, FakeDiscoveryAdapter, discovery_request, seeded_discovery_db
from hypertrade.db import ResearchEvidence
from hypertrade.research.discovery import StrategyDiscoveryService


def test_real_fresh_evidence_produces_auditable_phenomenon() -> None:
    db, refs = seeded_discovery_db()
    result = StrategyDiscoveryService(db, adapter=FakeDiscoveryAdapter()).discover(
        discovery_request(refs), actor="test", now=NOW
    )

    candidate = result["candidates"][0]
    assert candidate["phenomenon"]["phenomenon_key"] == "btc_funding_dispersion"
    assert candidate["phenomenon"]["evidence_ids"] == [refs["evidence_id"]]
    assert candidate["phenomenon"]["alternative_explanations"]


def test_stale_or_text_only_evidence_fails_closed() -> None:
    db, refs = seeded_discovery_db()
    with db.session() as session:
        row = session.get(ResearchEvidence, refs["evidence_id"])
        assert row is not None
        row.as_of = NOW - timedelta(days=2)
    with pytest.raises(ValueError, match="stale"):
        StrategyDiscoveryService(db, adapter=FakeDiscoveryAdapter()).discover(
            discovery_request(refs), actor="test", now=NOW
        )
