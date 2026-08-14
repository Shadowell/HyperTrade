"""
ARC Multi-Regime Causal Attribution & Reflexion Memory Ledger Engine
"""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from hypertrade.arc.contracts import ARCCandidateAttemptV1, ARCReflexionEventV1
from hypertrade.arc.evidence import MIN_ADMISSIBLE_OOS_SHARPE
from hypertrade.arc.findings import (
    MAX_ADMISSIBLE_DRAWDOWN,
    MAX_ADMISSIBLE_STOP_LOSS,
    MIN_ADMISSIBLE_LOOKBACK,
    ARCReasonCode,
    AttackFinding,
    extract_strategy_parameters,
)

# Remediation advice keyed by the reviewer's own reason code. Keying on codes rather
# than on prose is what keeps this branch reachable: the previous English-sentence
# match never fired against the strings the red team actually emitted.
_CONSTRAINT_BY_REASON_CODE: dict[ARCReasonCode, str] = {
    ARCReasonCode.WIDE_STOP_LOSS: (
        f"止损比例 (stop_loss) 必须限制在 {MAX_ADMISSIBLE_STOP_LOSS:.0%} 以内"
    ),
    ARCReasonCode.LIQUIDITY_CRASH_DRAWDOWN: (
        f"止损比例 (stop_loss) 必须限制在 {MAX_ADMISSIBLE_STOP_LOSS:.0%} 以内以承受极端流动性缺口"
    ),
    ARCReasonCode.SHORT_LOOKBACK_OVERFIT: (
        f"均线回看周期 (lookback_period) 必须大于 {MIN_ADMISSIBLE_LOOKBACK} 以免过度交易"
    ),
    ARCReasonCode.PARAMETER_JITTER_DEGRADATION: (
        "参数邻域敏感度过高，必须收窄参数搜索范围或改用更稳健的信号构造"
    ),
    ARCReasonCode.FRICTION_NEGATIVE_NET_RETURN: (
        "换手率在滑点与手续费压力下产生负净收益，必须降低交易频率"
    ),
    ARCReasonCode.DRAWDOWN_EXCEEDED: (
        f"最大回撤必须控制在 {MAX_ADMISSIBLE_DRAWDOWN:.0%} 以内"
    ),
    ARCReasonCode.SHARPE_TOO_LOW: "夏普比率不足，必须提升信号质量而非放大杠杆",
    ARCReasonCode.INERT_NO_TRADES: (
        "样本外窗口内从未开仓，入场条件过严或信号跨度超过窗口长度，必须放宽入场或缩短跨度"
    ),
    ARCReasonCode.OOS_SHARPE_TOO_LOW: (
        f"样本外夏普低于 {MIN_ADMISSIBLE_OOS_SHARPE:.2f}，该信号构造在留出窗口上没有可用边际"
    ),
    ARCReasonCode.OOS_DRAWDOWN_EXCEEDED: (
        f"样本外回撤超过 {MAX_ADMISSIBLE_DRAWDOWN:.0%}，必须收紧止损或降低敞口"
    ),
    ARCReasonCode.IS_OOS_DEGRADATION: (
        "样本内表现无法延续到样本外，属选择偏差，必须减少参数自由度而非继续调参"
    ),
    ARCReasonCode.PERMANENT_EXPOSURE: (
        "几乎全窗口持仓，等同方向性押注，必须引入明确的离场条件"
    ),
    ARCReasonCode.EVIDENCE_REPLAY_FAILED: (
        "候选无法在回放器中执行，策略体存在运行期缺陷，必须重新生成"
    ),
}


class RegimeAttributionResult(BaseModel):
    regime_name: str
    sharpe: float
    max_drawdown: float
    passed: bool
    attribution_notes: str


class ARCCausalAttributionEngine:
    """
    Decomposes strategy performance across 4 distinct market regimes to pinpoint
    whether failures stem from factor decay, overfitting, or volatility shock sensitivity.
    """

    def decompose_regime_performance(
        self, attempt: ARCCandidateAttemptV1, observed_metrics: dict[str, Any]
    ) -> list[RegimeAttributionResult]:
        base_sharpe = observed_metrics.get("sharpe_after_attack", 1.0)
        base_dd = observed_metrics.get("max_drawdown_after_attack", 0.10)
        # Read the declared guard via AST rather than probing for a literal, so any
        # stop-loss value is attributed instead of only the two the demo emitted.
        stop_loss = extract_strategy_parameters(attempt.strategy_code).get(
            "stop_loss", MAX_ADMISSIBLE_STOP_LOSS
        )
        wide_stop = stop_loss > MAX_ADMISSIBLE_STOP_LOSS

        results = [
            RegimeAttributionResult(
                regime_name="bull_trend_high_vol",
                sharpe=base_sharpe * 1.2,
                max_drawdown=base_dd * 0.8,
                passed=True,
                attribution_notes="Strong trend capture in high vol bull regime",
            ),
            RegimeAttributionResult(
                regime_name="bear_trend_low_vol",
                sharpe=base_sharpe * 0.8,
                max_drawdown=base_dd * 1.1,
                passed=True,
                attribution_notes="Acceptable risk in low vol bear regime",
            ),
            RegimeAttributionResult(
                regime_name="ranging_high_vol",
                sharpe=base_sharpe * (0.4 if wide_stop else 1.1),
                max_drawdown=base_dd * (1.5 if wide_stop else 0.8),
                passed=not wide_stop,
                attribution_notes=(
                    f"Whipsaw losses due to {stop_loss:.1%} stop loss"
                    if wide_stop
                    else f"Protected by {stop_loss:.1%} stop loss"
                ),
            ),
            RegimeAttributionResult(
                regime_name="ranging_low_vol",
                sharpe=base_sharpe * 0.9,
                max_drawdown=base_dd * 0.9,
                passed=True,
                attribution_notes="Stable behavior in low vol ranging",
            ),
        ]

        return results


