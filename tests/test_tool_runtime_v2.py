from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import pytest
from hypertrade.db import Database
from hypertrade.runtime.adapters.capability_catalog import InMemoryCapabilityCatalog
from hypertrade.runtime.adapters.tool_runtime import (
    CircuitBreaker,
    GovernedToolExecutor,
    SqlObservationStore,
    ToolResult,
)
from hypertrade.runtime.domain.capabilities import CapabilityDefinitionV1
from hypertrade.runtime.domain.models import (
    MissionBudgetV1,
    MissionProjection,
    MissionStatus,
    PlanStepV2,
    PlanV2,
    SuccessCriterionV1,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def mission(*, permission: str = "read_only.v1") -> MissionProjection:
    return MissionProjection(
        mission_id="mis_tool_runtime",
        objective="Validate the governed tool runtime",
        original_objective="Validate the governed tool runtime",
        success_criteria=(
            SuccessCriterionV1(
                criterion_id="validated",
                kind="all_steps_validated",
                description="Tool observation validates.",
            ),
        ),
        constraints=(),
        status=MissionStatus.RUNNING,
        budget=MissionBudgetV1(),
        permission_profile_ref=permission,
        context_policy_ref="mission_context.v1",
        created_by="test",
    )


def definition(**updates: object) -> CapabilityDefinitionV1:
    values: dict[str, object] = {
        "capability_id": "test.read",
        "title": "Test read capability",
        "description": "Return a schema-bound test observation.",
        "source_owner": "test",
        "handler_key": "test.read",
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": True,
        },
    }
    values.update(updates)
    return CapabilityDefinitionV1.model_validate(values)


def plan_step(capability: CapabilityDefinitionV1, **arguments: Any) -> tuple[PlanV2, PlanStepV2]:
    step = PlanStepV2(
        step_id="execute",
        title="Execute governed capability",
        capability_id=capability.capability_id,
        capability_version=capability.version,
        arguments=arguments,
        read_only=capability.scope == "read",
        requires_approval=capability.approval == "required",
    )
    plan = PlanV2(
        plan_id="plan_tool_runtime",
        version=1,
        goal_interpretation="Validate tool runtime",
        completion_checks=("validated",),
        steps=(step,),
    )
    return plan, step


async def catalog_with(item: CapabilityDefinitionV1) -> InMemoryCapabilityCatalog:
    catalog = InMemoryCapabilityCatalog()
    await catalog.bootstrap((item,))
    return catalog


@pytest.mark.anyio
async def test_success_is_bound_to_version_hashes_and_sources() -> None:
    item = definition()
    catalog = await catalog_with(item)

    async def handler(*_: object) -> ToolResult:
        return ToolResult(payload={"value": 7}, source_refs=("fixture:seven",))

    executor = GovernedToolExecutor(catalog, {item.handler_key: handler})
    plan, step = plan_step(item, value=7)

    result = await executor.execute(mission(), plan, step, 1)
    observations = await executor.observations.list(mission().mission_id)

    assert result.status == "succeeded"
    assert result.source_refs == ("fixture:seven",)
    assert observations[0].contract_hash == item.contract_hash()
    assert observations[0].policy_hash == item.policy_hash()


@pytest.mark.anyio
async def test_input_contract_mismatch_stops_before_handler() -> None:
    item = definition()
    catalog = await catalog_with(item)
    calls = 0

    async def handler(*_: object) -> ToolResult:
        nonlocal calls
        calls += 1
        return ToolResult(payload={"value": 7}, source_refs=("fixture:seven",))

    executor = GovernedToolExecutor(catalog, {item.handler_key: handler})
    plan, step = plan_step(item, value="not-an-integer")

    result = await executor.execute(mission(), plan, step, 1)

    assert result.status == "failed"
    assert result.error_category == "contract_mismatch"
    assert calls == 0


@pytest.mark.anyio
async def test_output_contract_mismatch_is_not_success() -> None:
    item = definition()
    catalog = await catalog_with(item)

    async def handler(*_: object) -> ToolResult:
        return ToolResult(payload={"value": "wrong"}, source_refs=("fixture:wrong",))

    executor = GovernedToolExecutor(catalog, {item.handler_key: handler})
    plan, step = plan_step(item, value=7)
    result = await executor.execute(mission(), plan, step, 1)

    assert result.status == "failed"
    assert result.error_category == "contract_mismatch"


@pytest.mark.anyio
async def test_timeout_opens_circuit_and_prevents_third_dispatch() -> None:
    item = definition(timeout_seconds=0.01)
    catalog = await catalog_with(item)
    calls = 0

    async def handler(*_: object) -> ToolResult:
        nonlocal calls
        calls += 1
        await anyio.sleep(0.05)
        return ToolResult(payload={"value": 1}, source_refs=("fixture:late",))

    executor = GovernedToolExecutor(
        catalog,
        {item.handler_key: handler},
        circuit=CircuitBreaker(failure_threshold=2, cooldown_seconds=60),
    )
    plan, step = plan_step(item, value=1)
    first = await executor.execute(mission(), plan, step, 1)
    second = await executor.execute(mission(), plan, step, 2)
    third = await executor.execute(mission(), plan, step, 3)

    assert first.error_category == "timeout"
    assert second.error_category == "timeout"
    assert third.error_category == "unknown_failure"
    assert calls == 2
    assert executor.circuit.state(item.capability_id).state == "open"


