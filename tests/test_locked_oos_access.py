from datetime import datetime, timedelta

from hypertrade.research.validation_v2 import UnifiedStrategyValidationService
from validation_v2_fixtures import seeded_validation_candidate, validation_request


def test_oos_access_before_candidate_freeze_invalidates_family() -> None:
    db, refs = seeded_validation_candidate("discovery")
    frozen = datetime.fromisoformat(refs["frozen_at"])
    result = UnifiedStrategyValidationService(db).validate(
        validation_request(
            refs,
            family_changes={
                "locked_oos_first_accessed_at": frozen - timedelta(seconds=1)
            },
        ),
        actor="test",
    )

    assert result["status"] == "rejected"
    assert result["gates"]["locked_oos_access"]["reasons"] == [
        "locked_oos_access_precedes_candidate_freeze"
    ]


def test_missing_oos_access_is_needs_data() -> None:
    db, refs = seeded_validation_candidate("discovery")
    result = UnifiedStrategyValidationService(db).validate(
        validation_request(
            refs,
            key="validation-missing-oos-access",
            family_changes={"locked_oos_first_accessed_at": None},
        ),
        actor="test",
    )
    assert result["status"] == "needs_data"