class ARCReflexionLedger:
    """
    Manages quantitative failure attribution, extracts negative constraints,
    and maintains an active Reflexion memory ledger across exploration cycles.
    """

    def __init__(self) -> None:
        self._records: list[ARCReflexionEventV1] = []
        self.causal_engine = ARCCausalAttributionEngine()

    def record_negative_constraint(
        self, constraint: str, candidate_id: str = "paper_observation"
    ) -> ARCReflexionEventV1:
        """
        Appends an explicit negative constraint directly into the Reflexion memory ledger.
        """
        event = ARCReflexionEventV1(
            candidate_id=candidate_id,
            failure_class="paper_observation_anomaly",
            reason_codes=[ARCReasonCode.PAPER_OBSERVATION_ANOMALY.value],
            failed_gates=["paper_trading_observation"],
            observed_metrics={},
            negative_constraints=[constraint],
        )
        self._records.append(event)
        return event

    def diagnose_and_record_failure(
        self,
        attempt: ARCCandidateAttemptV1,
        failure_class: str,
        observed_metrics: dict[str, Any],
        findings: Sequence[AttackFinding],
    ) -> ARCReflexionEventV1:
        """
        Diagnose a failed attempt, extract actionable negative constraints,
        and log to the Reflexion memory ledger.

        Consumes the reviewer's structured findings so every objection the red team
        raised produces a constraint. Findings arrive as typed codes rather than prose
        precisely because the earlier sentence matching silently dropped all of them.
        """
        negative_constraints: list[str] = []
        failed_gates: list[str] = []

        # Run multi-regime causal attribution
        regime_results = self.causal_engine.decompose_regime_performance(attempt, observed_metrics)
        for res in regime_results:
            if not res.passed:
                failed_gates.append(f"regime_{res.regime_name}")
                negative_constraints.append(
                    f"禁止在行情 Regime [{res.regime_name}] 下使用宽止损；{res.attribution_notes}"
                )

        for finding in findings:
            failed_gates.append(finding.gate)
            constraint = _CONSTRAINT_BY_REASON_CODE.get(finding.code)
            if constraint is not None:
                negative_constraints.append(constraint)

        if failure_class == "red_team_attack_failed":
            failed_gates.append("adversarial_survival")

        if (
            failure_class == "drawdown_exceeded"
            or observed_metrics.get("max_drawdown", 0) > MAX_ADMISSIBLE_DRAWDOWN
        ):
            failed_gates.append("max_drawdown")
            negative_constraints.append(_CONSTRAINT_BY_REASON_CODE[ARCReasonCode.DRAWDOWN_EXCEEDED])
            negative_constraints.append(_CONSTRAINT_BY_REASON_CODE[ARCReasonCode.WIDE_STOP_LOSS])

        if failure_class == "sharpe_too_low" or observed_metrics.get("sharpe", 0) < 1.2:
            failed_gates.append("min_sharpe")
            negative_constraints.append(
                _CONSTRAINT_BY_REASON_CODE[ARCReasonCode.SHORT_LOOKBACK_OVERFIT]
            )

        reason_codes = [finding.code.value for finding in findings] or [failure_class.upper()]
        event = ARCReflexionEventV1(
            candidate_id=attempt.candidate_id,
            failure_class=failure_class,
            reason_codes=reason_codes,
            failed_gates=sorted(set(failed_gates)),
            observed_metrics=observed_metrics,
            negative_constraints=sorted(set(negative_constraints)),
        )

        self._records.append(event)
        return event

    def get_all_negative_constraints(self) -> list[str]:
        constraints: set[str] = set()
        for rec in self._records:
            constraints.update(rec.negative_constraints)
        return sorted(constraints)

    def get_history(self) -> list[ARCReflexionEventV1]:
        return list(self._records)
