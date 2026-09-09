import pytest
from hypertrade.arc.contracts import ARCSuccessCriteriaV1
from hypertrade.arc.self_test import apply_success_criteria


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", True])
def test_nonfinite_or_boolean_metrics_cannot_pass(bad):
    valid, reasons = apply_success_criteria(
        {"sharpe": bad, "max_drawdown": bad, "trades": bad, "net_return": bad},
        ARCSuccessCriteriaV1(),
    )
    assert not valid
    assert reasons
