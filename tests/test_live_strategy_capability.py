from __future__ import annotations

from typing import Any

import pytest
from hypertrade.bitpro.mcp import BitProMcpError
from hypertrade.db import Database
from hypertrade.runtime.adapters.capability_catalog import (
    InMemoryCapabilityCatalog,
    builtin_capabilities,
)
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.adapters.research_planner import DeterministicResearchPlanner
from hypertrade.runtime.adapters.tool_runtime import (
    GovernedToolExecutor,
    LiveStrategyReader,
    builtin_handlers,
)
from hypertrade.runtime.domain.models import (
    MissionCreate,
    MissionProjection,
    PlanStepV2,
    StepObservationV2,
    SuccessCriterionV1,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _AvailableBitPro:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def live_strategy_performance(self, *, exchange: str, limit: int) -> dict[str, Any]:
        self.calls.append((exchange, limit))
        return {
            "status": "ok",
            "strategies": [
                {
                    "strategy_id": 107,
                    "strategy_name": "[合约][1H][CTA] BTC · 趋势跟踪 · 100U",
                    "status": "running",
                    "workspace_status": "active",
                    "symbols": ["BTC/USDT:USDT"],
                    "return_pct": "4.2",
                    "total_pnl": "42",
                    "deployment_status": "deployed",
                    "updated_at": "2026-07-16T00:00:00Z",
                }
            ],
        }


class _UnavailableBitPro:
    def live_strategy_performance(self, *, exchange: str, limit: int) -> dict[str, Any]:
        del exchange, limit
        raise BitProMcpError("BitPro MCP unavailable")


class _NoPerformanceBitPro:
    def live_strategy_performance(self, *, exchange: str, limit: int) -> dict[str, Any]:
        del exchange, limit
        return {
            "status": "ok",
            "strategies": [
                {
                    "strategy_id": 107,
                    "strategy_name": "BTC 趋势跟踪",
                    "status": "running",
                    "symbols": ["BTC/USDT:USDT"],
                }
            ],
        }


async def _mission(objective: str = "我的实盘策略有哪些") -> MissionProjection:
    return await InMemoryMissionStore().create(
        MissionCreate(
            objective=objective,
            success_criteria=(
                SuccessCriterionV1(
                    criterion_id="validated",
                    kind="all_steps_validated",
                    description="The governed live strategy read must validate.",
                ),
            ),
        )
    )


async def _execute(
    adapter: LiveStrategyReader,
    objective: str = "我的实盘策略有哪些",
) -> tuple[StepObservationV2, PlanStepV2]:
    database = Database("sqlite:///:memory:")
    database.create_all()
    catalog = InMemoryCapabilityCatalog()
    await catalog.bootstrap(builtin_capabilities())
    mission = await _mission(objective)
    plan = await DeterministicResearchPlanner().plan(mission)
    step = plan.steps[-1]
    executor = GovernedToolExecutor(
        catalog,
        builtin_handlers(
            database,
            knowledge_dir="docs/knowledge",
            bitpro_adapter_factory=lambda: adapter,
        ),
    )
    return await executor.execute(mission, plan, step, 1), step


@pytest.mark.anyio
async def test_live_strategy_inventory_returns_only_bitpro_bound_facts() -> None:
    adapter = _AvailableBitPro()

    observation, step = await _execute(adapter)

    assert observation.status == "succeeded"
    assert step.capability_id == "bitpro.live_strategy_summary"
    assert observation.source_refs == ("bitpro_mcp:live_strategies:107",)
    assert observation.result["count"] == 1
    assert observation.result["strategies"][0]["strategy_name"].startswith("[合约]")
    assert "BTC · 趋势跟踪" in observation.summary
    assert "运行中" in observation.summary
    assert adapter.calls == [("okx", 20)]


@pytest.mark.anyio
async def test_live_strategy_inventory_reports_unavailable_source_without_fabricating() -> None:
    observation, _ = await _execute(_UnavailableBitPro())

    assert observation.status == "succeeded"
    assert observation.source_refs == ("bitpro_mcp:live_strategies:no_matches",)
    assert observation.unknowns == ("BitPro 实盘策略数据源当前不可用，未推断策略清单。",)
    assert observation.result == {"strategies": [], "count": 0, "source_available": False}


@pytest.mark.anyio
async def test_live_strategy_ranking_requires_numeric_returns() -> None:
    observation, step = await _execute(
        _NoPerformanceBitPro(),
        "看下我最好的实盘策略是哪个？",
    )

    assert step.arguments["presentation"] == "best"
    assert step.arguments["sort"] == "desc"
    assert observation.status == "succeeded"
    assert observation.source_refs == ("bitpro_mcp:live_strategies:no_matches",)
    assert observation.unknowns == (
        "BitPro 返回了 1 条实盘策略记录，但未提供可比较的逐策略收益率；"
        "无法确定表现最佳或最差的策略。",
    )
    assert observation.result == {"strategies": [], "count": 0, "source_available": True}
