from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from hypertrade.arc.avo import run_avo_research
from hypertrade.arc.contracts import (
    ARCBudgetV1,
    ARCCandidateAttemptV1,
    ARCGoalV1,
    ARCSuccessCriteriaV1,
    ResearchWindowsV1,
)
from hypertrade.arc.controller import ARCController
from hypertrade.arc.evolution_memory import experiment_key
from hypertrade.arc.self_test import ARCSelfTestService
from hypertrade.arc.store import reset_store, save_mission
from hypertrade.providers.chat import ChatResponse, ToolCallRequest


@pytest.fixture
def source_variant_mission():
    reset_store()
    variant_policy = {
        "contract_version": "strategy_research_variant_policy.v1",
        "parent_strategy_id": 107,
        "parent_manifest_sha256": "a" * 64,
        "variant_creation_supported": True,
        "authorized_parameters": [
            {
                "name": "fast_window",
                "type": "int",
                "minimum": 5,
                "maximum": 50,
                "current_value": 10,
            },
            {
                "name": "slow_window",
                "type": "int",
                "minimum": 20,
                "maximum": 200,
                "current_value": 30,
            },
            {
                "name": "threshold",
                "type": "float",
                "minimum": 0.01,
                "maximum": 0.10,
                "current_value": 0.02,
            },
        ],
    }
    baseline_attempt = ARCCandidateAttemptV1(
        attempt_id="baseline_107",
        candidate_id="baseline_107",
        hypothesis="原策略基线",
        strategy_code="class NativeStrategy107: pass\n",
        strategy_spec={
            "symbol": "BTC-USDT",
            "timeframe": "1H",
            "is_source_variant": True,
            "parent_strategy_id": 107,
            "parent_manifest_sha256": "a" * 64,
            "tunable_parameters": {
                "fast_window": 10,
                "slow_window": 30,
                "threshold": 0.02,
            },
            "baseline_config": {"fast_window": 10, "slow_window": 30, "threshold": 0.02},
        },
    )
    ctrl = ARCController(
        goal=ARCGoalV1(
            objective="对107号策略进行参数调优",
            symbols=["BTC-USDT"],
            timeframes=["1H"],
            paper_review_required=True,
            research_mode="avo",
            budget=ARCBudgetV1(max_candidates=5, max_backtests=10),
            success_criteria=ARCSuccessCriteriaV1(required_validation_policy="arc_windowed_v1"),
            evolution_context={
                "source_strategy_id": 107,
                "variant_policy": variant_policy,
                "baseline": baseline_attempt.model_dump(mode="json"),
                "research_windows": {
                    "as_of": "2026-09-24",
                    "development_days": 60,
                    "final_days": 30,
                },
            },
        )
    )
    save_mission(ctrl)
    yield ctrl
    reset_store()


def test_experiment_key_distinguishes_different_parameter_changes():
    windows = ResearchWindowsV1(as_of="2026-09-24")
    code_sha256 = "b" * 64
    spec_a = {
        "symbol": "BTC-USDT",
        "timeframe": "1H",
        "is_source_variant": True,
        "parent_manifest_sha256": "a" * 64,
        "parameter_changes": {"fast_window": 15},
    }
    spec_b = {
        "symbol": "BTC-USDT",
        "timeframe": "1H",
        "is_source_variant": True,
        "parent_manifest_sha256": "a" * 64,
        "parameter_changes": {"fast_window": 20},
    }
    key_a = experiment_key(code_sha256, spec_a, Decimal("10000"), windows)
    key_b = experiment_key(code_sha256, spec_b, Decimal("10000"), windows)
    assert key_a != key_b, "Different parameter changes must produce distinct experiment keys"

    spec_a_repeat = {
        "symbol": "BTC-USDT",
        "timeframe": "1H",
        "is_source_variant": True,
        "parent_manifest_sha256": "a" * 64,
        "parameter_changes": {"fast_window": 15},
    }
    key_a_repeat = experiment_key(code_sha256, spec_a_repeat, Decimal("10000"), windows)
    assert key_a == key_a_repeat, (
        "Identical parameter changes must produce identical experiment keys"
    )


