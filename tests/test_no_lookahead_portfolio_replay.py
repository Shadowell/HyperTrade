from __future__ import annotations

from datetime import timedelta

import pytest
from hypertrade.db import Database, PaperCohortSnapshot
from hypertrade.portfolio.regime_shadow import RegimeShadowAllocatorServiceV2
from regime_shadow_support import DECISION, build_request, seed_sources


def test_replay_is_bound_to_then_visible_sources() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id, regime_id = seed_sources(db, suffix="replay")
    service = RegimeShadowAllocatorServiceV2(db)
    target = service.build(
        build_request(cohort_id, regime_id, key="no-lookahead-replay-build"),
        actor="test",
    )

    replay = service.replay(target["id"])

    assert replay["no_lookahead_verified"] is True
    assert replay["source_hash"] == target["source_hash"]
    assert replay["target_weights"] == target["target_weights"]
    assert replay["execution_authorized"] is False


def test_future_cohort_fact_is_rejected() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    cohort_id, regime_id = seed_sources(db, suffix="future")
    with db.session() as session:
        cohort = session.get(PaperCohortSnapshot, cohort_id)
        assert cohort is not None
        cohort.created_at = DECISION + timedelta(seconds=1)

    with pytest.raises(ValueError, match="lookahead source rejected"):
        RegimeShadowAllocatorServiceV2(db).build(
            build_request(cohort_id, regime_id, key="future-cohort-build"),
            actor="test",
        )
