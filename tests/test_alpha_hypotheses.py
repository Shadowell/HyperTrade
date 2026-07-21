import pytest
from discovery_fixtures import NOW, FakeDiscoveryAdapter, discovery_request, seeded_discovery_db
from hypertrade.research.discovery import StrategyDiscoveryService
from hypertrade.research.discovery_schemas import AlphaHypothesisV1
from pydantic import ValidationError


def test_hypothesis_is_frozen_before_locked_oos_is_visible() -> None:
    _, refs = seeded_discovery_db()
    hypothesis = discovery_request(refs).proposals[0].hypothesis

    assert hypothesis.locked_oos_visible is False
    assert hypothesis.frozen_at == NOW
    assert hypothesis.falsification_criteria
    assert hypothesis.failure_conditions


def test_hypothesis_contract_rejects_post_oos_visibility() -> None:
    _, refs = seeded_discovery_db()
    payload = discovery_request(refs).proposals[0].hypothesis.model_dump()
    payload["locked_oos_visible"] = True

    with pytest.raises(ValidationError):
        AlphaHypothesisV1.model_validate(payload)


def test_changed_hypothesis_requires_a_new_version() -> None:
    db, refs = seeded_discovery_db()
    service = StrategyDiscoveryService(db, adapter=FakeDiscoveryAdapter())
    service.discover(discovery_request(refs), actor="test", now=NOW)
    changed = discovery_request(refs, key="changed-hypothesis-version")
    changed.proposals[0].hypothesis.economic_rationale = (
        "A materially changed rationale that must not overwrite frozen version one."
    )

    with pytest.raises(ValueError, match="immutable"):
        service.discover(changed, actor="test", now=NOW)
