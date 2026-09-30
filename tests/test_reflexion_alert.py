from typing import Any

from hypertrade.arc.reflexion_alert import (
    ReflexionAlertPayload,
    WebhookRejected,
    build_feishu_card_payload,
    build_feishu_text_payload,
    dispatch_reflexion_alert,
)


def test_build_feishu_card_payload() -> None:
    alert = ReflexionAlertPayload(
        strategy_id="101",
        strategy_name="RSI超买超卖反转策略",
        strategy_family="rsi_reversal",
        symbol="ETH-USDT-SWAP",
        timeframe="1H",
        failure_class="MAX_DRAWDOWN_BREACH",
        severity="critical",
        observed_metrics={"max_drawdown": 0.125, "win_rate": 0.38, "consecutive_losses": 4},
        regime_attribution=[
            {
                "regime_name": "ranging_high_vol",
                "passed": False,
                "attribution_notes": "高波动震荡市频繁打止损",
            },
            {
                "regime_name": "bull_trend_high_vol",
                "passed": True,
                "attribution_notes": "多头高波趋势稳健",
            },
        ],
        negative_constraints=[
            "止损比例必须限制在 5% 以内以承受极端流动性缺口",
            "RSI 超卖阈值必须 <= 20 以防震荡市过早抄底",
        ],
        evolution_action="已启动第 2 代 MCTS 变异重训，剪枝参数解空间",
    )

    payload = build_feishu_card_payload(alert, console_url="https://test.console")
    assert payload["msg_type"] == "interactive"
    card = payload["card"]
    assert card["header"]["template"] == "red"
    assert "RSI超买超卖反转策略" in card["header"]["title"]["content"]

    elements = card["elements"]
    assert len(elements) >= 5

    # Check fields block
    fields = elements[0]["fields"]
    assert any("ETH-USDT-SWAP" in f["text"]["content"] for f in fields)
    assert any("最大回撤突破阈值" in f["text"]["content"] for f in fields)
    assert any("12.5%" in f["text"]["content"] for f in fields)

    # Check attribution
    assert any("ranging_high_vol" in str(e) for e in elements)
    # Check negative constraints
    assert any("止损比例必须限制在 5% 以内" in str(e) for e in elements)


def test_build_feishu_text_payload() -> None:
    alert = ReflexionAlertPayload(
        strategy_name="EMA/MACD趋势跟踪",
        symbol="BTC-USDT-SWAP",
        timeframe="4H",
        failure_class="LOSS_STREAK",
        severity="warning",
        observed_metrics={"consecutive_losses": 5},
        negative_constraints=["触发建仓必须叠加 ATR 波动率确认信号"],
    )
    text_payload = build_feishu_text_payload(alert)
    assert text_payload["msg_type"] == "text"
    text = text_payload["content"]["text"]
    assert "BTC-USDT-SWAP" in text
    assert "触发建仓必须叠加 ATR" in text


def test_dispatch_reflexion_alert_no_webhook(monkeypatch: Any) -> None:
    from hypertrade.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "feishu_webhook_url", "")

    alert = ReflexionAlertPayload()
    delivered, status = dispatch_reflexion_alert(alert)
    assert not delivered
    assert status == "skipped_no_webhook"


def test_dispatch_reflexion_alert_success() -> None:
    sent_payloads: list[dict[str, Any]] = []

    def mock_post(url: str, payload: dict[str, Any]) -> None:
        sent_payloads.append(payload)

    alert = ReflexionAlertPayload(
        strategy_name="RSI反转策略",
        symbol="ETH-USDT-SWAP",
        failure_class="MAX_DRAWDOWN_BREACH",
    )

    delivered, status = dispatch_reflexion_alert(
        alert, webhook_url="https://feishu.example/hook", post=mock_post
    )
    assert delivered
    assert status == "sent_interactive_card"
    assert len(sent_payloads) == 1
    assert sent_payloads[0]["msg_type"] == "interactive"


def test_dispatch_reflexion_alert_fallback_to_text() -> None:
    sent_payloads: list[dict[str, Any]] = []

    def mock_post(url: str, payload: dict[str, Any]) -> None:
        sent_payloads.append(payload)
        if payload["msg_type"] == "interactive":
            raise WebhookRejected("card_not_supported")
        # Text succeeds

    alert = ReflexionAlertPayload(
        strategy_name="RSI反转策略",
        symbol="ETH-USDT-SWAP",
        failure_class="WIN_RATE_DECAY",
    )

    delivered, status = dispatch_reflexion_alert(
        alert, webhook_url="https://feishu.example/hook", post=mock_post
    )
    assert delivered
    assert status == "sent_fallback_text"
    assert len(sent_payloads) == 2
    assert sent_payloads[0]["msg_type"] == "interactive"
    assert sent_payloads[1]["msg_type"] == "text"


def test_dispatch_reflexion_alert_network_failure() -> None:
    def mock_failing_post(url: str, payload: dict[str, Any]) -> None:
        raise ConnectionResetError("Connection reset by peer")

    alert = ReflexionAlertPayload()
    delivered, status = dispatch_reflexion_alert(
        alert, webhook_url="https://feishu.example/hook", post=mock_failing_post
    )
    assert not delivered
    assert "failed:ConnectionResetError" in status