class MockSourceVariantProvider:
    name = "fixture"
    model = "source-variant-test"

    def __init__(self):
        self.step = 0
        self.seen_messages = []
        self.knowledge_observed = None

    def chat(self, messages, tools=None):
        self.seen_messages.append(messages)
        self.step += 1
        last = json.loads(messages[-1]["content"]) if messages[-1]["role"] == "tool" else {}
        if self.step == 1:
            # 1. 检查 knowledge
            return ChatResponse(
                content="",
                tool_calls=[ToolCallRequest("1", "inspect", {"target": "knowledge"})],
            )
        elif self.step == 2:
            self.knowledge_observed = last
            # 2. 提议一个合法参数变体
            return ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        "2",
                        "propose",
                        {
                            "hypothesis": "提高快线周期至15以过滤假突破",
                            "parameter_changes": {"fast_window": 15},
                        },
                    )
                ],
            )
        elif self.step == 3:
            self.first_attempt_id = last["attempt_id"]
            # 3. 提议另一个不同参数的变体（测试同源码不同参数不被去重）
            return ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        "3",
                        "propose",
                        {
                            "hypothesis": "进一步提高快线周期至20",
                            "parameter_changes": {"fast_window": 20},
                        },
                    )
                ],
            )
        elif self.step == 4:
            self.second_attempt_id = last["attempt_id"]
            # 4. 重新提议第一个变体（测试同源码同参数被去重）
            return ChatResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        "4",
                        "propose",
                        {
                            "hypothesis": "再次尝试快线15",
                            "parameter_changes": {"fast_window": 15},
                        },
                    )
                ],
            )
        elif self.step == 5:
            self.duplicate_response = last
            # 5. develop 第一个变体
            return ChatResponse(
                content="",
                tool_calls=[ToolCallRequest("5", "develop", {"attempt_id": self.first_attempt_id})],
            )
        else:
            return ChatResponse(
                content="",
                tool_calls=[ToolCallRequest("6", "stop", {"reason": "test finished"})],
            )


