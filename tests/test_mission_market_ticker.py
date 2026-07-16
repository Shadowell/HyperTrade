from __future__ import annotations

from decimal import Decimal

import pytest
from hypertrade.db import Database
from hypertrade.market.repository import MarketRepository
from hypertrade.runtime.adapters.capability_catalog import (
    InMemoryCapabilityCatalog,
    builtin_capabilities,
)
from hypertrade.runtime.adapters.memory_store import InMemoryMissionStore
from hypertrade.runtime.adapters.research_planner import DeterministicResearchPlanner
from hypertrade.runtime.adapters.tool_runtime import GovernedToolExecutor, builtin_handlers
from hypertrade.runtime.application.operator_response import (
    build_operator_response,
    render_operator_response,
)
from hypertrade.runtime.domain.models import (
    MissionCreate,
    MissionStatus,
    StepAttemptV2,
    SuccessCriterionV1,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _execute_market_quote(
    tmp_path,
    *,
    seed_lab: bool,
):
    database = Database("sqlite:///:memory:")
    database.create_all()
    if seed_lab:
        MarketRepository(database).upsert_ticker_snapshot(
            inst_id="LAB-USDT-SWAP",
            inst_type="SWAP",
            last=Decimal("0.48"),
            volume_ccy_24h=Decimal("1200000"),
            change_utc0_pct=Decimal("3.2"),
        )
    catalog = InMemoryCapabilityCatalog()
    await catalog.bootstrap(builtin_capabilities())
    mission = await InMemoryMissionStore().create(
        MissionCreate(
            objective="看下 LAB 的价格",
            success_criteria=(
                SuccessCriterionV1(
                    criterion_id="validated",
                    kind="all_steps_validated",
                    description="The requested market fact must be validated.",
                ),
            ),
        )
    )
    plan = await DeterministicResearchPlanner().plan(mission)
    step = plan.steps[-1]
    observation = await GovernedToolExecutor(
        catalog,
        builtin_handlers(database, knowledge_dir=str(tmp_path)),
    ).execute(mission, plan, step, 1)
    response = build_operator_response(
        mission.model_copy(update={"status": MissionStatus.COMPLETED}),
        (
            StepAttemptV2(
                attempt_id="sat_lab_quote",
                step_id=step.step_id,
                attempt=1,
                status=observation.status,
                capability_id=step.capability_id,
                observation=observation,
            ),
        ),
    )
    return step, observation, response, render_operator_response(response)


@pytest.mark.anyio
async def test_explicit_bare_symbol_returns_the_requested_quote(tmp_path) -> None:
    step, observation, response, rendered = await _execute_market_quote(tmp_path, seed_lab=True)

    assert step.arguments == {"limit": 10, "inst_id": "LAB-USDT-SWAP"}
    assert observation.source_refs == ("hypertrade_db:market_tickers:LAB-USDT-SWAP",)
    assert response.outcome == "completed"
    assert "LAB-USDT-SWAP 最新价 0.480000000000" in response.decision
    assert "已读取 10 个最新合约行情快照" not in rendered


@pytest.mark.anyio
async def test_explicit_missing_bare_symbol_returns_targeted_data_gap(tmp_path) -> None:
    step, observation, response, rendered = await _execute_market_quote(tmp_path, seed_lab=False)

    assert step.arguments == {"limit": 10, "inst_id": "LAB-USDT-SWAP"}
    assert observation.source_refs == ("market:no_matches",)
    assert response.outcome == "needs_data"
    assert response.decision == "未找到 LAB-USDT-SWAP 的可验证行情。"
    assert response.next_actions
    assert "已读取 10 个最新合约行情快照" not in rendered
