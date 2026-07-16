"""Deterministic ingress safety classification for governed Mission requests.

This is deliberately narrow: it prevents an obvious order/approval request from
being mistaken for a read-only research task before any planner or provider can
propose a capability. It never grants execution authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

SafetyDisposition = Literal["normal", "blocked", "needs_review", "needs_data"]


@dataclass(frozen=True)
class ObjectiveSafety:
    disposition: SafetyDisposition = "normal"
    reason: str = ""
    unknowns: tuple[str, ...] = ()


_EXECUTION_TERMS = (
    "下单",
    "买入",
    "卖出",
    "开仓",
    "平仓",
    "执行",
    "启动",
    "停止",
    "调仓",
    "分配",
    "rebalance",
    "order",
    "buy",
    "sell",
)
_MAINNET_TERMS = ("主网", "实盘", "mainnet", "live")
_APPROVAL_TERMS = ("未批准", "待批准", "批准", "approval", "approve")
_STALE_TERMS = ("过期", "stale", "timeout", "超时")
_IN_SAMPLE_TERMS = ("样本内", "in-sample", "insample")
_OOS_TERMS = ("样本外", "oos", "out-of-sample", "out of sample")
_CONFLICT_TERMS = ("冲突", "矛盾", "不一致", "conflict", "diverge")
_SECRET_TERMS = ("私钥", "api token", "api_key", "token", "密钥")
_GUARANTEE_TERMS = ("稳赚", "保证收益", "保证盈利")


def classify_objective_safety(objective: str) -> ObjectiveSafety:
    """Return a conservative, auditable disposition for a user objective."""

    lowered = objective.casefold()
    if any(term in lowered for term in _SECRET_TERMS):
        return ObjectiveSafety(
            disposition="blocked",
            reason="secret_disclosure_request_blocked",
            unknowns=("不能显示凭证、Token 或私钥。",),
        )
    if any(term in lowered for term in _GUARANTEE_TERMS):
        return ObjectiveSafety(
            disposition="needs_data",
            reason="guaranteed_return_request_rejected",
            unknowns=("不存在可验证的无风险盈利策略。",),
        )
    execution_requested = any(term in lowered for term in _EXECUTION_TERMS)
    if execution_requested and any(term in lowered for term in _MAINNET_TERMS):
        return ObjectiveSafety(
            disposition="blocked",
            reason="mainnet_execution_request_blocked",
            unknowns=("主网执行不属于只读研究权限，未创建任何订单。",),
        )
    if execution_requested and any(
        term in lowered for term in ("策略", "资金", "权重", "仓位", "风险")
    ):
        return ObjectiveSafety(
            disposition="blocked",
            reason="governed_mutation_request_blocked",
            unknowns=("策略启停、资金分配和调仓不属于只读研究权限，未执行任何变更。",),
        )
    if execution_requested and (
        any(term in lowered for term in _APPROVAL_TERMS)
        or "testnet" in lowered
        or "测试网" in lowered
    ):
        return ObjectiveSafety(
            disposition="needs_review",
            reason="approval_gated_execution_request",
            unknowns=("交易意图需要独立的人工批准和风险复核。",),
        )
    if _has_excessive_leverage(lowered):
        return ObjectiveSafety(
            disposition="needs_review",
            reason="leverage_requires_risk_review",
            unknowns=("杠杆和仓位风险尚未通过独立风险复核。",),
        )
    if any(term in lowered for term in _STALE_TERMS):
        return ObjectiveSafety(
            disposition="needs_data",
            reason="source_freshness_not_verified",
            unknowns=("请求依赖的数据新鲜度未被验证。",),
        )
    return ObjectiveSafety()


def _has_excessive_leverage(value: str) -> bool:
    for match in re.finditer(r"(?<!\d)(\d{1,4})\s*(?:倍|x)(?![a-z])", value):
        if int(match.group(1)) >= 20:
            return True
    return False


def requires_evidence_review(objective: str) -> bool:
    """Identify a strategy-evidence conflict without blocking read-only research.

    Unlike an order approval, a conflict between in-sample and out-of-sample
    results still benefits from governed reads. The public answer must retain
    that evidence but cannot present a promotion or risk-change conclusion.
    """

    lowered = objective.casefold()
    return (
        any(term in lowered for term in _IN_SAMPLE_TERMS)
        and any(term in lowered for term in _OOS_TERMS)
        and any(term in lowered for term in _CONFLICT_TERMS)
    )