class MockSelfTestClient:
    def __init__(self):
        self.variant_created = []
        self.backtests_started = []

    def strategy_get(self, *, strategy_id: int) -> dict[str, Any]:
        return {"strategy_id": strategy_id, "script_content": "class NativeStrategy107: pass\n"}

    def strategy_research_variant_create(
        self,
        *,
        strategy_id: int,
        expected_parent_manifest_sha256: str,
        idempotency_key: str,
        parameter_changes: dict[str, int | float],
        purpose: str = "candidate",
    ) -> dict[str, Any]:
        prior = next(
            (
                i
                for i, c in enumerate(self.variant_created)
                if c["idempotency_key"] == idempotency_key
            ),
            None,
        )
        if prior is not None:
            # BitPro rejects a reused key with different parameters.
            assert self.variant_created[prior]["parameter_changes"] == parameter_changes
            new_id = 9001 + prior
        else:
            self.variant_created.append(
                {
                    "strategy_id": strategy_id,
                    "expected_parent_manifest_sha256": expected_parent_manifest_sha256,
                    "idempotency_key": idempotency_key,
                    "parameter_changes": parameter_changes,
                    "purpose": purpose,
                }
            )
            new_id = 9000 + len(self.variant_created)
        return {
            "contract_version": "strategy_research_variant.v1",
            "parent_strategy_id": strategy_id,
            "parent_manifest_sha256": expected_parent_manifest_sha256,
            "purpose": purpose,
            "status": "stopped",
            "candidate_strategy_id": new_id,
            "cost_receipt": {"cost_policy_hash": "c" * 64},
        }

    def backtest_start_job(
        self,
        *,
        strategy_id: int,
        start_date: str,
        end_date: str,
        initial_capital: float = 10000.0,
        exchange: str = "okx",
        symbol: str | None = None,
        timeframe: str | None = None,
        wait_for_result: bool = False,
        verified_data_snapshot_id: str | None = None,
        verified_data_manifest_sha256: str | None = None,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        if not any(b["idempotency_key"] == idempotency_key for b in self.backtests_started):
            self.backtests_started.append(
                {
                    "strategy_id": strategy_id,
                    "start_date": start_date,
                    "end_date": end_date,
                    "initial_capital": initial_capital,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "idempotency_key": idempotency_key,
                    "verified_data_snapshot_id": verified_data_snapshot_id,
                    "verified_data_manifest_sha256": verified_data_manifest_sha256,
                }
            )
        sealed = verified_data_manifest_sha256 or "d" * 64
        return {
            "backtest_id": f"bt_{strategy_id}_{idempotency_key[-8:]}",
            "job": {
                "verified_data_binding": {
                    "version": "verified_backtest_data.v3",
                    "entries": [
                        {"verified_snapshot_id": "vbs_" + sealed, "manifest_sha256": sealed}
                    ],
                }
            },
            "metrics": {
                "net_return": 0.15,
                "sharpe": 1.8,
                "max_drawdown": 0.05,
                "trades": 35,
            },
        }


def test_avo_source_variant_flow(source_variant_mission):
    provider = MockSourceVariantProvider()
    client = MockSelfTestClient()
    service = ARCSelfTestService(client=client)

    run_avo_research(source_variant_mission.mission_id, provider=provider, experiments=service)

    # 1. 验证 inspect 得到了 source_variant_policy
    assert provider.knowledge_observed is not None
    assert "source_variant_policy" in provider.knowledge_observed
    assert provider.knowledge_observed["source_variant_policy"]["parent_strategy_id"] == 107

    # 2. 验证两次不同参数的变体都成功生成且 attempt_id 不同
    attempts = source_variant_mission.projection.attempts
    assert len(attempts) == 2, f"Expected 2 unique attempts, found {len(attempts)}"
    assert attempts[0].attempt_id != attempts[1].attempt_id
    assert attempts[0].strategy_spec.get("is_source_variant") is True
    assert attempts[0].strategy_spec["parameter_changes"] == {"fast_window": 15}
    assert attempts[1].strategy_spec["parameter_changes"] == {"fast_window": 20}
    # 原策略代码原封不动
    assert attempts[0].strategy_code == attempts[1].strategy_code

    # 3. 验证同源码同参数被去重
    assert provider.duplicate_response is not None
    assert provider.duplicate_response.get("duplicate") is True
    assert provider.duplicate_response.get("attempt_id") == provider.first_attempt_id

    # 4. 验证 develop 时调用了 strategy_research_variant_create 和 backtest_start_job
    assert len(client.variant_created) >= 1
    created_call = client.variant_created[0]
    assert created_call["strategy_id"] == 107
    assert created_call["parameter_changes"] == {"fast_window": 15}
    assert created_call["purpose"] == "candidate"
    baseline_create = client.variant_created[1]
    assert baseline_create["purpose"] == "baseline"
    assert baseline_create["parameter_changes"] == {}
    candidate_keys = [
        c["idempotency_key"] for c in client.variant_created if c["purpose"] == "candidate"
    ]
    assert len(candidate_keys) == len(set(candidate_keys))

    # 5. 基线先在同窗封存行情，候选只引用基线的封存快照
    baseline_run, candidate_run = client.backtests_started[0], client.backtests_started[1]
    assert baseline_run["strategy_id"] == 9002
    assert baseline_run["verified_data_snapshot_id"] is None
    assert candidate_run["strategy_id"] == 9001
    assert candidate_run["verified_data_snapshot_id"] == "vbs_" + "d" * 64
    assert candidate_run["verified_data_manifest_sha256"] == "d" * 64
    assert candidate_run["idempotency_key"] != baseline_run["idempotency_key"]


def test_source_variant_validation_rejections(source_variant_mission):
    from hypertrade.arc.avo import _perform

    experiments = ARCSelfTestService(client=MockSelfTestClient())

    # 1. 尝试未授权参数
    with pytest.raises(ValueError, match="not authorized for variation"):
        _perform(
            source_variant_mission,
            "propose",
            {
                "hypothesis": "修改未授权参数",
                "parameter_changes": {"unauthorized_param": 10},
            },
            experiments,
        )

    # 2. 尝试越界参数（超上限）
    with pytest.raises(ValueError, match="out of bounds"):
        _perform(
            source_variant_mission,
            "propose",
            {
                "hypothesis": "修改参数超出上限",
                "parameter_changes": {"fast_window": 999},
            },
            experiments,
        )

    # 3. 整型参数传浮点数
    with pytest.raises(ValueError, match="requires integer value"):
        _perform(
            source_variant_mission,
            "propose",
            {
                "hypothesis": "整型参数传小数",
                "parameter_changes": {"fast_window": 12.5},
            },
            experiments,
        )

    # 4. 0 变更（与原基线参数完全一样）
    with pytest.raises(ValueError, match="must change at least one source parameter"):
        _perform(
            source_variant_mission,
            "propose",
            {
                "hypothesis": "没有实际改变任何参数",
                "parameter_changes": {"fast_window": 10},
            },
            experiments,
        )


def test_candidate_fails_closed_when_baseline_has_no_sealed_data(source_variant_mission):
    from hypertrade.arc.contracts import ARCCandidateAttemptV1

    class NoBindingClient(MockSelfTestClient):
        def backtest_start_job(self, **kwargs):
            result = super().backtest_start_job(**kwargs)
            result.pop("job")
            return result

    client = NoBindingClient()
    goal = source_variant_mission.projection.goal
    baseline = goal.evolution_context["baseline"]
    attempt = ARCCandidateAttemptV1(
        attempt_id="att_candidate",
        candidate_id="cand_candidate",
        hypothesis="h",
        strategy_code=baseline["strategy_code"],
        strategy_spec={
            **baseline["strategy_spec"],
            "is_source_variant": True,
            "parent_strategy_id": 107,
            "parent_manifest_sha256": "a" * 64,
            "parameter_changes": {"fast_window": 15},
        },
    )
    result = ARCSelfTestService(client=client).run(attempt, goal, purpose="development")
    assert result.passed is False
    assert result.reasons == ["baseline_data_snapshot_unavailable"]
    assert [b["strategy_id"] for b in client.backtests_started] == [9002]
