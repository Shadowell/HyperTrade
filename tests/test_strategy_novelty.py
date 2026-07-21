from decimal import Decimal

from discovery_fixtures import discovery_request, seeded_discovery_db
from hypertrade.research.discovery import StrategyDiscoveryService
from sqlalchemy import select


def test_explainable_feature_and_regime_difference_is_novel() -> None:
    db, refs = seeded_discovery_db()
    proposal = discovery_request(refs).proposals[0]
    report = StrategyDiscoveryService(db).assess_novelty(
        proposal,
        code_sha="c" * 64,
    )

    assert report.status == "novel"
    assert report.reasons == ["explainable_feature_or_regime_difference"]


def test_unrelated_strategy_family_does_not_require_correlation_evidence() -> None:
    db, refs = seeded_discovery_db()
    proposal = discovery_request(refs).proposals[0]
    proposal.novelty_comparisons = []

    report = StrategyDiscoveryService(db).assess_novelty(proposal, code_sha="c" * 64)

    assert report.status == "novel"
    assert report.unknowns == []


def test_highly_correlated_candidate_is_existing_strategy_variant() -> None:
    db, refs = seeded_discovery_db()
    request = discovery_request(refs)
    comparison = request.proposals[0].novelty_comparisons[0]
    comparison.return_correlation = Decimal("0.95")
    report = StrategyDiscoveryService(db).assess_novelty(
        request.proposals[0], code_sha="c" * 64
    )

    assert report.status == "existing_strategy_variant"
    assert report.max_return_correlation == Decimal("0.95")


def test_renamed_equivalent_spec_is_not_novel() -> None:
    db, refs = seeded_discovery_db()
    proposal = discovery_request(refs).proposals[0]
    with db.session() as session:
        from hypertrade.db import ExperimentManifest

        existing = session.scalars(select(ExperimentManifest)).first()
        assert existing is not None
        existing_spec = dict(existing.canonical_json["strategy_spec"])
    payload = proposal.hypothesis.strategy_spec.model_dump()
    payload.update(existing_spec)
    payload["strategy_key"] = "renamed_existing_strategy"
    payload["title"] = "A renamed strategy"
    proposal.hypothesis.strategy_spec = proposal.hypothesis.strategy_spec.model_validate(payload)

    report = StrategyDiscoveryService(db).assess_novelty(proposal, code_sha="c" * 64)
    assert report.status == "existing_strategy_variant"
