from decimal import Decimal

import pytest
from hypertrade.research.validation_v2_schemas import ValidationPolicyV2
from pydantic import ValidationError


def test_policy_freezes_required_validation_thresholds() -> None:
    policy = ValidationPolicyV2()
    assert policy.walk_forward_folds == 3
    assert policy.purge_bars == 1
    assert policy.embargo_bars == 1
    assert policy.require_funding is True
    assert policy.require_capacity is True
    assert policy.missing_data_policy == "needs_data"


def test_policy_rejects_zero_cost_stress_and_invalid_bias_thresholds() -> None:
    with pytest.raises(ValidationError):
        ValidationPolicyV2(min_stress_multiplier=Decimal("1"))
    with pytest.raises(ValidationError):
        ValidationPolicyV2(max_overfit_probability=Decimal("1.1"))
