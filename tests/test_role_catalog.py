from __future__ import annotations

import pytest
from hypertrade.runtime.adapters.supervisor import RoleCatalog
from hypertrade.runtime.domain.supervision import AssignmentCreateV1


def assignment(**updates: object) -> AssignmentCreateV1:
    values: dict[str, object] = {
        "role_id": "market_analyst",
        "objective": "Inspect the bounded market summary",
        "capability_id": "market.summary",
        "context_pack_refs": ("context:ctxp_one@" + "a" * 64,),
    }
    values.update(updates)
    return AssignmentCreateV1.model_validate(values)


def test_builtin_roles_are_reviewed_and_read_only() -> None:
    roles = RoleCatalog().list()

    assert [role.role_id for role in roles] == [
        "critic",
        "evidence_analyst",
        "market_analyst",
        "research_lead",
    ]
    assert all(role.reviewed for role in roles)
    assert all(role.permission_profiles == ("read_only.v1",) for role in roles)


def test_role_catalog_denies_unknown_capability_and_permission_expansion() -> None:
    catalog = RoleCatalog()
    with pytest.raises(ValueError, match="outside role allowlist"):
        catalog.validate(assignment(capability_id="live.order"), "read_only.v1")
    with pytest.raises(ValueError, match="permission"):
        catalog.validate(assignment(), "live.v1")
    with pytest.raises(ValueError, match="not reviewed"):
        catalog.validate(assignment(role_id="invented_agent"), "read_only.v1")
