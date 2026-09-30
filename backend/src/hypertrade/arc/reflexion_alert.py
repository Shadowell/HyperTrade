"""
HyperTrade Reflexion Trading Closed-Loop Alerting & Feishu Card Dispatcher.

Surfaces trading failure causal attribution, negative constraint extraction,
and next-generation autonomous strategy mutations to operators via Feishu interactive cards.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

TEXT_LIMIT = 3900
DELIVERY_RECEIPT_VERSION = "feishu_reflexion_card.v1"

Poster = Callable[[str, dict[str, Any]], None]


class WebhookRejected(RuntimeError):
    """Raised when Feishu webhook rejects the message receipt."""


class ReflexionAlertPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    alert_id: str = Field(default_factory=lambda: f"ref_alt_{uuid4().hex[:8]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    strategy_id: str | int | None = None
    strategy_name: str = "RSI反转策略"
    strategy_family: str = "rsi_reversal"
    symbol: str = "ETH-USDT-SWAP"
    timeframe: str = "1H"
    failure_class: str = "MAX_DRAWDOWN_BREACH"
    severity: str = "warning"  # info | warning | critical
    # Trigger source: paper_observation | adversarial_attack | backtest_matrix
    trigger_source: str = "paper_observation"
    observed_metrics: dict[str, Any] = Field(default_factory=dict)
    regime_attribution: list[dict[str, Any]] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    evolution_action: str = (
        "已自动将负向约束沉淀入 Reflexion Memory Ledger，启动下一代参数与 AST 变异重训"
    )
    candidate_id: str | None = None
    next_candidate_id: str | None = None


_SEVERITY_COLOR = {
    "info": "blue",
    "warning": "orange",
    "critical": "red",
}

_SEVERITY_LABEL = {
    "info": "一般提示 (INFO)",
    "warning": "风险警示 (WARNING)",
    "critical": "严重阻断 (CRITICAL)",
}

_FAILURE_LABEL = {
    "MAX_DRAWDOWN_BREACH": "最大回撤突破阈值",
    "WIN_RATE_DECAY": "胜率显著衰退",
    "LOSS_STREAK": "出现异常连续亏损",
    "SLIPPAGE_SURGE": "市场执行滑点激增",
    "RED_TEAM_ATTACK_FAILED": "红队对抗压力测试未通过",
    "PARAMETER_JITTER_DEGRADATION": "参数邻域脆弱 (刀锋过拟合)",
    "FRICTION_NEGATIVE_NET_RETURN": "手续费滑点吞噬收益",
    "OOS_SHARPE_TOO_LOW": "样本外夏普比率过低",
}


def _format_metrics_summary(metrics: dict[str, Any]) -> str:
    parts = []
    if "max_drawdown" in metrics:
        dd = float(metrics["max_drawdown"])
        parts.append(f"最大回撤: {dd:.1%}")
    if "current_drawdown_pct" in metrics:
        dd = float(metrics["current_drawdown_pct"])
        parts.append(f"当前回撤: {dd:.1%}")
    if "win_rate" in metrics:
        wr = float(metrics["win_rate"])
        parts.append(f"胜率: {wr:.1%}")
    if "win_rate_30d" in metrics:
        wr = float(metrics["win_rate_30d"])
        parts.append(f"30日胜率: {wr:.1%}")
    if "consecutive_losses" in metrics:
        parts.append(f"连亏笔数: {metrics['consecutive_losses']}")
    if "sharpe" in metrics:
        sp = float(metrics["sharpe"])
        parts.append(f"夏普比率: {sp:.2f}")
    if "avg_slippage_bps" in metrics:
        parts.append(f"平均滑点: {metrics['avg_slippage_bps']} bps")
    return " | ".join(parts) if parts else "暂无细分指标"


def build_feishu_card_payload(
    alert: ReflexionAlertPayload,
    console_url: str = "https://bitpro.notenap.com",
) -> dict[str, Any]:
    """
    Builds a structured Feishu Interactive Message Card v2.
    """
    color = _SEVERITY_COLOR.get(alert.severity.lower(), "orange")
    severity_text = _SEVERITY_LABEL.get(alert.severity.lower(), alert.severity.upper())
    failure_label = _FAILURE_LABEL.get(alert.failure_class, alert.failure_class)

    header_title = f"🚨 [HyperTrade 交易反思闭环] {alert.strategy_name} - 触发负向约束提炼"
    if alert.severity.lower() == "info":
        header_title = f"ℹ️ [HyperTrade 交易反思] {alert.strategy_name} - 提炼负向约束"

    # Multi-regime attribution block
    regime_lines = []
    if alert.regime_attribution:
        for r in alert.regime_attribution[:4]:
            r_name = r.get("regime_name", "unknown")
            r_notes = r.get("attribution_notes", "")
            r_passed = "✓ 稳健" if r.get("passed") else "✗ 失效"
            regime_lines.append(f"• **`{r_name}`** [{r_passed}]: {r_notes}")
    regime_text = "\n".join(regime_lines) if regime_lines else "暂无宏观状态分解记录"

    # Negative constraints list
    constraint_lines = []
    for idx, c in enumerate(alert.negative_constraints, 1):
        constraint_lines.append(f"{idx}. {c}")
    constraints_text = (
        "\n".join(constraint_lines) if constraint_lines else "（未生成新的显式禁止规则）"
    )

    metrics_text = _format_metrics_summary(alert.observed_metrics)

    strategy_link = f"{console_url}/ai-lab?tab=evolution"
    if alert.strategy_id is not None:
        strategy_link = f"{console_url}/live?mode=paper&strategyId={alert.strategy_id}"

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title[:100]},
            "template": color,
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**🎯 策略标的**\n`{alert.symbol}` ({alert.timeframe})",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**⚠️ 异常分类**\n{failure_label}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**📊 触发指标**\n{metrics_text}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**⚡ 告警等级**\n{severity_text}",
                        },
                    },
                ],
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**🔍 多宏观状态因果归因 (Causal Attribution)**:\n{regime_text}",
                },
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**💡 提炼负向约束 (Reflexion Memory)**:\n{constraints_text}",
                },
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**🚀 自主进化动作 (Next Evolution Action)**:\n{alert.evolution_action}"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"🔗 [查看策略监控与进化进度]({strategy_link})",
                },
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": (
                            f"HyperTrade Reflexion Engine • "
                            f"{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                        ),
                    }
                ],
            },
        ],
    }

    return {"msg_type": "interactive", "card": card}


def build_feishu_text_payload(
    alert: ReflexionAlertPayload,
    console_url: str = "https://bitpro.notenap.com",
) -> dict[str, Any]:
    """
    Fallback plain text formatter for webhooks that don't support interactive cards.
    """
    failure_label = _FAILURE_LABEL.get(alert.failure_class, alert.failure_class)
    lines = [
        f"🚨 [HyperTrade 交易反思闭环] {alert.strategy_name}",
        f"标的/周期: {alert.symbol} ({alert.timeframe})",
        f"异常分类: {failure_label}",
        f"触发绩效: {_format_metrics_summary(alert.observed_metrics)}",
        "---",
        "🔍 因果归因:",
    ]
    if alert.regime_attribution:
        for r in alert.regime_attribution[:3]:
            lines.append(f"• {r.get('regime_name')}: {r.get('attribution_notes')}")
    else:
        lines.append("• 暂无宏观状态分解")

    lines.append("💡 提炼负向约束:")
    if alert.negative_constraints:
        for idx, c in enumerate(alert.negative_constraints, 1):
            lines.append(f"{idx}. {c}")
    else:
        lines.append("• （未生成显式禁止规则）")

    lines.append("🚀 自主进化动作:")
    lines.append(f"{alert.evolution_action}")
    lines.append(f"控制台: {console_url}/ai-lab?tab=evolution")

    body = "\n".join(lines)
    return {"msg_type": "text", "content": {"text": body[:TEXT_LIMIT]}}


def _default_post(url: str, payload: dict[str, Any]) -> None:
    import httpx

    response = httpx.post(url, json=payload, timeout=10)
    response.raise_for_status()
    try:
        body = response.json()
    except ValueError as exc:
        raise WebhookRejected("invalid_receipt_json") from exc
    if not isinstance(body, dict):
        raise WebhookRejected("invalid_receipt_body")
    codes = [body[key] for key in ("code", "StatusCode") if key in body]
    if not codes or any(type(code) is not int for code in codes):
        raise WebhookRejected("missing_receipt_code")
    rejected = next((code for code in codes if code != 0), None)
    if rejected is not None:
        raise WebhookRejected(f"feishu_rejected_code_{rejected}")


def dispatch_reflexion_alert(
    alert: ReflexionAlertPayload,
    *,
    webhook_url: str | None = None,
    post: Poster | None = None,
) -> tuple[bool, str]:
    """
    Dispatches a Reflexion alert card to the configured Feishu webhook.
    Returns (delivered: bool, status_message: str).
    Never raises an exception — failure is recorded and logged gracefully.
    """
    from hypertrade.config import get_settings

    settings = get_settings()
    url = (webhook_url or getattr(settings, "feishu_webhook_url", "") or "").strip()
    if not url:
        logger.info(
            "Feishu webhook not configured; skipping reflexion alert delivery: %s", alert.alert_id
        )
        return False, "skipped_no_webhook"

    console_url = str(
        getattr(settings, "bitpro_console_url", "") or "https://bitpro.notenap.com"
    ).strip()
    card_payload = build_feishu_card_payload(alert, console_url=console_url)
    sender = post or _default_post

    try:
        sender(url, card_payload)
        logger.info(
            "Successfully dispatched Reflexion Feishu card for alert %s", alert.alert_id
        )
        return True, "sent_interactive_card"
    except WebhookRejected as exc:
        logger.warning(
            "Feishu interactive card rejected (%s); attempting fallback to text payload", exc
        )
        # Attempt fallback to text payload
        try:
            text_payload = build_feishu_text_payload(alert, console_url=console_url)
            sender(url, text_payload)
            logger.info(
                "Successfully dispatched Reflexion fallback text for alert %s", alert.alert_id
            )
            return True, "sent_fallback_text"
        except Exception as fb_exc:
            logger.error("Feishu fallback text delivery failed: %s", fb_exc)
            return False, f"failed_fallback:{fb_exc}"
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to dispatch Reflexion Feishu alert %s: %s", alert.alert_id, exc)
        return False, f"failed:{type(exc).__name__}"
