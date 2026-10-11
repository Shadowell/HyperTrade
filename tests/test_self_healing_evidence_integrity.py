from unittest.mock import Mock

from hypertrade.arc.evolution import _heal_bitpro_fallback
from hypertrade.paper.self_healing import SelfHealingEvolutionEngine, generate_7d_attribution_report


def test_missing_candidate_receipt_cannot_pass_or_borrow_parent_backtest():
    engine = object.__new__(SelfHealingEvolutionEngine)
    adapter = Mock()
    adapter.backtest_start_job.return_value = {"result": {"win_rate": .9, "sharpe_ratio": 3}}
    for client in (None, adapter):
        engine._bitpro_adapter = client
        result = engine._validate_offspring("333", "cta", {"fast_window": 8})
        assert result["validation_passed"] is False
        assert "win_rate" not in result
    adapter.backtest_start_job.assert_not_called()


def test_summary_metrics_are_not_execution_attribution():
    report = generate_7d_attribution_report(
        strategy_name="test", strategy_type="cta", parameters={},
        metrics={"win_rate": .8, "simulated_trades": 40}, strategy_id=333,
    )
    assert report["causal_conclusion"] == "not_established"
    assert all(
        d["state"] == "unknown" and d["metrics"] == {}
        for d in report["dimensions"].values()
    )


def test_incomplete_scan_never_mutates_registry_or_claims_candidate(monkeypatch):
    heal = Mock(side_effect=AssertionError("must not manufacture evidence during scan"))
    monkeypatch.setattr(SelfHealingEvolutionEngine, "heal_bitpro_strategy", heal)
    assert _heal_bitpro_fallback(333, {"strategy_id": 333}, Mock()) is None
    heal.assert_not_called()