@pytest.mark.anyio
async def test_idempotent_write_replays_without_second_handler_call() -> None:
    item = definition(
        capability_id="test.write",
        handler_key="test.write",
        scope="research_write",
        side_effect="idempotent_write",
        idempotency="required",
    )
    catalog = await catalog_with(item)
    calls = 0

    async def handler(*_: object) -> ToolResult:
        nonlocal calls
        calls += 1
        return ToolResult(payload={"value": 9}, source_refs=("fixture:write",))

    executor = GovernedToolExecutor(catalog, {item.handler_key: handler})
    plan, step = plan_step(item, value=9)
    first = await executor.execute(mission(permission="research.v1"), plan, step, 1)
    replay = await executor.execute(mission(permission="research.v1"), plan, step, 2)

    assert first.status == "succeeded"
    assert replay.status == "succeeded"
    assert calls == 1
    observations = await executor.observations.list()
    assert observations[-1].status == "replayed"


@pytest.mark.anyio
async def test_sql_observation_store_persists_idempotency_and_replays(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'observations.db'}"
    Database(database_url).create_all()
    item = definition(
        capability_id="test.sql.write",
        handler_key="test.sql.write",
        scope="research_write",
        side_effect="idempotent_write",
        idempotency="required",
    )
    catalog = await catalog_with(item)
    calls = 0

    async def handler(*_: object) -> ToolResult:
        nonlocal calls
        calls += 1
        return ToolResult(payload={"value": 11}, source_refs=("fixture:sql",))

    observations = SqlObservationStore(database_url)
    executor = GovernedToolExecutor(
        catalog,
        {item.handler_key: handler},
        observations=observations,
    )
    plan, step = plan_step(item, value=11)
    try:
        first = await executor.execute(mission(permission="research.v1"), plan, step, 1)
        replay = await executor.execute(mission(permission="research.v1"), plan, step, 2)
        persisted = await observations.list(mission().mission_id)
    finally:
        await observations.dispose()

    assert first.status == replay.status == "succeeded"
    assert calls == 1
    assert [row.status for row in persisted] == ["succeeded", "replayed"]
    assert persisted[0].source_refs == ("fixture:sql",)


@pytest.mark.anyio
async def test_read_only_mission_denies_write_and_approval_without_dispatch() -> None:
    item = definition(
        capability_id="test.paper.write",
        handler_key="test.paper.write",
        scope="paper_write",
        side_effect="idempotent_write",
        idempotency="required",
        approval="required",
    )
    catalog = await catalog_with(item)
    calls = 0

    async def handler(*_: object) -> ToolResult:
        nonlocal calls
        calls += 1
        return ToolResult(payload={"value": 1}, source_refs=("fixture:write",))

    executor = GovernedToolExecutor(catalog, {item.handler_key: handler})
    plan, step = plan_step(item, value=1)
    result = await executor.execute(mission(), plan, step, 1)

    assert result.status == "failed"
    assert result.error_category == "permission_denied"
    assert calls == 0


@pytest.mark.anyio
async def test_result_preview_redacts_secrets_and_truncates_large_payload() -> None:
    item = definition(
        output_schema={"type": "object"},
        max_result_bytes=256,
    )
    catalog = await catalog_with(item)

    async def handler(*_: object) -> ToolResult:
        return ToolResult(
            payload={"value": 1, "api_token": "secret-value", "data": "x" * 1_000},
            source_refs=("fixture:large",),
        )

    executor = GovernedToolExecutor(catalog, {item.handler_key: handler})
    plan, step = plan_step(item, value=1)
    result = await executor.execute(mission(), plan, step, 1)
    observations = await executor.observations.list()

    assert result.status == "succeeded"
    assert observations[0].truncated is True
    assert "secret-value" not in str(observations[0].result_preview)


@pytest.mark.anyio
async def test_rate_limit_failures_open_circuit() -> None:
    item = definition()
    catalog = await catalog_with(item)

    async def handler(*_: object) -> ToolResult:
        raise RuntimeError("provider rate limit exceeded")

    executor = GovernedToolExecutor(
        catalog,
        {item.handler_key: handler},
        circuit=CircuitBreaker(failure_threshold=2),
    )
    plan, step = plan_step(item, value=1)
    first = await executor.execute(mission(), plan, step, 1)
    second = await executor.execute(mission(), plan, step, 2)

    assert first.error_category == "rate_limited"
    assert second.error_category == "rate_limited"
    assert executor.circuit.state(item.capability_id).state == "open"
