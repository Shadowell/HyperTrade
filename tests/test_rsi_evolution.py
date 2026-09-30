from typing import Any

from hypertrade.research.rsi_evolution import RsiEvolutionEngine


def test_create_initial_rsi_candidate() -> None:
    engine = RsiEvolutionEngine()
    cand = engine.create_initial_rsi_candidate(symbol="ETH-USDT-SWAP", timeframe="1H")
    assert cand is not None
    assert "ETH-USDT-SWAP" in cand.hypothesis
    assert "class" in cand.strategy_code
    assert "_rsi" in cand.strategy_code
    assert cand.strategy_spec.get("family") == "rsi_reversal"


def test_evaluate_and_diagnose() -> None:
    engine = RsiEvolutionEngine()
    cand = engine.create_initial_rsi_candidate(symbol="BTC-USDT-SWAP", timeframe="1H")
    metrics, findings, regime_results = engine.evaluate_and_diagnose(
        cand, simulated_drawdown=0.15, simulated_consecutive_losses=4
    )

    assert metrics["max_drawdown"] == 0.15
    assert len(findings) >= 2
    assert any("DRAWDOWN_EXCEEDED" in str(f.code) for f in findings)
    assert len(regime_results) == 4


def test_run_full_cycle_with_mock_feishu() -> None:
    delivered_payloads: list[dict[str, Any]] = []

    def mock_poster(url: str, payload: dict[str, Any]) -> None:
        delivered_payloads.append(payload)

    engine = RsiEvolutionEngine(poster=mock_poster)
    result = engine.run_full_cycle(
        symbol="ETH-USDT-SWAP",
        timeframe="1H",
        webhook_url="https://feishu.example/test-hook",
        dispatch_alert=True,
    )

    assert result.status == "completed"
    assert result.symbol == "ETH-USDT-SWAP"
    assert result.initial_candidate_id != ""
    assert len(result.negative_constraints) > 0
    assert result.mutated_candidate_id is not None
    assert result.alert_delivered is True
    assert result.alert_status == "sent_interactive_card"
    assert len(delivered_payloads) == 1
    assert delivered_payloads[0]["msg_type"] == "interactive"
    card = delivered_payloads[0]["card"]
    assert "RSI超买超卖反转策略" in card["header"]["title"]["content"]
    assert "ETH-USDT-SWAP" in str(card["elements"])
