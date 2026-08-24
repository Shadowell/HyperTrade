"""Sprint-139: LLM team workers producing structured, auditable handoffs.

The worker reasons over Context Pack evidence with no dispatch authority.
Every test pins a trust boundary: citation requirement, output hash binding,
forbidden-transcript guard, repair-then-degrade semantics, and honest failure
on unreadable packs.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypertrade.providers.chat import ChatResponse
from hypertrade.runtime.adapters.supervisor import (
    BoundedSupervisor,
    InMemorySupervisionStore,
    RoleCatalog,
    build_team_worker,
    llm_assignment_worker,
)
from hypertrade.runtime.domain.models import MissionProjection
from hypertrade.runtime.domain.supervision import (
    AssignmentCreateV1,
    AssignmentV1,
    BudgetReservationV1,
    TeamRunRequestV1,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _ScriptedProvider:
    def __init__(self, *responses: str | Exception) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []
        self.name = "scripted"
        self.model = "team-worker-test"

    def chat(self, messages: list[dict[str, str]]) -> ChatResponse:
        self.calls.append(messages)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return ChatResponse(content=item)


def _assignment(
    role_id: str = "market_analyst",
    capability_id: str = "market.summary",
    objective: str = "Assess BTC market posture from the pack",
) -> AssignmentV1:
    return AssignmentV1(
        assignment_id=f"asgn_{role_id}",
        mission_id="mis_team_01",
        role_id=role_id,
        objective=objective,
        capability_id=capability_id,
        depends_on=(),
        context_pack_refs=("context:ctxp_01@" + "a" * 64,),
        artifact_refs=(),
        reservation=BudgetReservationV1(),
    )


def _pack_ref_content() -> dict[str, Any]:
    class _Decision:
        rendered_content = "BTC funding rate 0.01%; open interest up 4%; price 77,000."

    class _Pack:
        decisions = (_Decision(),)

    return _Pack()


async def _pack_loader(ref: str) -> Any:
    if ref.startswith("context:ctxp_01"):
        return _pack_ref_content()
    return None


def _valid_content() -> str:
    return json.dumps(
        {
            "summary": "BTC posture is neutral-positive on funding and OI.",
            "claims": {
                "market.funding": "0.01%",
                "market.oi_change": "up 4%",
                "market.posture": "neutral-positive",
            },
            "unknowns": ["spot volume trend unavailable in pack"],
        },
        ensure_ascii=False,
    )


@pytest.mark.anyio
async def test_llm_worker_produces_grounded_structured_handoff() -> None:
    provider = _ScriptedProvider(_valid_content())
    worker = llm_assignment_worker(provider, pack_loader=_pack_loader)

    handoff = await worker(_assignment())

    assert handoff.role_id == "market_analyst"
    assert "neutral-positive" in handoff.summary
    assert handoff.claims["market.funding"] == "0.01%"
    assert handoff.unknowns == ("spot volume trend unavailable in pack",)
    # Citation contract: the handoff must cite its assigned Context Pack.
    assert handoff.source_refs[0].startswith("context:ctxp_01")
    assert handoff.output_hash
    # Evidence actually reached the model.
    prompt = provider.calls[0][1]["content"]
    assert "funding rate 0.01%" in prompt
    assert "market_analyst" in provider.calls[0][0]["content"]


@pytest.mark.anyio
async def test_llm_worker_repairs_invalid_json_then_succeeds() -> None:
    provider = _ScriptedProvider(
        "summary about market things without any json payload",
        _valid_content(),
    )
    worker = llm_assignment_worker(provider, pack_loader=_pack_loader)

    handoff = await worker(_assignment())

    assert handoff.claims["market.posture"] == "neutral-positive"
    assert len(provider.calls) == 2


@pytest.mark.anyio
async def test_llm_worker_degrades_with_audit_marker_after_two_failures() -> None:
    provider = _ScriptedProvider("not json at all", "still not json")
    worker = llm_assignment_worker(provider, pack_loader=_pack_loader)

    handoff = await worker(_assignment())

    assert handoff.claims["market_analyst.status"] == "completed"
    assert handoff.claims["market_analyst.mode"] == "deterministic_fallback"


@pytest.mark.anyio
async def test_llm_worker_degrades_when_provider_raises() -> None:
    provider = _ScriptedProvider(RuntimeError("upstream down"))
    worker = llm_assignment_worker(provider, pack_loader=_pack_loader)

    handoff = await worker(_assignment())

    assert handoff.claims["market_analyst.mode"] == "deterministic_fallback"


@pytest.mark.anyio
async def test_llm_worker_fails_honestly_on_unreadable_pack() -> None:
    provider = _ScriptedProvider(_valid_content())

    async def missing_loader(ref: str) -> Any:
        return None

    worker = llm_assignment_worker(provider, pack_loader=missing_loader)

    with pytest.raises(ValueError, match="no readable context pack"):
        await worker(_assignment())


@pytest.mark.anyio
async def test_forbidden_transcript_content_is_rejected_via_repair() -> None:
    poisoned = json.dumps(
        {
            "summary": "Here is my private reasoning chain of thought for you",
            "claims": {"k": "v"},
            "unknowns": [],
        }
    )
    provider = _ScriptedProvider(poisoned, _valid_content())
    worker = llm_assignment_worker(provider, pack_loader=_pack_loader)

    handoff = await worker(_assignment())

    assert "chain of thought" not in handoff.summary.lower()
    assert handoff.claims["market.posture"] == "neutral-positive"


@pytest.mark.anyio
async def test_factory_flag_off_returns_deterministic_worker() -> None:
    class _Settings:
        agent_team_llm_worker_enabled = False

    class _OnSettings:
        agent_team_llm_worker_enabled = True

    provider = _ScriptedProvider(_valid_content())

    off = build_team_worker(_Settings(), provider=provider, pack_loader=_pack_loader)
    assignment = _assignment()
    handoff = await off(assignment)
    # Flag off: canned handoff without any provider call.
    assert provider.calls == []
    assert handoff.claims == {"market_analyst.status": "completed"}

    on = build_team_worker(_OnSettings(), provider=provider, pack_loader=_pack_loader)
    llm_handoff = await on(assignment)
    assert llm_handoff.claims["market.posture"] == "neutral-positive"
    assert len(provider.calls) == 1


@pytest.mark.anyio
async def test_supervisor_end_to_end_llm_team_with_conflict_merge() -> None:
    """多角色真对抗：两个 worker 的矛盾 claim 必须进入冲突合并而非被吞掉。"""
    provider = _ScriptedProvider(
        json.dumps(
            {
                "summary": "Bull case: funding and OI support upside continuation.",
                "claims": {"market.posture": "bullish"},
                "unknowns": [],
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "summary": "Bear case: the same pack shows distribution risk.",
                "claims": {"market.posture": "bearish"},
                "unknowns": [],
            },
            ensure_ascii=False,
        ),
    )
    worker = llm_assignment_worker(provider, pack_loader=_pack_loader)
    supervisor = BoundedSupervisor(InMemorySupervisionStore(), RoleCatalog())
    from hypertrade.runtime.domain.models import (
        MissionBudgetV1,
        MissionStatus,
        SuccessCriterionV1,
    )

    mission = MissionProjection(
        mission_id="mis_team_01",
        objective="Assess BTC posture",
        original_objective="Assess BTC posture",
        success_criteria=(
            SuccessCriterionV1(
                criterion_id="all_validated",
                kind="all_steps_validated",
                description="Every step validated.",
            ),
        ),
        constraints=(),
        status=MissionStatus.RUNNING,
        budget=MissionBudgetV1(),
        permission_profile_ref="read_only.v1",
        context_policy_ref="mission_context.v1",
        created_by="operator",
    )
    request = TeamRunRequestV1(
        assignments=(
            AssignmentCreateV1(
                role_id="market_analyst",
                objective="Read market posture",
                capability_id="market.summary",
                context_pack_refs=("context:ctxp_01@" + "a" * 64,),
            ),
            AssignmentCreateV1(
                role_id="critic",
                objective="Challenge the market posture claim",
                capability_id="runtime.objective_inspection",
                context_pack_refs=("context:ctxp_01@" + "a" * 64,),
            ),
        ),
        idempotency_key="team-llm-worker-e2e",
    )

    merge = await supervisor.run(mission, request, worker)

    assert len(merge.handoff_refs) == 2
    assert merge.agreed_claims == {}
    assert any(conflict.claim_key == "market.posture" for conflict in merge.conflicts)
    assert any(unknown.startswith("conflict:market.posture") for unknown in merge.unknowns)
