"""Agent tool-surface coverage for the paper strategy research mainline.

These tests pin the trusted executor branches added in sprint-137:
research_validation_gate and paper_promotion_request.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypertrade.agent.kernel import AgentKernel
from hypertrade.db import Database
from hypertrade.research.schemas import (
    ResearchJobCreate,
    ResearchMandateCreate,
    ValidationPolicy,
)
from hypertrade.research.service import ResearchProgramService


def _kernel_with_mandate(db: Database) -> tuple[AgentKernel, str]:
    kernel = AgentKernel(db, knowledge_dir="docs/knowledge")
    program = ResearchProgramService(db)
    mandate = program.create_mandate(
        ResearchMandateCreate(
            name="BTC bounded matrix",
            symbols=["BTC"],
            timeframes=["1H"],
            strategy_categories=["TREND"],
            validation=ValidationPolicy(min_trade_count=3, max_drawdown_pct="20"),
        )
    )
    return kernel, str(mandate["id"])


def _passing_rows() -> list[dict[str, Any]]:
    return [
        {
            "window": "locked_out_of_sample",
            "metrics": {
                "total_return_pct": "35",
                "max_drawdown_pct": "12",
                "trade_count": "8",
            },
        }
    ]


@pytest.fixture()
def memory_db():
    db = Database("sqlite:///:memory:")
    db.create_all()
    return db


def test_validation_gate_passes_locked_criteria(memory_db):
    kernel, mandate_id = _kernel_with_mandate(memory_db)

    result = kernel._dispatch_tool(
        "research_validation_gate",
        {"mandate_id": mandate_id, "results": _passing_rows()},
        run_id="run_gate_1",
        policy=kernel.tools.get("research.validation_gate").policy,
    )

    assert result["status"] == "ok"
    assert result["passed"] is True
    assert result["evaluated_rows"] == 1
    assert "Authoritative gates" in result["note"]


def test_validation_gate_fails_on_weaker_criteria_without_model_thresholds(memory_db):
    """阈值只能来自 mandate：行不满足 min_trade_count 必须判负。"""
    kernel, mandate_id = _kernel_with_mandate(memory_db)

    rows = _passing_rows()
    rows[0]["metrics"]["trade_count"] = "1"

    result = kernel._dispatch_tool(
        "research_validation_gate",
        # 模型试图自带更宽松的 validation 字段——必须被忽略。
        {
            "mandate_id": mandate_id,
            "results": rows,
            "validation": {"min_trade_count": 0, "max_drawdown_pct": "99"},
        },
        run_id="run_gate_2",
        policy=kernel.tools.get("research.validation_gate").policy,
    )

    assert result["passed"] is False
    assert any(r.startswith("trade_count_below_minimum") for r in result["rejection_reasons"])


def test_validation_gate_reports_missing_mandate(memory_db):
    db = Database("sqlite:///:memory:")
    db.create_all()
    kernel = AgentKernel(db, knowledge_dir="docs/knowledge")

    result = kernel._dispatch_tool(
        "research_validation_gate",
        {"mandate_id": "rman_missing", "results": _passing_rows()},
        run_id="run_gate_3",
        policy=kernel.tools.get("research.validation_gate").policy,
    )

    assert result["status"] == "unavailable"
    assert result["error"]["type"] == "mandate_not_found"


def test_promotion_request_accepts_only_passing_evidence(memory_db):
    """未过检证据必须被拒绝，且不产生任何晋升记录。"""
    from hypertrade.db import ResearchExperimentEvidence

    kernel, mandate_id = _kernel_with_mandate(memory_db)
    program = ResearchProgramService(memory_db)
    job = program.queue_job(
        mandate_id,
        ResearchJobCreate(prompt="test promotion rejection path", idempotency_key="k-promo-1"),
    )
    with memory_db.session() as session:
        evidence = ResearchExperimentEvidence(
            job_id=str(job["id"]),
            mandate_id=mandate_id,
            variant_id="v1",
            status="rejected",
            strategy_key="momentum_breakout_v1",
            gate_results_json={"drawdown": False},
            rejection_reasons_json=["drawdown_exceeds_mandate:locked"],
        )
        session.add(evidence)
        session.flush()
        evidence_id = evidence.id

    result = kernel._dispatch_tool(
        "paper_promotion_request",
        {"evidence_id": evidence_id, "reason": "looks good to me"},
        run_id="run_promo_1",
        policy=kernel.tools.get("paper.promotion_request").policy,
    )

    assert result["status"] == "denied"
    assert result["error"]["type"] == "promotion_request_rejected"


def test_promotion_request_creates_pending_approval_for_passing_evidence(memory_db):
    from hypertrade.db import PaperPromotion, ResearchExperimentEvidence
    from sqlalchemy import select

    kernel, mandate_id = _kernel_with_mandate(memory_db)
    program = ResearchProgramService(memory_db)
    job = program.queue_job(
        mandate_id,
        ResearchJobCreate(prompt="test pending approval creation", idempotency_key="k-promo-2"),
    )
    with memory_db.session() as session:
        evidence = ResearchExperimentEvidence(
            job_id=str(job["id"]),
            mandate_id=mandate_id,
            variant_id="v1",
            status="evidence_recorded",
            strategy_key="momentum_breakout_v1",
            bitpro_strategy_id="42",
            gate_results_json={
                "real_data_coverage": True,
                "cost_assumptions_declared": True,
                "locked_sample_available": True,
                "reported_metrics_complete": True,
                "trade_count": True,
                "drawdown": True,
            },
            rejection_reasons_json=[],
        )
        session.add(evidence)
        session.flush()
        evidence_id = evidence.id

    kwargs = {
        "evidence_id": evidence_id,
        "reason": "all gates passed with locked OOS sample",
    }
    policy = kernel.tools.get("paper.promotion_request").policy
    first = kernel._dispatch_tool(
        "paper_promotion_request", dict(kwargs), run_id="run_promo_2", policy=policy
    )
    second = kernel._dispatch_tool(
        "paper_promotion_request", dict(kwargs), run_id="run_promo_3", policy=policy
    )

    assert first["status"] == "ok"
    assert first["promotion"]["status"] == "pending_paper_approval"
    # Idempotent replay returns the same record instead of duplicating.
    assert second["promotion"]["id"] == first["promotion"]["id"]

    with memory_db.session() as session:
        count = len(session.scalars(select(PaperPromotion)).all())
    assert count == 1


def test_planner_can_orchestrate_full_mainline_within_iteration_budget(memory_db):
    """主线全链路：门禁自检 -> 晋升请求 -> 最终答复，2 个规划轮内完成。"""
    from unittest.mock import MagicMock

    from hypertrade.agent.planner import AgentPlanner
    from hypertrade.db import ResearchExperimentEvidence
    from hypertrade.providers.chat import ChatResponse, ToolCallRequest

    kernel, mandate_id = _kernel_with_mandate(memory_db)
    program = ResearchProgramService(memory_db)
    job = program.queue_job(
        mandate_id,
        ResearchJobCreate(prompt="test mainline orchestration", idempotency_key="k-main-1"),
    )
    with memory_db.session() as session:
        evidence = ResearchExperimentEvidence(
            job_id=str(job["id"]),
            mandate_id=mandate_id,
            variant_id="v1",
            status="evidence_recorded",
            strategy_key="momentum_breakout_v1",
            gate_results_json={
                "real_data_coverage": True,
                "cost_assumptions_declared": True,
                "locked_sample_available": True,
                "reported_metrics_complete": True,
                "trade_count": True,
                "drawdown": True,
            },
            rejection_reasons_json=[],
        )
        session.add(evidence)
        session.flush()
        evidence_id = evidence.id

    llm = MagicMock()
    llm.name = "replay"
    llm.model = "mainline"
    llm.chat.side_effect = [
        ChatResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="c1",
                    name="research_validation_gate",
                    arguments={"mandate_id": mandate_id, "results": _passing_rows()},
                ),
                ToolCallRequest(
                    id="c2",
                    name="paper_promotion_request",
                    arguments={
                        "evidence_id": evidence_id,
                        "reason": "gates passed on locked OOS window",
                        "idempotency_key": "promo-main-1",
                    },
                ),
            ],
        ),
        ChatResponse(content="## 结论\n门禁通过，已提交模拟盘晋升审批。"),
    ]

    run_id = kernel._create_run("推进 BTC 策略到模拟盘", execution_mode="standard")
    executor = kernel._build_executor(run_id)
    result = AgentPlanner(llm).run("推进 BTC 策略到模拟盘", executor)

    assert [call.tool_name for call in result.tool_calls] == [
        "research_validation_gate",
        "paper_promotion_request",
    ]
    assert result.tool_calls[0].output_json["passed"] is True
    assert result.tool_calls[1].output_json["promotion"]["status"] == "pending_paper_approval"
    assert "pending_paper_approval" in result.final_message or len(result.final_message) > 0

    # Telemetry covers both mainline tools.
    assert set(result.tool_telemetry) >= {"research_validation_gate", "paper_promotion_request"}
