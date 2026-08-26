"""Sprint-148: mission research profile — authored-strategy capabilities.

The mission runtime gains workspace/validate/BitPro-write capabilities gated
behind the research.v1 permission profile (operator flag). read_only.v1
behavior must remain byte-identical.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from hypertrade.runtime.adapters.capability_catalog import (
    CatalogCapabilityPolicy,
    builtin_capabilities,
)
from hypertrade.runtime.adapters.research_planner import (
    LlmPlanV2Planner,
    build_mission_planner,
)
from hypertrade.runtime.adapters.tool_runtime import GovernedToolExecutor, builtin_handlers
from hypertrade.runtime.domain.models import (
    MissionBudgetV1,
    MissionProjection,
    MissionStatus,
    PlanStepV2,
    SuccessCriterionV1,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def _fresh_settings_cache():
    """Isolate get_settings lru_cache around env-mutating tests."""
    from hypertrade.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mission(profile: str = "research.v1") -> MissionProjection:
    return MissionProjection(
        mission_id="mis_research_profile_01",
        objective="研究 SOL 4H 双均线策略并回测",
        original_objective="研究 SOL 4H 双均线策略并回测",
        success_criteria=(
            SuccessCriterionV1(
                criterion_id="validated_steps",
                kind="all_steps_validated",
                description="Every step validated.",
            ),
        ),
        constraints=(),
        status=MissionStatus.RUNNING,
        budget=MissionBudgetV1(),
        permission_profile_ref=profile,
        context_policy_ref="mission_context.v1",
        created_by="operator",
    )


def test_catalog_contains_authored_strategy_capabilities_with_coherent_policy():
    capabilities = {item.capability_id: item for item in builtin_capabilities()}

    write_capabilities = (
        "workspace.write_file",
        "workspace.run",
        "bitpro.strategy_create",
        "bitpro.backtest_start",
    )
    for capability_id in write_capabilities:
        definition = capabilities[capability_id]
        assert definition.scope == "research_write"
        assert definition.idempotency == "required"
        assert definition.side_effect == "idempotent_write"

    assert capabilities["research.validate_strategy_code"].scope == "read"
    assert capabilities["bitpro.backtest_result"].scope == "read"


def test_research_profile_allows_research_write_but_read_only_profile_denies():
    policy = CatalogCapabilityPolicy(_CatalogStub())
    step = PlanStepV2(
        step_id="write_strategy",
        title="Write the strategy file",
        capability_id="workspace.write_file",
        arguments={"path": "strategies/s.py", "content": "x = 1"},
        read_only=False,
    )

    # research.v1 admits it.
    policy.validate_step(step, "research.v1")

    # read_only.v1 still denies — byte-identical legacy behavior.
    from hypertrade.runtime.adapters.capability_catalog import CapabilityUnavailable

    with pytest.raises(CapabilityUnavailable, match="denies research_write"):
        policy.validate_step(step, "read_only.v1")

    # Unknown profiles fall back to read-only strictness.
    with pytest.raises(CapabilityUnavailable):
        policy.validate_step(step, "unknown.v1")


class _ScriptedProvider:
    name = "scripted"
    model = "profile-test"

    def __init__(self, content: str) -> None:
        self._content = content
        self.last_envelope_ids: list[str] = []

    def chat(self, messages: list[dict[str, Any]]) -> Any:
        import json as _json

        payload = _json.loads(messages[1]["content"])
        self.last_envelope_ids = [
            item["capability_id"] for item in payload.get("capabilities", [])
        ]
        return _FakeResponse(self._content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


def test_planner_envelope_filters_by_mission_profile():
    plan_json = (
        '{"goal_interpretation": "写策略并回测", "steps": [{"step_id": "write", '
        '"title": "Write strategy file", "capability_id": "workspace.write_file", '
        '"arguments": {"path": "strategies/s.py", "content": "x = 1"}, '
        '"depends_on": []}]}'
    )
    provider = _ScriptedProvider(plan_json)
    planner = build_mission_planner(_FlagSettings(True), provider)
    assert isinstance(planner, LlmPlanV2Planner)

    # research.v1 mission: write capability visible and plannable.
    plan = asyncio.run(planner.plan(_mission("research.v1")))
    assert plan.steps[0].capability_id == "workspace.write_file"
    assert plan.steps[0].read_only is False
    assert "workspace.write_file" in provider.last_envelope_ids

    # read_only.v1 mission: envelope hides write capabilities entirely, so the
    # model cannot even see them; proposal falls back to deterministic plan.
    read_only_plan = asyncio.run(planner.plan(_mission("read_only.v1")))
    assert "workspace.write_file" not in provider.last_envelope_ids
    assert all(step.read_only for step in read_only_plan.steps)


class _FlagSettings:
    def __init__(self, enabled: bool) -> None:
        self.mission_llm_planner_enabled = True
        self.mission_research_profile_enabled = enabled


@pytest.mark.anyio
async def test_executor_end_to_end_workspace_write_and_pytest(tmp_path):
    """executor 端到端：mission 步骤写策略+测试并跑真实 pytest 通过。"""
    handlers = builtin_handlers(_StubDb(), knowledge_dir=str(tmp_path))
    executor = GovernedToolExecutor(
        _CatalogStub(),
        handlers,
        observations=_ObservationsStub(),
    )
    mission = _mission("research.v1")

    from hypertrade.runtime.domain.models import PlanDiffV1, PlanV2

    plan = PlanV2(
        plan_id="plan_ws_01",
        version=1,
        goal_interpretation="author and test a strategy",
        completion_checks=("validated_steps",),
        steps=(
            PlanStepV2(
                step_id="write_strategy",
                title="Write strategy",
                capability_id="workspace.write_file",
                arguments={
                    "path": "strategies/agent_sma.py",
                    "content": (
                        "from app.core.execution.base_strategy import BaseStrategy\n"
                        "\n"
                        "\n"
                        "class AgentSma(BaseStrategy):\n"
                        "    async def on_init(self):\n"
                        "        self.seen = 0\n"
                        "\n"
                        "    async def on_bar(self, bar):\n"
                        "        self.seen += 1\n"
                        "        return None\n"
                    ),
                },
                read_only=False,
            ),
            PlanStepV2(
                step_id="write_test",
                title="Write test",
                capability_id="workspace.write_file",
                arguments={
                    "path": "tests/test_agent_sma.py",
                    "content": (
                        "import asyncio\n"
                        "from types import SimpleNamespace\n"
                        "from strategies.agent_sma import AgentSma\n"
                        "\n"
                        "\n"
                        "def test_counts_bars():\n"
                        "    s = AgentSma({'symbols': ('SOL',)})\n"
                        "    asyncio.run(s.on_init())\n"
                        "    asyncio.run(s.on_bar(SimpleNamespace(symbol='SOL', close=1.0)))\n"
                        "    assert s.seen == 1\n"
                    ),
                },
                read_only=False,
            ),
            PlanStepV2(
                step_id="run_pytest",
                title="Run pytest",
                capability_id="workspace.run",
                arguments={"command": "pytest"},
                read_only=False,
            ),
        ),
        diff=PlanDiffV1(reason_code="initial_plan"),
    )

    for step in plan.steps:
        observation = await executor.execute(mission, plan, step, 1)
        assert observation.status == "succeeded", observation.summary

    # The pytest step must have really executed and passed.
    pytest_step = await executor.execute(mission, plan, plan.steps[2], 2)
    assert pytest_step.status == "succeeded"


class _StubDb:
    url = "sqlite:///:memory:"


class _CatalogStub:
    def resolve_sync(self, capability_id: str, version: str) -> Any:
        from hypertrade.runtime.adapters.capability_catalog import builtin_capabilities

        for definition in builtin_capabilities():
            if definition.capability_id == capability_id:
                return _SnapshotStub(definition)
        raise KeyError(capability_id)


class _SnapshotStub:
    def __init__(self, definition: Any) -> None:
        self.definition = definition
        from hypertrade.runtime.domain.capabilities import (
            CapabilityDefinitionV1,
        )

        assert isinstance(definition, CapabilityDefinitionV1)
        self.contract_hash = definition.contract_hash()
        # 64-hex policy hash stub (ToolRequestV2 requires the shape).
        self.policy_hash = "a" * 64


class _ObservationsStub:
    async def append(self, observation: Any, *, idempotency_key: str = "") -> None:
        return None

    async def by_idempotency(self, key: str) -> None:
        return None


def test_bitpro_write_handlers_use_fake_adapter(tmp_path):
    """BitPro 写 handler 走 fake adapter：strategy_create + backtest_start。"""
    from hypertrade.runtime.domain.models import PlanDiffV1, PlanV2

    class _FakeAdapter:
        def __init__(self) -> None:
            self.created: dict[str, Any] = {}
            self.started: dict[str, Any] = {}

        def strategy_create(self, **kwargs: Any) -> dict[str, Any]:
            self.created = kwargs
            return {"strategy_id": 777, "name": kwargs.get("name", "")}

        def backtest_start_job(self, **kwargs: Any) -> dict[str, Any]:
            self.started = kwargs
            return {
                "backtest_id": "bt_9001",
                "metrics": {"total_return_pct": "5.0", "sharpe_ratio": "1.1"},
            }

    fake = _FakeAdapter()
    handlers = builtin_handlers(
        _StubDb(), knowledge_dir=str(tmp_path), bitpro_adapter_factory=lambda: fake
    )
    executor = GovernedToolExecutor(
        _CatalogStub(), handlers, observations=_ObservationsStub()
    )
    mission = _mission("research.v1")
    plan = PlanV2(
        plan_id="plan_bp_01",
        version=1,
        goal_interpretation="create and backtest",
        completion_checks=("validated_steps",),
        steps=(
            PlanStepV2(
                step_id="write_code",
                title="Write the strategy file",
                capability_id="workspace.write_file",
                arguments={
                    "path": "strategies/agent_sma.py",
                    "content": (
                        "from app.core.execution.base_strategy import BaseStrategy\n"
                        "\n"
                        "\n"
                        "class AgentSma(BaseStrategy):\n"
                        "    async def on_bar(self, bar: BarData):\n"
                        "        return None\n"
                    ),
                },
                read_only=False,
            ),
            PlanStepV2(
                step_id="create",
                title="Create strategy",
                capability_id="bitpro.strategy_create",
                arguments={
                    "name": "agent_sma_v1",
                    "workspace_path": "strategies/agent_sma.py",
                    "symbols": ["SOL-USDT-SWAP"],
                },
                read_only=False,
            ),
            PlanStepV2(
                step_id="backtest",
                title="Start backtest",
                capability_id="bitpro.backtest_start",
                arguments={
                    "strategy_id": 777,
                    "start_date": "2025-01-01",
                    "end_date": "2025-04-01",
                    "symbol": "SOL-USDT-SWAP",
                    "timeframe": "4H",
                },
                read_only=False,
            ),
        ),
        diff=PlanDiffV1(reason_code="initial_plan"),
    )

    write_obs = asyncio.run(executor.execute(mission, plan, plan.steps[0], 1))
    assert write_obs.status == "succeeded"

    created_obs = asyncio.run(executor.execute(mission, plan, plan.steps[1], 1))
    assert created_obs.status == "succeeded"
    assert created_obs.result["strategy_id"] == 777
    assert fake.created["name"] == "agent_sma_v1"
    # Provenance binding: the submitted code IS the workspace file content.
    assert "class AgentSma(BaseStrategy)" in fake.created["script_content"]

    backtest_obs = asyncio.run(executor.execute(mission, plan, plan.steps[2], 1))
    assert backtest_obs.status == "succeeded"
    assert backtest_obs.result["backtest_id"] == "bt_9001"
    assert backtest_obs.result["metrics"]["sharpe_ratio"] == "1.1"
    assert fake.started["strategy_id"] == 777
    assert fake.started["wait_for_result"] is True


@pytest.mark.usefixtures("_fresh_settings_cache")
def test_entrypoint_profile_flag(monkeypatch):
    from hypertrade.runtime.application.entrypoint import (
        active_mission_permission_profile,
        mission_request_for_prompt,
    )

    monkeypatch.delenv("MISSION_RESEARCH_PROFILE_ENABLED", raising=False)
    from hypertrade.config import get_settings

    get_settings.cache_clear()
    assert active_mission_permission_profile() == "read_only.v1"
    request = mission_request_for_prompt(
        "研究 SOL 趋势", actor="t", idempotency_key="k-profile-1"
    )
    assert request.permission_profile_ref == "read_only.v1"

    monkeypatch.setenv("MISSION_RESEARCH_PROFILE_ENABLED", "true")
    from hypertrade.config import get_settings

    get_settings.cache_clear()
    assert active_mission_permission_profile() == "research.v1"
    request = mission_request_for_prompt(
        "研究 SOL 趋势", actor="t", idempotency_key="k-profile-2"
    )
    assert request.permission_profile_ref == "research.v1"
    assert any("research_write" in constraint for constraint in request.constraints)
