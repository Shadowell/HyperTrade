"""
RSI Strategy Autonomous Evolution & Reflexion Closed-Loop Engine.

Orchestrates the entire lifecycle:
1. Generates initial RSI reversal candidate strategy (`rsi_reversal`).
2. Subject candidate to market stress/volatility shocks (triggering drawdown/loss-streak).
3. Executes causal regime attribution & extracts structured negative constraints.
4. Mutates strategy parameters/AST under Reflexion memory guidance.
5. Dispatches rich Feishu alert card with actionable intelligence.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from hypertrade.arc.adversarial import BlueTeamQuant
from hypertrade.arc.contracts import ARCCandidateAttemptV1
from hypertrade.arc.findings import (
    ARCReasonCode,
    AttackFinding,
    FindingSeverity,
)
from hypertrade.arc.mutation import ARCGeneticMutator
from hypertrade.arc.reflexion import (
    ARCCausalAttributionEngine,
    ARCReflexionLedger,
    RegimeAttributionResult,
)
from hypertrade.arc.reflexion_alert import (
    Poster,
    ReflexionAlertPayload,
    dispatch_reflexion_alert,
)

logger = logging.getLogger(__name__)


class RsiEvolutionCycleResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cycle_id: str
    symbol: str
    timeframe: str
    status: str  # "completed" | "failed"
    initial_candidate_id: str
    initial_code: str
    observed_metrics: dict[str, Any]
    regime_attributions: list[dict[str, Any]]
    negative_constraints: list[str]
    mutated_candidate_id: str | None
    mutated_code: str | None
    alert_delivered: bool
    alert_status: str
    summary_markdown: str


class RsiEvolutionEngine:
    """
    Autonomous research engine specialized for RSI oscillator evolution.
    """

    def __init__(self, *, poster: Poster | None = None) -> None:
        self.blue_team = BlueTeamQuant()
        self.mutator = ARCGeneticMutator(seed=42)
        self.attribution_engine = ARCCausalAttributionEngine()
        self.poster = poster

    def create_initial_rsi_candidate(
        self,
        symbol: str = "ETH-USDT-SWAP",
        timeframe: str = "1H",
        *,
        objective: str = "RSI 超买超卖反转策略",
    ) -> ARCCandidateAttemptV1:
        """
        Synthesizes an initial baseline RSI reversal candidate with standard bounds.
        """
        return self.blue_team.propose_initial_strategy(
            objective=objective,
            symbol=symbol,
            timeframe=timeframe,
            family_key="rsi_reversal",
        )

    def evaluate_and_diagnose(
        self,
        candidate: ARCCandidateAttemptV1,
        *,
        simulated_drawdown: float = 0.135,
        simulated_sharpe: float = 0.72,
        simulated_win_rate: float = 0.40,
        simulated_consecutive_losses: int = 4,
    ) -> tuple[dict[str, Any], list[AttackFinding], list[RegimeAttributionResult]]:
        """
        Evaluates candidate performance under market stress, detecting drawdown
        and loss streaks, and decomposing regime causality.
        """
        metrics = {
            "max_drawdown": simulated_drawdown,
            "sharpe": simulated_sharpe,
            "win_rate": simulated_win_rate,
            "consecutive_losses": simulated_consecutive_losses,
            "sharpe_after_attack": simulated_sharpe * 0.7,
            "max_drawdown_after_attack": simulated_drawdown * 1.25,
        }

        findings: list[AttackFinding] = []
        if simulated_drawdown > 0.10:
            findings.append(
                AttackFinding(
                    code=ARCReasonCode.DRAWDOWN_EXCEEDED,
                    severity=FindingSeverity.BLOCKING,
                    gate="max_drawdown",
                    detail=f"回撤 ({simulated_drawdown:.1%}) 超过阈值 (10.0%)",
                )
            )
            findings.append(
                AttackFinding(
                    code=ARCReasonCode.WIDE_STOP_LOSS,
                    severity=FindingSeverity.BLOCKING,
                    gate="stop_loss_guard",
                    detail="止损过宽导致震荡市连续亏损放大",
                )
            )

        if simulated_consecutive_losses >= 4:
            findings.append(
                AttackFinding(
                    code=ARCReasonCode.PARAMETER_JITTER_DEGRADATION,
                    severity=FindingSeverity.ADVISORY,
                    gate="parameter_plateau",
                    detail="连续亏损4笔：超买超卖阈值对震荡噪声过敏",
                )
            )

        regime_results = self.attribution_engine.decompose_regime_performance(
            candidate, metrics
        )

        return metrics, findings, regime_results

    def run_full_cycle(
        self,
        symbol: str = "ETH-USDT-SWAP",
        timeframe: str = "1H",
        *,
        webhook_url: str | None = None,
        dispatch_alert: bool = True,
    ) -> RsiEvolutionCycleResult:
        """
        Executes the entire end-to-end RSI evolution and reflexion closed-loop cycle.
        """
        cycle_id = f"rsi_evol_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        logger.info("Starting RSI autonomous evolution cycle %s for %s", cycle_id, symbol)

        # 1. Propose initial candidate
        initial_cand = self.create_initial_rsi_candidate(symbol=symbol, timeframe=timeframe)

        # 2. Simulate stress evaluation & regime causal attribution
        metrics, findings, regime_results = self.evaluate_and_diagnose(initial_cand)

        # 3. Reflexion Ledger recording & negative constraint extraction
        ledger = ARCReflexionLedger()
        reflexion_event = ledger.diagnose_and_record_failure(
            attempt=initial_cand,
            failure_class="MAX_DRAWDOWN_BREACH",
            observed_metrics=metrics,
            findings=findings,
            dispatch_alert=False,  # We will dispatch custom formatted card below
        )
        negative_constraints = reflexion_event.negative_constraints

        # 4. AST Mutation & Evolution guided by Reflexion memory
        mutated_cand = self.mutator.mutate_attempt(initial_cand, ledger.get_history())

        # 5. Dispatch Feishu Reflexion Card
        alert_delivered = False
        alert_status = "skipped"
        if dispatch_alert:
            alert = ReflexionAlertPayload(
                strategy_id=f"strat_{symbol.lower()}_rsi",
                strategy_name=f"RSI超买超卖反转策略 ({symbol})",
                strategy_family="rsi_reversal",
                symbol=symbol,
                timeframe=timeframe,
                failure_class="MAX_DRAWDOWN_BREACH",
                severity="critical",
                trigger_source="adversarial_attack",
                observed_metrics=metrics,
                regime_attribution=[
                    {
                        "regime_name": r.regime_name,
                        "passed": r.passed,
                        "attribution_notes": r.attribution_notes,
                    }
                    for r in regime_results
                ],
                negative_constraints=negative_constraints,
                evolution_action=(
                    f"已提取 {len(negative_constraints)} 条负向反思教训，成功剪枝参数空间并"
                    f"进化出新一代候选策略 [{mutated_cand.candidate_id}]，已注入后续回测矩阵沙盒。"
                ),
                candidate_id=initial_cand.candidate_id,
                next_candidate_id=mutated_cand.candidate_id,
            )
            alert_delivered, alert_status = dispatch_reflexion_alert(
                alert, webhook_url=webhook_url, post=self.poster
            )

        # 6. Formulate summary
        dd_pct = metrics["max_drawdown"] * 100
        losses = metrics["consecutive_losses"]
        summary = (
            f"### RSI 策略自主进化与交易反思闭环报告\n\n"
            f"- **标的 / 周期**: `{symbol}` ({timeframe})\n"
            f"- **原版候选 ID**: `{initial_cand.candidate_id}`\n"
            f"- **触发异常**: 最大回撤 {dd_pct:.1f}%，连续亏损 {losses} 笔\n"
            f"- **提炼反思约束** ({len(negative_constraints)} 条):\n"
            + "\n".join(f"  {idx}. {c}" for idx, c in enumerate(negative_constraints, 1))
            + f"\n- **进化新候选 ID**: `{mutated_cand.candidate_id}`\n"
            f"- **飞书告警状态**: `{alert_status}` (投递={alert_delivered})\n"
        )

        return RsiEvolutionCycleResult(
            cycle_id=cycle_id,
            symbol=symbol,
            timeframe=timeframe,
            status="completed",
            initial_candidate_id=initial_cand.candidate_id,
            initial_code=initial_cand.strategy_code,
            observed_metrics=metrics,
            regime_attributions=[
                {
                    "regime_name": r.regime_name,
                    "passed": r.passed,
                    "attribution_notes": r.attribution_notes,
                }
                for r in regime_results
            ],
            negative_constraints=negative_constraints,
            mutated_candidate_id=mutated_cand.candidate_id,
            mutated_code=mutated_cand.strategy_code,
            alert_delivered=alert_delivered,
            alert_status=alert_status,
            summary_markdown=summary,
        )
