from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database
from hypertrade.main import create_app
from hypertrade.runtime.adapters.capability_catalog import (
    CapabilityUnavailable,
    InMemoryCapabilityCatalog,
    SqlCapabilityCatalog,
    builtin_capabilities,
)
from hypertrade.runtime.domain.capabilities import (
    CapabilityDefinitionV1,
    CapabilityProposalV1,
    CapabilityReviewV1,
)
from hypertrade.runtime.domain.models import utc_now


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def discovered_definition() -> CapabilityDefinitionV1:
    return CapabilityDefinitionV1(
        capability_id="external.news.search",
        title="External news search",
        description="Search an external reviewed news source.",
        source_owner="external.connector",
        handler_key="external.news.search",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )


def test_capability_api_keeps_discovery_pending_until_admin_review() -> None:
    database = Database("sqlite:///:memory:")
    database.create_all()
    settings = Settings(
        DATABASE_URL="sqlite:///:memory:",
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="secret",
        SESSION_SECRET="capability-api-test-secret",
    )
    with TestClient(create_app(settings=settings, db=database)) as client:
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "secret"},
            ).status_code
            == 200
        )
        active = client.get("/api/agent/capabilities")
        proposal = client.post(
            "/api/agent/capability-proposals",
            json={
                "definition": discovered_definition().model_dump(mode="json"),
                "discovered_from": "mcp://news-server/tools",
            },
        )
        proposal_id = proposal.json()["proposal_id"]
        pending_active = client.get("/api/agent/capabilities")
        reviewed = client.post(
            f"/api/agent/capability-proposals/{proposal_id}/review",
            json={
                "decision": "approve",
                "reason": "Reviewed in the administrative capability gate",
                "idempotency_key": "cap-api-review-001",
            },
        )
        reviewed_active = client.get("/api/agent/capabilities")

    assert active.status_code == proposal.status_code == reviewed.status_code == 200
    builtin_count = len(builtin_capabilities())
    assert len(active.json()["capabilities"]) == builtin_count
    assert len(pending_active.json()["capabilities"]) == builtin_count
    assert reviewed.json()["status"] == "approved"
    assert len(reviewed_active.json()["capabilities"]) == builtin_count + 1


@pytest.mark.anyio
async def test_builtins_are_reviewed_versioned_and_hash_bound() -> None:
    catalog = InMemoryCapabilityCatalog()
    await catalog.bootstrap(builtin_capabilities())

    rows = await catalog.list_active()

    assert len(rows) == len(builtin_capabilities())
    assert all(row.review_status == "reviewed" for row in rows)
    assert all(row.executable() for row in rows)
    assert all(row.contract_hash == row.definition.contract_hash() for row in rows)
    assert all(row.policy_hash == row.definition.policy_hash() for row in rows)


@pytest.mark.anyio
async def test_discovery_stays_pending_until_idempotent_admin_review() -> None:
    catalog = InMemoryCapabilityCatalog()
    proposal = await catalog.propose(
        CapabilityProposalV1(
            definition=discovered_definition(),
            discovered_from="mcp://news-server/tools",
        )
    )

    assert proposal.status == "pending_review"
    with pytest.raises(CapabilityUnavailable):
        catalog.resolve_sync("external.news.search", "1")

    review = CapabilityReviewV1(
        decision="approve",
        reason="Connector contract and policy reviewed",
        actor="admin",
        idempotency_key="review-news-001",
    )
    approved = await catalog.review(proposal.proposal_id, review)
    replay = await catalog.review(proposal.proposal_id, review)

    assert approved.status == "approved"
    assert replay == approved
    assert catalog.resolve_sync("external.news.search", "1").reviewed_by == "admin"


@pytest.mark.anyio
async def test_rejected_proposal_never_enters_active_catalog() -> None:
    catalog = InMemoryCapabilityCatalog()
    proposal = await catalog.propose(
        CapabilityProposalV1(
            definition=discovered_definition(),
            discovered_from="openapi://untrusted/schema",
        )
    )
    rejected = await catalog.review(
        proposal.proposal_id,
        CapabilityReviewV1(
            decision="reject",
            reason="Source owner cannot be verified",
            idempotency_key="reject-news-001",
        ),
    )

    assert rejected.status == "rejected"
    with pytest.raises(CapabilityUnavailable):
        catalog.resolve_sync("external.news.search", "1")


@pytest.mark.anyio
async def test_stale_and_unhealthy_capability_fail_pre_dispatch() -> None:
    catalog = InMemoryCapabilityCatalog()
    await catalog.bootstrap(builtin_capabilities())
    catalog.set_health(
        "market.summary",
        "1",
        "healthy",
        fresh_until=utc_now() - timedelta(seconds=1),
    )
    with pytest.raises(CapabilityUnavailable, match="unavailable"):
        catalog.resolve_sync("market.summary", "1")

    await catalog.bootstrap(builtin_capabilities())
    catalog.set_health("market.summary", "1", "unhealthy")
    with pytest.raises(CapabilityUnavailable, match="unavailable"):
        catalog.resolve_sync("market.summary", "1")


@pytest.mark.anyio
async def test_sql_catalog_persists_reviewed_snapshot_and_proposal(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'catalog.db'}"
    Database(url).create_all()
    first = SqlCapabilityCatalog(url)
    await first.bootstrap(builtin_capabilities())
    proposal = await first.propose(
        CapabilityProposalV1(
            definition=discovered_definition(),
            discovered_from="mcp://news-server/tools",
        )
    )
    await first.dispose()

    second = SqlCapabilityCatalog(url)
    await second.load()
    rows = await second.list_active()
    proposals = await second.list_proposals()
    await second.dispose()

    assert len(rows) == len(builtin_capabilities())
    assert proposals[0].proposal_id == proposal.proposal_id
    assert proposals[0].status == "pending_review"


def test_write_capability_contract_requires_idempotency_and_trading_approval() -> None:
    with pytest.raises(ValueError, match="idempotency"):
        CapabilityDefinitionV1(
            capability_id="research.write",
            title="Research write",
            description="Write a research record.",
            source_owner="test",
            handler_key="research.write",
            scope="research_write",
            side_effect="idempotent_write",
        )
    with pytest.raises(ValueError, match="approval"):
        CapabilityDefinitionV1(
            capability_id="paper.write",
            title="Paper write",
            description="Write paper state.",
            source_owner="test",
            handler_key="paper.write",
            scope="paper_write",
            side_effect="idempotent_write",
            idempotency="required",
        )
