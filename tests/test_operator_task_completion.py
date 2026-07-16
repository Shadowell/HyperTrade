from __future__ import annotations

from hypertrade.evals.task_completion import (
    OperatorTaskCompletionSuite,
    TaskCompletionObservation,
)
from hypertrade.runtime.domain.models import OperatorEvidenceV1, OperatorResponseV1


def test_task_completion_catalog_has_exactly_100_cross_domain_tasks() -> None:
    suite = OperatorTaskCompletionSuite()

    status = suite.catalog_status()

    assert status["status"] == "ready"
    assert status["case_count"] == 100
    assert status["multi_turn_count"] >= 10
    assert all(count >= 10 for count in status["cohorts"].values())


def test_task_completion_requires_requested_facts_not_only_a_safe_contract() -> None:
    suite = OperatorTaskCompletionSuite()
    case = next(item for item in suite.cases() if item.case_id == "m01_exact_eth")
    response = OperatorResponseV1(
        mission_id="mis_eval",
        outcome="completed",
        decision="已读取 ETH 合约行情。",
        confidence="medium",
        evidence=(
            OperatorEvidenceV1(
                summary="ETH-USDT-SWAP 最新价 3000。",
                source_refs=("hypertrade_db:market_tickers:ETH-USDT-SWAP",),
            ),
        ),
    )

    passed = suite.evaluate(
        case,
        TaskCompletionObservation(
            response=response,
            visible_text="## 结论\n已读取 ETH 合约行情。\n\nETH-USDT-SWAP 最新价 3000。",
            capability_ids=("market.summary",),
            source_refs=("hypertrade_db:market_tickers:ETH-USDT-SWAP",),
        ),
    )
    failed = suite.evaluate(
        case,
        TaskCompletionObservation(
            response=response,
            visible_text="## 结论\n已完成本次只读研究。",
            capability_ids=("market.summary",),
            source_refs=("hypertrade_db:market_tickers:ETH-USDT-SWAP",),
        ),
    )

    assert passed["status"] == "passed"
    assert failed["status"] == "failed"
    assert "requested_facts" in failed["failed_checks"]
    assert "R3" in failed["remediation_ids"]


def test_multiturn_task_requires_a_real_context_reference() -> None:
    suite = OperatorTaskCompletionSuite()
    case = next(item for item in suite.cases() if item.case_id == "c01_strategy_pronoun")
    response = OperatorResponseV1(
        mission_id="mis_context",
        outcome="completed",
        decision="已读取策略交易数据。",
        confidence="medium",
        evidence=(
            OperatorEvidenceV1(
                summary="momentum_breakout_v1 收益 2.1。",
                source_refs=("hypertrade_db:backtest_runs:196",),
            ),
        ),
    )

    result = suite.evaluate(
        case,
        TaskCompletionObservation(
            response=response,
            visible_text="## 结论\nmomentum_breakout_v1 收益 2.1。",
            capability_ids=("strategy.performance_summary",),
            source_refs=("hypertrade_db:backtest_runs:196",),
            executed_turns=2,
        ),
    )

    assert result["status"] == "failed"
    assert "conversation_context" in result["failed_checks"]
    assert "R4" in result["remediation_ids"]


def test_task_completion_can_require_relevant_text_in_the_decision_field() -> None:
    suite = OperatorTaskCompletionSuite()
    case = next(item for item in suite.cases() if item.case_id == "r02_memory_strategy")
    response = OperatorResponseV1(
        mission_id="mis_memory",
        outcome="completed",
        decision="已读取通用知识库说明。",
        confidence="medium",
        evidence=(
            OperatorEvidenceV1(
                summary="momentum_breakout_v1 的历史经验。",
                source_refs=("memory:eval_memory_momentum",),
            ),
        ),
    )

    result = suite.evaluate(
        case,
        TaskCompletionObservation(
            response=response,
            visible_text="## 结论\n已读取通用知识库说明。\n\nmomentum_breakout_v1 的历史经验。",
            capability_ids=("memory.search",),
            source_refs=("memory:eval_memory_momentum",),
        ),
    )

    assert result["status"] == "failed"
    assert "decision_facts" in result["failed_checks"]
    assert "R3" in result["remediation_ids"]


def test_task_completion_rejects_internal_guidance_in_the_decision_field() -> None:
    suite = OperatorTaskCompletionSuite()
    case = next(item for item in suite.cases() if item.case_id == "r01_rag_risk")
    response = OperatorResponseV1(
        mission_id="mis_rag_noise",
        outcome="completed",
        decision="风控规则：先定义止损。HyperTrade 工具运维指南：/rag 风控。",
        confidence="medium",
        evidence=(
            OperatorEvidenceV1(
                summary="风控规则：先定义止损。",
                source_refs=("rag:eval://risk-controls#0",),
            ),
        ),
    )

    result = suite.evaluate(
        case,
        TaskCompletionObservation(
            response=response,
            visible_text="## 结论\n风控规则：先定义止损。HyperTrade 工具运维指南：/rag 风控。",
            capability_ids=("rag.search",),
            source_refs=("rag:eval://risk-controls#0",),
        ),
    )

    assert result["status"] == "failed"
    assert "no_forbidden_decision" in result["failed_checks"]
    assert "R3" in result["remediation_ids"]
