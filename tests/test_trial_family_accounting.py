from hypertrade.research.validation_v2 import UnifiedStrategyValidationService
from validation_v2_fixtures import seeded_validation_candidate, validation_request


def test_failed_trials_remain_counted_and_cannot_be_deleted() -> None:
    db, refs = seeded_validation_candidate("evolution")
    result = UnifiedStrategyValidationService(db).validate(
        validation_request(
            refs,
            family_changes={"declared_attempt_count": 3},
        ),
        actor="test",
    )

    assert result["status"] == "rejected"
    assert result["gates"]["trial_accounting"]["outcome"] == "failed"
    assert len(result["trial_family"]["attempts"]) == 2


def test_all_attempts_including_failures_can_validate() -> None:
    db, refs = seeded_validation_candidate("evolution")
    result = UnifiedStrategyValidationService(db).validate(
        validation_request(refs), actor="test"
    )

    assert result["status"] == "validated"
    assert result["gates"]["trial_accounting"]["outcome"] == "passed"
